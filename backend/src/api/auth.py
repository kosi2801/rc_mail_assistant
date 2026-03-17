"""Auth router: Gmail OAuth 2.0 Authorization Code flow endpoints.

Implements contracts/auth.md:
  GET  /auth/gmail/initiate   → 302 to Google consent screen (T012)
  GET  /auth/gmail/callback   → exchange code, store token, redirect (T013)
  POST /auth/gmail/disconnect → delete credential, redirect or HTMX (T020)

Security:
  - CSRF state signed with itsdangerous.URLSafeTimedSerializer (SECRET_KEY)
  - oauth_state cookie: HttpOnly, SameSite=Lax, Max-Age=600, Secure if HTTPS
  - FR-010: refresh token MUST NOT appear in logs or responses
"""
from __future__ import annotations

import asyncio
import secrets

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_session
from src.logging_config import get_logger
from src.services.gmail_credential_service import GmailCredentialService, mask_email

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

_GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
_STATE_MAX_AGE = 600  # 10 minutes


def _get_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key)


def _get_callback_url(request: Request) -> str:
    """Build the absolute callback URL from the current request."""
    base = str(request.base_url).rstrip("/")
    return f"{base}/auth/gmail/callback"


def _build_flow(redirect_uri: str) -> Flow:
    """Build a google_auth_oauthlib Flow from settings."""
    client_config = {
        "web": {
            "client_id": settings.gmail_client_id,
            "client_secret": settings.gmail_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }
    flow = Flow.from_client_config(
        client_config=client_config,
        scopes=_GMAIL_SCOPES,
        redirect_uri=redirect_uri,
    )
    return flow


# ---------------------------------------------------------------------------
# GET /auth/gmail/initiate
# ---------------------------------------------------------------------------


@router.get("/gmail/initiate")
async def gmail_initiate(request: Request):
    """Start the OAuth 2.0 Authorization Code flow (contracts/auth.md §1).

    On success: 302 to Google consent screen + sets HttpOnly CSRF state cookie.
    If GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET are not configured: 302 to
    /config?gmail_error=oauth_unconfigured.
    """
    if not settings.gmail_client_id or not settings.gmail_client_secret:
        logger.warning("gmail_initiate_unconfigured")
        return RedirectResponse(url="/config?gmail_error=oauth_unconfigured", status_code=302)

    # Generate CSRF state value and sign it for the cookie
    state = secrets.token_urlsafe(32)
    signed_state = _get_serializer().dumps(state)

    # Build consent URL
    redirect_uri = _get_callback_url(request)
    flow = _build_flow(redirect_uri)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=state,
    )

    logger.info("gmail_initiate", redirect_uri=redirect_uri)

    # Build response: 302 to Google + set CSRF cookie
    response = RedirectResponse(url=auth_url, status_code=302)
    is_https = request.url.scheme == "https"
    response.set_cookie(
        key="oauth_state",
        value=signed_state,
        httponly=True,
        samesite="lax",
        max_age=_STATE_MAX_AGE,
        path="/",
        secure=is_https,
    )
    return response


# ---------------------------------------------------------------------------
# GET /auth/gmail/callback
# ---------------------------------------------------------------------------


