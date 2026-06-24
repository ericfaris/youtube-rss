"""Tests for app.notify cookie-alert emailing (debounce + SMTP transport)."""
import time

import pytest

from app import config, notify


@pytest.fixture
def smtp(monkeypatch, tmp_path):
    """Configure SMTP + an isolated alert-state file, and capture sent mail."""
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setattr(config, "SMTP_PORT", 587)
    monkeypatch.setattr(config, "SMTP_USER", "me@gmail.com")
    monkeypatch.setattr(config, "SMTP_PASS", "app-password")
    monkeypatch.setattr(config, "SMTP_FROM", "me@gmail.com")
    monkeypatch.setattr(config, "ALERT_EMAIL", "me@gmail.com")
    monkeypatch.setattr(config, "ALERT_COOLDOWN_HOURS", 24)
    monkeypatch.setattr(notify, "_ALERT_STATE_FILE", str(tmp_path / ".alert_state"))

    sent = []
    monkeypatch.setattr(notify, "_send", lambda msg: sent.append(msg))
    return sent


def test_not_sent_when_unconfigured(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SMTP_HOST", "")
    monkeypatch.setattr(config, "SMTP_USER", "")
    monkeypatch.setattr(config, "SMTP_PASS", "")
    monkeypatch.setattr(notify, "_ALERT_STATE_FILE", str(tmp_path / ".alert_state"))
    assert notify.send_cookie_alert() is False


def test_sends_when_configured(smtp):
    assert notify.send_cookie_alert() is True
    assert len(smtp) == 1


def test_debounced_within_cooldown(smtp):
    assert notify.send_cookie_alert() is True
    assert notify.send_cookie_alert() is False  # suppressed by cooldown
    assert len(smtp) == 1


def test_force_bypasses_cooldown(smtp):
    assert notify.send_cookie_alert() is True
    assert notify.send_cookie_alert(force=True) is True
    assert len(smtp) == 2


def test_resends_after_cooldown(smtp, monkeypatch):
    assert notify.send_cookie_alert() is True
    # pretend the last send was 25h ago
    monkeypatch.setattr(notify, "_last_sent", lambda kind: time.time() - 25 * 3600)
    assert notify.send_cookie_alert() is True
    assert len(smtp) == 2


def test_message_is_well_formed(smtp):
    msg = notify._cookie_alert_message()
    assert msg["To"] == "me@gmail.com"
    assert "cookies" in msg["Subject"].lower()
    # multipart: plain + html alternatives
    body = msg.get_body(preferencelist=("html",)).get_content()
    assert "cookies.txt" in body
    assert config.BASE_URL in body
    plain = msg.get_body(preferencelist=("plain",)).get_content()
    assert "Upload it here" in plain


def test_send_failure_returns_false(smtp, monkeypatch):
    def boom(msg):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(notify, "_send", boom)
    assert notify.send_cookie_alert() is False


def test_state_not_recorded_on_failure(smtp, monkeypatch):
    monkeypatch.setattr(notify, "_send", lambda msg: (_ for _ in ()).throw(RuntimeError("x")))
    notify.send_cookie_alert()
    # cooldown not started, so a later good send still works
    monkeypatch.setattr(notify, "_send", lambda msg: smtp.append(msg))
    assert notify.send_cookie_alert() is True
