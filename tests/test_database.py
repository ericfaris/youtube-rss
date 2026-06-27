"""Roundtrip tests for database helpers (channel + episode lifecycle)."""
from app import database as db

CID = "UCabc12345678901234567890"
CID2 = "UCdef12345678901234567890"


def _setup_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "t.db"))
    db.init_db()


def _ep(i, cid=CID):
    return {
        "id": f"v{i:03d}", "channel_id": cid, "channel_name": "C",
        "title": f"t{i}", "description": "",
        "published": f"2026-06-{(i % 28) + 1:02d}T00:00:00+00:00",
        "duration": 1, "filename": f"v{i:03d}.mp3", "filesize": 1, "thumbnail": None,
    }


def test_add_channel_is_idempotent(tmp_path, monkeypatch):
    _setup_tmp(tmp_path, monkeypatch)
    url = "https://www.youtube.com/@A"
    db.add_channel(url)
    db.add_channel(url)  # INSERT OR IGNORE
    assert [r["url"] for r in db.get_channels()] == [url]


def test_remove_channel(tmp_path, monkeypatch):
    _setup_tmp(tmp_path, monkeypatch)
    url = "https://www.youtube.com/@A"
    db.add_channel(url)
    db.remove_channel(url)
    assert db.get_channels() == []


def test_unsubscribed_channel_roundtrip(tmp_path, monkeypatch):
    _setup_tmp(tmp_path, monkeypatch)
    db.upsert_unsubscribed_channel(CID, "Name")
    db.upsert_unsubscribed_channel(CID, "Renamed")  # REPLACE updates name
    rows = db.get_unsubscribed_channels()
    assert len(rows) == 1 and rows[0]["channel_name"] == "Renamed"
    db.remove_unsubscribed_channel(CID)
    assert db.get_unsubscribed_channels() == []


def test_get_all_channel_ids_is_distinct(tmp_path, monkeypatch):
    _setup_tmp(tmp_path, monkeypatch)
    # episode id (the video id) is globally unique, so use distinct ids per channel
    db.upsert_episode(_ep(0, CID))
    db.upsert_episode(_ep(1, CID))
    db.upsert_episode(_ep(9, CID2))
    assert set(db.get_all_channel_ids()) == {CID, CID2}


def test_delete_episodes_for_channel_returns_and_removes(tmp_path, monkeypatch):
    _setup_tmp(tmp_path, monkeypatch)
    db.upsert_episode(_ep(0, CID))
    db.upsert_episode(_ep(1, CID))
    db.upsert_episode(_ep(9, CID2))
    removed = db.delete_episodes_for_channel(CID)
    assert {r["id"] for r in removed} == {"v000", "v001"}
    assert db.get_episodes(CID) == []
    assert len(db.get_episodes(CID2)) == 1  # other channel untouched


def test_upsert_episode_is_idempotent_on_id(tmp_path, monkeypatch):
    _setup_tmp(tmp_path, monkeypatch)
    db.upsert_episode(_ep(0))
    dup = _ep(0)
    dup["title"] = "updated"
    db.upsert_episode(dup)  # same id -> replace, not duplicate
    eps = db.get_episodes(CID)
    assert len(eps) == 1 and eps[0]["title"] == "updated"