@router.get("/gmail/callback")
async def gmail_callback(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Receive authorization code from Google, validate CSRF, store token.

    Processing steps (contracts/auth.md §2):
    1. Read + verify oauth_state cookie (signature + 10-min expiry)
    2. Compare unsigned state to query param
    3. Clear the cookie (one-use)
    4. Handle ?error= from Google
    5. Exchange code for tokens
    6. Retrieve account email via getProfile
    7. Store encrypted refresh token via GmailCredentialService
    8. Redirect to /config?gmail_connected=1
    """
    signed_cookie = request.cookies.get("oauth_state")

    # --- Always-clear helper ---
    def _redirect_with_cleared_cookie(url: str) -> RedirectResponse:
        resp = RedirectResponse(url=url, status_code=302)
        resp.delete_cookie("oauth_state", path="/")
        return resp

    if not signed_cookie:
        logger.warning("gmail_callback_missing_state_cookie")
        return HTMLResponse(
            content="<p>Missing CSRF state cookie. Please try connecting again.</p>",
            status_code=400,
        )

    # Step 1: Verify signature + expiry
    try:
        unsigned_state = _get_serializer().loads(signed_cookie, max_age=_STATE_MAX_AGE)
    except SignatureExpired:
        logger.warning("gmail_callback_state_expired")
        return HTMLResponse(
            content="<p>OAuth state expired (10-minute window). Please try connecting again.</p>",
            status_code=400,
        )
    except BadSignature:
        logger.warning("gmail_callback_bad_signature")
        return HTMLResponse(
            content="<p>Invalid OAuth state. Please try connecting again.</p>",
            status_code=400,
        )

    # Step 2: Compare to query param
    query_state = request.query_params.get("state", "")
    if unsigned_state != query_state:
        logger.warning("gmail_callback_state_mismatch")
        return HTMLResponse(
            content="<p>OAuth state mismatch. Possible CSRF attempt.</p>",
            status_code=400,
        )

    # Step 4: Handle Google error (e.g. user cancelled)
    google_error = request.query_params.get("error")
    if google_error:
        logger.warning("gmail_callback_google_error", error=google_error)
        return _redirect_with_cleared_cookie("/config?gmail_error=cancelled")

    # Step 5: Exchange code for tokens
    code = request.query_params.get("code")
    if not code:
        logger.warning("gmail_callback_no_code")
        return _redirect_with_cleared_cookie("/config?gmail_error=cancelled")

    redirect_uri = _get_callback_url(request)
    flow = _build_flow(redirect_uri)

    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: flow.fetch_token(code=code)
        )
    except Exception as exc:
        logger.warning("gmail_callback_token_exchange_failed", error=str(exc))
        return _redirect_with_cleared_cookie("/config?gmail_error=cancelled")

    creds = flow.credentials

    # Validate refresh token was issued
    if not creds.refresh_token:
        logger.warning("gmail_callback_no_refresh_token")
        return _redirect_with_cleared_cookie("/config?gmail_error=no_refresh_token")

    # Step 6: Retrieve account email
    try:
        gmail_svc = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: build("gmail", "v1", credentials=creds, cache_discovery=False),
        )
        profile = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: gmail_svc.users().getProfile(userId="me").execute(),
        )
        account_email = profile.get("emailAddress", "unknown@unknown")
    except Exception as exc:
        logger.warning("gmail_callback_profile_fetch_failed", error=str(exc))
        account_email = "unknown@unknown"

    # Step 7: Store encrypted refresh token
    try:
        cred_svc = GmailCredentialService(session)
        await cred_svc.upsert(
            plaintext_token=creds.refresh_token,
            account_email=account_email,
        )
    except Exception as exc:
        logger.error("gmail_callback_db_write_failed", error=str(exc))
        return _redirect_with_cleared_cookie("/config?gmail_error=db_write_failed")

    logger.info("gmail_callback_success", account_email=mask_email(account_email), token_stored=True)

    # Step 8: Redirect to config page with success indicator
    return _redirect_with_cleared_cookie("/config?gmail_connected=1")


# ---------------------------------------------------------------------------
# POST /auth/gmail/disconnect
# ---------------------------------------------------------------------------


@router.post("/gmail/disconnect")
async def gmail_disconnect(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Disconnect Gmail by deleting the stored credential.

    If called via HTMX (HX-Request header present):
        Returns 200 with State A HTML fragment for hx-swap="outerHTML".
    Otherwise:
        Returns 302 to /config?gmail_disconnected=1.
    """
    svc = GmailCredentialService(session)
    await svc.delete()

    is_htmx = request.headers.get("HX-Request") == "true"

    if is_htmx:
        # Return State A fragment — suitable for hx-target="#gmail-connection-section"
        oauth_configured = bool(
            settings.gmail_client_id and settings.gmail_client_secret
        )
        fragment = _render_state_a(oauth_configured)
        return HTMLResponse(content=fragment, status_code=200)

    return RedirectResponse(url="/config?gmail_disconnected=1", status_code=302)


def _render_state_a(oauth_configured: bool) -> str:
    """Render the State A (Not Connected) HTML fragment."""
    if oauth_configured:
        connect_button = (
            '<a href="/auth/gmail/initiate" '
            'style="display:inline-block;padding:0.35rem 0.75rem;font-size:0.85rem;'
            'background:#1565c0;color:#fff;border:none;border-radius:4px;'
            'text-decoration:none;cursor:pointer">Connect Gmail</a>'
        )
    else:
        connect_button = (
            '<button disabled style="padding:0.35rem 0.75rem;font-size:0.85rem;cursor:not-allowed;'
            'opacity:0.6">Connect Gmail (app credentials required)</button>'
            '<p style="font-size:0.8rem;color:#6c757d;margin-top:0.4rem">'
            'Set <code>GMAIL_CLIENT_ID</code> and <code>GMAIL_CLIENT_SECRET</code> '
            "in <code>.env</code> and restart the application.</p>"
        )
    return (
        '<fieldset id="gmail-connection-section" '
        'style="border:1px solid #dee2e6;border-radius:4px;padding:1rem">'
        '<legend style="font-weight:600;padding:0 0.25rem">Gmail Connection</legend>'
        '<p style="font-size:0.85rem;color:#6c757d;margin-bottom:0.75rem">'
        "Status: <strong>Not connected</strong></p>"
        f"{connect_button}"
        "</fieldset>"
    )
