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
