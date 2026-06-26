"""Tests for the cookie-upload validation and test-email endpoints.

These call the route handlers directly so we don't boot the scheduler/app.
"""
import asyncio
import io

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.datastructures import UploadFile as StarletteUploadFile

from app import __version__, config, database as db, main, notify

VALID = b"# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t9999999999\tSID\tabc\n"


def _upload(content: bytes):
    headers = Headers({"content-type": "text/plain"})
    return StarletteUploadFile(
        file=io.BytesIO(content), size=len(content),
        filename="cookies.txt", headers=headers,
    )


def test_upload_valid_cookies_saved(tmp_path, monkeypatch):
    dest = tmp_path / "cookies.txt"
    monkeypatch.setattr(main, "COOKIES_FILE", str(dest))
    resp = asyncio.run(main.upload_cookies(_upload(VALID)))
    assert resp.status_code == 302
    assert dest.read_bytes() == VALID


def test_upload_empty_cookies_rejected(tmp_path, monkeypatch):
    dest = tmp_path / "cookies.txt"
    monkeypatch.setattr(main, "COOKIES_FILE", str(dest))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.upload_cookies(_upload(b"")))
    assert exc.value.status_code == 400
    assert not dest.exists()  # nothing written


def test_upload_invalid_does_not_clobber_existing(tmp_path, monkeypatch):
    dest = tmp_path / "cookies.txt"
    dest.write_bytes(VALID)  # a previously-working file
    monkeypatch.setattr(main, "COOKIES_FILE", str(dest))
    with pytest.raises(HTTPException):
        asyncio.run(main.upload_cookies(_upload(b"garbage, not cookies")))
    assert dest.read_bytes() == VALID  # original preserved
    assert not (tmp_path / "cookies.txt.upload").exists()  # temp cleaned up


def test_test_email_unconfigured_returns_400(monkeypatch):
    monkeypatch.setattr(notify, "_smtp_configured", lambda: False)
    with pytest.raises(HTTPException) as exc:
        main.test_email()
    assert exc.value.status_code == 400


def test_test_email_sends_when_configured(monkeypatch):
    monkeypatch.setattr(notify, "_smtp_configured", lambda: True)
    sent = {}
    monkeypatch.setattr(notify, "send_cookie_alert", lambda force=False: sent.setdefault("f", force) or True)
    resp = main.test_email()
    assert resp.status_code == 302
    assert sent["f"] is True  # forced past the cooldown


def test_health_reports_version():
    body = main.health()
    assert body["status"] == "ok"
    assert body["version"] == main.VERSION


def test_served_version_matches_package():
    # Guards against the package __version__ drifting from what /health serves
    # (VERSION may have a "+<gitsha>" suffix appended locally).
    assert main.VERSION.split("+", 1)[0] == __version__


def test_app_title_is_slipcast():
    assert main.app.title == "Slipcast"


def test_ui_shows_slipcast_branding():
    db.init_db()
    html = main._render_ui()
    assert "<title>Slipcast</title>" in html
    assert "<h1>Slipcast</h1>" in html
