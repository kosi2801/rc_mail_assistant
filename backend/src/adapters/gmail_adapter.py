"""GmailAdapter — concrete Gmail API implementation of MailAdapter (research.md)."""
from __future__ import annotations

import asyncio
import base64
import email.utils
from datetime import datetime, timezone
from typing import Any

import html2text as html2text_lib
import google.auth.exceptions
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.config import settings as app_settings
from src.logging_config import get_logger
from src.services.mail_service import (
    ConnectorStatus,
    EmailMessage,
    MailAdapter,
    MailCredentialsError,
)

logger = get_logger(__name__)

_BODY_LIMIT_BYTES = 100_000
_TRUNCATION_SUFFIX = " [TRUNCATED]"


def _should_retry(exc: BaseException) -> bool:
    """Return True for HttpError with retriable status codes (429, 500, 503)."""
    if isinstance(exc, HttpError):
        try:
            return exc.resp.status in (429, 500, 503)
        except Exception:
            return False
    return False


class GmailAdapter(MailAdapter):
    """Full Gmail API adapter (research.md decisions §1-§10).

    Credential construction (§1):
        Builds ``google.oauth2.credentials.Credentials`` from env vars and
        eagerly calls ``creds.refresh(Request())`` to fail fast on bad creds.

    Blocking calls (§2):
        All ``googleapiclient`` calls wrapped in ``run_in_executor`` using
        ``asyncio.get_event_loop()``, with ``cache_discovery=False``.
    """

    def __init__(self) -> None:
        creds = self._build_credentials()
        self._svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
        logger.info("gmail_adapter_initialized")

    # ------------------------------------------------------------------
    # Credential helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_credentials() -> Credentials:
        """Build and eagerly refresh OAuth2 credentials (research §1)."""
        if not all(
            [
                app_settings.gmail_client_id,
                app_settings.gmail_client_secret,
                app_settings.gmail_refresh_token,
            ]
        ):
            raise MailCredentialsError(
                "Gmail credentials could not be loaded. "
                "Check GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, and GMAIL_REFRESH_TOKEN in .env."
            )

        creds = Credentials(
            token=None,
            refresh_token=app_settings.gmail_refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=app_settings.gmail_client_id,
            client_secret=app_settings.gmail_client_secret,
        )
        # Eagerly refresh to fail fast on bad creds (research §1)
        try:
            creds.refresh(Request())
        except google.auth.exceptions.RefreshError as exc:
            raise google.auth.exceptions.RefreshError(
                f"Failed to refresh Gmail credentials: {exc}"
            ) from exc
        return creds

    # ------------------------------------------------------------------
    # Executor helper
    # ------------------------------------------------------------------

    @staticmethod
    async def _run(fn):
        """Execute a blocking callable in the default thread pool (research §2)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn)

    # ------------------------------------------------------------------
    # Retry-decorated API executor
    # ------------------------------------------------------------------

    def _execute(self, request):
        """Execute a Google API request with retry on 429/500/503 (research §4).

        The retry parameters (max_retries) are read from the DB at call time
        via the module-level settings row passed to fetch_new_emails; for the
        retry decorator we use a module-level default of 3, which is overridden
        per-call via the wrapper below.
        """
        return request.execute()

    def _make_retrying_execute(self, max_retries: int):
        """Return a version of _execute with the given retry limit baked in."""

        @retry(
            wait=wait_exponential(multiplier=1, min=2, max=30),
            stop=stop_after_attempt(max_retries),
            retry=retry_if_exception(_should_retry),
            reraise=True,
        )
        def _inner(req):
            return req.execute()

        return _inner

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def get_status(self) -> ConnectorStatus:
        """Credential presence check — no outbound API call (FR-016)."""
        if not all(
            [
                app_settings.gmail_client_id,
                app_settings.gmail_client_secret,
                app_settings.gmail_refresh_token,
            ]
        ):
            return ConnectorStatus.UNCONFIGURED
        return ConnectorStatus.OK

    async def fetch_new_emails(
        self,
        since: datetime | None,
        mail_filter: str = "in:inbox",
        max_retries: int = 3,
    ) -> list[EmailMessage]:
        """Fetch new emails from Gmail matching the configured filter (research §3).

        Args:
            since: Lower-bound datetime (UTC). ``None`` = first-sync, no date lower bound.
            mail_filter: Gmail search query (default: ``"in:inbox"``).
            max_retries: Maximum retry attempts for retriable API errors.

        Returns:
            List of EmailMessage objects.
        """

        execute = self._make_retrying_execute(max_retries)

        # Build Gmail query (research §3)
        query = mail_filter
        if since is not None:
            epoch = int(since.timestamp())
            query = f"{query} after:{epoch}"

        logger.info("gmail_fetch_start", query=query)

        messages: list[EmailMessage] = []
        page_token: str | None = None

        while True:
            # List messages page (wrapped in executor)
            list_kwargs: dict[str, Any] = {"userId": "me", "q": query}
            if page_token:
                list_kwargs["pageToken"] = page_token

            list_req = self._svc.users().messages().list(**list_kwargs)
            response = await self._run(lambda req=list_req: execute(req))

            msg_stubs = response.get("messages", [])
            for stub in msg_stubs:
                msg_id = stub["id"]
                get_req = self._svc.users().messages().get(
                    userId="me", id=msg_id, format="full"
                )
                msg_data = await self._run(lambda req=get_req: execute(req))
                email_msg = self._extract_email(msg_data)
                messages.append(email_msg)

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        logger.info("gmail_fetch_done", count=len(messages))
        return messages

    # ------------------------------------------------------------------
    # Internal: email parsing
    # ------------------------------------------------------------------

    def _extract_email(self, msg_data: dict) -> EmailMessage:
        """Parse a Gmail API message dict into an EmailMessage (research §6)."""
        # internalDate is milliseconds epoch → UTC datetime
        internal_date_ms = int(msg_data.get("internalDate", 0))
        received_at = datetime.fromtimestamp(internal_date_ms / 1000.0, tz=timezone.utc)

        # Parse headers
        headers: list[dict] = msg_data.get("payload", {}).get("headers", [])
        header_map = {h["name"].lower(): h["value"] for h in headers}

        from_raw = header_map.get("from", "")
        sender_name, sender_email = self._parse_from_header(from_raw)
        subject = header_map.get("subject", "")

        # Extract body
        payload = msg_data.get("payload", {})
        body_text = self._extract_body(payload)

        # 100 KB truncation (FR-021) — operate on bytes
        encoded = body_text.encode("utf-8")
        if len(encoded) > _BODY_LIMIT_BYTES:
            # Slice at byte boundary, decode safely
            truncated = encoded[:_BODY_LIMIT_BYTES].decode("utf-8", errors="ignore")
            body_text = truncated + _TRUNCATION_SUFFIX

        return EmailMessage(
            gmail_message_id=msg_data["id"],
            gmail_thread_id=msg_data.get("threadId", ""),
            sender_name=sender_name,
            sender_email=sender_email,
            subject=subject,
            received_at=received_at,
            body_plain_text=body_text,
        )

    @staticmethod
    def _parse_from_header(from_value: str) -> tuple[str, str]:
        """Parse a From header into (display_name, email_address)."""
        name, addr = email.utils.parseaddr(from_value)
        return name or addr, addr

    def _extract_body(self, payload: dict) -> str:
        """Recursively traverse payload.parts to find the best body text (research §6).

        Preference order: text/plain > text/html (via html2text).
        Falls back to payload.body.data if no parts present.
        """
        mime_type: str = payload.get("mimeType", "")
        parts: list[dict] = payload.get("parts", [])

        if parts:
            # Prefer text/plain
            for part in parts:
                if part.get("mimeType") == "text/plain":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        return self._decode_b64(data)
            # Fallback: text/html
            for part in parts:
                if part.get("mimeType") == "text/html":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        return self._html_to_text(self._decode_b64(data))
            # Recurse into multipart/* sub-parts
            for part in parts:
                sub_mime = part.get("mimeType", "")
                if sub_mime.startswith("multipart/"):
                    result = self._extract_body(part)
                    if result:
                        return result
            return ""
        else:
            # No parts — inline body in payload.body.data (T027 edge case)
            data = payload.get("body", {}).get("data", "")
            if not data:
                return ""
            decoded = self._decode_b64(data)
            if mime_type == "text/html":
                return self._html_to_text(decoded)
            return decoded

    @staticmethod
    def _decode_b64(data: str) -> str:
        """Decode URL-safe base64 with padding fix (research §6)."""
        # Append "==" before decode to handle missing padding (research §6)
        padded = data + "=="
        raw_bytes = base64.urlsafe_b64decode(padded)
        return raw_bytes.decode("utf-8", errors="replace")

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Convert HTML to plain text using html2text (research §7)."""
        converter = html2text_lib.HTML2Text()
        converter.ignore_links = True
        converter.ignore_images = True
        converter.ignore_emphasis = True
        converter.body_width = 0
        converter.skip_internal_links = True
        return converter.handle(html).strip()
