"""Unit tests for GmailAdapter internals (no real Gmail API calls)."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# We test GmailAdapter methods directly without instantiating (to avoid credential
# checks). We import the class and call methods on a mock-constructed instance.


def _make_adapter():
    """Build a GmailAdapter instance bypassing __init__ credential checks."""
    from src.adapters.gmail_adapter import GmailAdapter

    adapter = object.__new__(GmailAdapter)
    adapter._svc = MagicMock()
    return adapter


def _b64(text: str) -> str:
    """Encode text as URL-safe base64 (no padding) for use in test payloads."""
    return base64.urlsafe_b64encode(text.encode("utf-8")).rstrip(b"=").decode("ascii")


def _make_msg(
    msg_id: str = "abc123",
    thread_id: str = "thread1",
    from_header: str = "Alice <alice@example.com>",
    subject: str = "Test Subject",
    internal_date_ms: int = 1_700_000_000_000,
    parts: list | None = None,
    body_data: str = "",
    mime_type: str = "text/plain",
) -> dict:
    """Helper: build a Gmail API message dict."""
    msg: dict = {
        "id": msg_id,
        "threadId": thread_id,
        "internalDate": str(internal_date_ms),
        "payload": {
            "mimeType": mime_type,
            "headers": [
                {"name": "From", "value": from_header},
                {"name": "Subject", "value": subject},
            ],
            "body": {"data": body_data},
        },
    }
    if parts is not None:
        msg["payload"]["parts"] = parts
    return msg


# ---------------------------------------------------------------------------
# Test 1: multipart/alternative payload returns text/plain verbatim
# ---------------------------------------------------------------------------


def test_extract_email_prefers_plain_text():
    """_extract_email with multipart/alternative returns text/plain part verbatim."""
    adapter = _make_adapter()
    plain_text = "Hello, plain text!"
    html_text = "<p>Hello, <b>HTML</b>!</p>"
    msg = _make_msg(
        parts=[
            {
                "mimeType": "text/plain",
                "body": {"data": _b64(plain_text)},
            },
            {
                "mimeType": "text/html",
                "body": {"data": _b64(html_text)},
            },
        ]
    )
    result = adapter._extract_email(msg)
    assert result.body_plain_text == plain_text


# ---------------------------------------------------------------------------
# Test 2: HTML-only payload returns html2text-converted plain text, no tags
# ---------------------------------------------------------------------------


def test_extract_email_html_only_converts_to_plain():
    """_extract_email with HTML-only payload returns plain text (no HTML tags)."""
    adapter = _make_adapter()
    html_text = "<p>Hello <b>World</b>! <a href='http://x.com'>link</a></p>"
    msg = _make_msg(
        parts=[
            {
                "mimeType": "text/html",
                "body": {"data": _b64(html_text)},
            }
        ]
    )
    result = adapter._extract_email(msg)
    assert "<" not in result.body_plain_text
    assert ">" not in result.body_plain_text
    assert "World" in result.body_plain_text


# ---------------------------------------------------------------------------
# Test 3: empty body returns empty string without raising
# ---------------------------------------------------------------------------


def test_extract_email_empty_body_returns_empty_string():
    """_extract_email with empty body data returns '' without error."""
    adapter = _make_adapter()
    msg = _make_msg(body_data="")  # no parts, empty body.data
    result = adapter._extract_email(msg)
    assert result.body_plain_text == ""


# ---------------------------------------------------------------------------
# Test 4: 100 KB boundary — exact limit stored, 100001 bytes truncated
# ---------------------------------------------------------------------------


def test_body_truncation_boundary():
    """Body at exactly 100,000 bytes is stored without truncation; 100,001 bytes is truncated."""
    from src.adapters.gmail_adapter import _BODY_LIMIT_BYTES, _TRUNCATION_SUFFIX

    adapter = _make_adapter()

    # Exactly at limit — no truncation
    exact_text = "A" * _BODY_LIMIT_BYTES
    msg_exact = _make_msg(body_data=_b64(exact_text))
    result_exact = adapter._extract_email(msg_exact)
    assert len(result_exact.body_plain_text.encode("utf-8")) == _BODY_LIMIT_BYTES
    assert not result_exact.body_plain_text.endswith(_TRUNCATION_SUFFIX)

    # One byte over limit — truncated
    over_text = "A" * (_BODY_LIMIT_BYTES + 1)
    msg_over = _make_msg(body_data=_b64(over_text))
    result_over = adapter._extract_email(msg_over)
    assert result_over.body_plain_text.endswith(_TRUNCATION_SUFFIX)
    body_bytes = result_over.body_plain_text.encode("utf-8")
    assert len(body_bytes) <= _BODY_LIMIT_BYTES + len(_TRUNCATION_SUFFIX.encode("utf-8"))


# ---------------------------------------------------------------------------
# Test 5: URL-safe base64 without padding is decoded correctly
# ---------------------------------------------------------------------------


def test_decode_b64_without_padding():
    """URL-safe base64 data without padding is decoded correctly when '==' appended."""
    from src.adapters.gmail_adapter import GmailAdapter

    original = "Hello, World! This is a test message."
    # Encode without padding
    encoded_no_padding = base64.urlsafe_b64encode(original.encode("utf-8")).rstrip(b"=").decode()
    assert "=" not in encoded_no_padding  # confirm no padding present

    decoded = GmailAdapter._decode_b64(encoded_no_padding)
    assert decoded == original


# ---------------------------------------------------------------------------
# Test 6: _html_to_text strips links and img tags
# ---------------------------------------------------------------------------


def test_html_to_text_strips_links_and_images():
    """_html_to_text removes <a href> link URLs and <img> tags (ignore_links, ignore_images)."""
    from src.adapters.gmail_adapter import GmailAdapter

    html = (
        '<p>Click <a href="http://tracker.example.com/pixel">here</a>.</p>'
        '<img src="http://tracker.example.com/pixel.gif" width="1" height="1" />'
        "<p>Visit request confirmed.</p>"
    )
    result = GmailAdapter._html_to_text(html)
    # Link URL should not appear in output
    assert "http://tracker.example.com" not in result
    # Image should not appear
    assert "<img" not in result
    # Meaningful text should be preserved
    assert "here" in result
    assert "Visit request confirmed" in result
