"""Tests for the episode cap (prune) and members-only skip behavior."""
from app import database as db, downloader

CID = "UCabc12345678901234567890"  # valid channel_id per the regex


def _setup_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(downloader, "AUDIO_DIR", str(tmp_path / "audio"))
    monkeypatch.setattr(downloader, "THUMBNAIL_DIR", str(tmp_path / "thumb"))
    db.init_db()


def _ep(i, cid=CID):
    return {
        "id": f"v{i:03d}", "channel_id": cid, "channel_name": "C",
        "title": f"t{i}", "description": "",
        "published": f"2026-06-{(i % 28) + 1:02d}T00:00:00+00:00",
        "duration": 1, "filename": f"v{i:03d}.mp3", "filesize": 1, "thumbnail": None,
    }


def test_prune_enforces_cap(tmp_path, monkeypatch):
    _setup_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(downloader, "MAX_EPISODES_PER_CHANNEL", 20)
    for i in range(30):
        db.upsert_episode(_ep(i))
    assert len(db.get_episodes(CID)) == 30
    downloader._prune_channel(CID)
    assert len(db.get_episodes(CID)) == 20


def test_prune_keeps_newest(tmp_path, monkeypatch):
    _setup_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(downloader, "MAX_EPISODES_PER_CHANNEL", 5)
    for i in range(10):
        db.upsert_episode(_ep(i))
    downloader._prune_channel(CID)
    remaining = db.get_episodes(CID)
    assert len(remaining) == 5
    # get_episodes returns newest-first; kept set should be the 5 most recent
    pubs = [r["published"] for r in remaining]
    assert pubs == sorted(pubs, reverse=True)


def test_get_channel_id_for_url(tmp_path, monkeypatch):
    _setup_tmp(tmp_path, monkeypatch)
    url = "https://www.youtube.com/@SomeChannel"
    db.add_channel(url)
    # No channel_id resolved yet -> None
    assert db.get_channel_id_for_url(url) is None
    db.update_channel_meta(url, CID, "C")
    assert db.get_channel_id_for_url(CID + "x") is None  # unknown url
    assert db.get_channel_id_for_url(url) == CID


def test_poll_prunes_even_when_fetch_fails(tmp_path, monkeypatch):
    """Regression: an over-cap channel must be pruned even if the fetch raises
    (e.g. expired cookies), instead of returning early and never capping."""
    _setup_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(downloader, "MAX_EPISODES_PER_CHANNEL", 20)

    url = "https://www.youtube.com/@SomeChannel"
    db.add_channel(url)
    db.update_channel_meta(url, CID, "C")
    for i in range(34):
        db.upsert_episode(_ep(i))
    assert len(db.get_episodes(CID)) == 34

    # Fetch blows up the way an auth/cookie failure would.
    def _boom(*_a, **_k):
        raise RuntimeError("Sign in to confirm you're not a bot")

    monkeypatch.setattr(downloader, "_fetch_channel_entries", _boom)
    monkeypatch.setattr(downloader, "valid_cookie_file", lambda _p: True)
    monkeypatch.setattr(downloader.notify, "send_cookie_alert", lambda *a, **k: None)

    downloader.poll_channel(url)

    # Even though the fetch failed and poll returned early, the cap was enforced.
    assert len(db.get_episodes(CID)) == 20


def _stub_poll_io(monkeypatch, entries):
    """Wire poll_channel's external I/O to in-memory stubs and return a list
    that records the ids actually handed to _download_entry."""
    downloaded_ids = []

    def _fake_download(entry, cid, cname):
        downloaded_ids.append(entry["id"])
        return _ep(int(entry["id"][1:]), cid)

    monkeypatch.setattr(downloader, "_fetch_channel_entries",
                        lambda *a, **k: (entries, CID, "C"))
    monkeypatch.setattr(downloader, "_download_entry", _fake_download)
    monkeypatch.setattr(downloader, "valid_cookie_file", lambda _p: True)
    monkeypatch.setattr(downloader.time, "sleep", lambda _s: None)
    return downloaded_ids


def test_poll_loop_caps_downloads(tmp_path, monkeypatch):
    """Regression for 'episode numbers above twenty': a successful poll must
    stop downloading at the cap and finish with exactly MAX episodes."""
    _setup_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(downloader, "MAX_EPISODES_PER_CHANNEL", 20)
    url = "https://www.youtube.com/@SomeChannel"
    db.add_channel(url)

    entries = [{"id": f"v{i:03d}", "availability": None} for i in range(34)]
    downloaded_ids = _stub_poll_io(monkeypatch, entries)

    downloader.poll_channel(url)

    # The loop itself stopped at the cap (didn't download all 34) ...
    assert len(downloaded_ids) == 20
    # ... and the channel ends at exactly the cap.
    assert len(db.get_episodes(CID)) == 20


def test_poll_skips_members_only_and_records_skip(tmp_path, monkeypatch):
    """Members-only entries are not downloaded and are remembered for fast-skip."""
    _setup_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(downloader, "MAX_EPISODES_PER_CHANNEL", 20)
    url = "https://www.youtube.com/@SomeChannel"
    db.add_channel(url)

    entries = [
        {"id": "v000", "availability": None},
        {"id": "v001", "availability": "subscriber_only"},
        {"id": "v002", "availability": None},
    ]
    downloaded_ids = _stub_poll_io(monkeypatch, entries)

    downloader.poll_channel(url)

    assert downloaded_ids == ["v000", "v002"]  # member-only one skipped
    assert "v001" in db.get_skip_video_ids(CID)
    assert len(db.get_episodes(CID)) == 2


def test_member_only_detection():
    assert downloader._looks_like_member_only("ERROR: [youtube] x: Join this channel to get access")
    assert downloader._looks_like_member_only("This video is members-only content")
    assert not downloader._looks_like_member_only("Video unavailable")
    assert not downloader._looks_like_member_only("")


def test_skip_video_roundtrip(tmp_path, monkeypatch):
    _setup_tmp(tmp_path, monkeypatch)
    db.add_skip_video("vid1", CID, "members_only")
    db.add_skip_video("vid1", CID, "members_only")  # idempotent
    db.add_skip_video("vid2", CID, "members_only")
    assert db.get_skip_video_ids(CID) == {"vid1", "vid2"}
    db.delete_skip_videos_for_channel(CID)
    assert db.get_skip_video_ids(CID) == set()
