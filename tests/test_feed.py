"""Tests for RSS feed generation, including the per-feed episode cap."""
from xml.etree import ElementTree as ET

from app import database as db, feed

CID = "UCabc12345678901234567890"


def _setup_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(feed, "THUMBNAIL_DIR", str(tmp_path / "thumb"))
    monkeypatch.setattr(feed, "BASE_URL", "https://example.test")
    db.init_db()


def _ep(i, cid=CID):
    return {
        "id": f"v{i:03d}", "channel_id": cid, "channel_name": "Chan",
        "title": f"Episode {i}", "description": "",
        "published": f"2026-06-{(i % 28) + 1:02d}T00:00:00+00:00",
        "duration": 1, "filename": f"v{i:03d}.mp3", "filesize": 123,
        "thumbnail": None,
    }


def _items(xml_bytes):
    root = ET.fromstring(xml_bytes)
    return root.findall("./channel/item")


def test_empty_feed_returns_empty_bytes(tmp_path, monkeypatch):
    _setup_tmp(tmp_path, monkeypatch)
    assert feed.build_feed(CID) == b""


def test_feed_caps_at_max(tmp_path, monkeypatch):
    """Even if the DB has drifted over the cap, the feed must not expose more
    than MAX_EPISODES_PER_CHANNEL items."""
    _setup_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(feed, "MAX_EPISODES_PER_CHANNEL", 20)
    for i in range(34):
        db.upsert_episode(_ep(i))
    assert len(db.get_episodes(CID)) == 34
    assert len(_items(feed.build_feed(CID))) == 20


def test_feed_includes_all_episodes_under_cap(tmp_path, monkeypatch):
    _setup_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(feed, "MAX_EPISODES_PER_CHANNEL", 20)
    for i in range(5):
        db.upsert_episode(_ep(i))
    items = _items(feed.build_feed(CID))
    titles = {it.find("title").text for it in items}
    assert titles == {f"Episode {i}" for i in range(5)}


def test_feed_includes_enclosure_and_metadata(tmp_path, monkeypatch):
    _setup_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(feed, "MAX_EPISODES_PER_CHANNEL", 20)
    db.upsert_episode(_ep(1))
    xml = feed.build_feed(CID)
    item = _items(xml)[0]
    enc = item.find("enclosure")
    assert enc.get("type") == "audio/mpeg"
    assert enc.get("url") == "https://example.test/audio/%s/v001.mp3" % CID
    assert enc.get("length") == "123"


def test_feed_survives_bad_published_date(tmp_path, monkeypatch):
    _setup_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(feed, "MAX_EPISODES_PER_CHANNEL", 20)
    ep = _ep(1)
    ep["published"] = "not-a-date"
    db.upsert_episode(ep)
    # Should not raise; falls back to "now".
    assert len(_items(feed.build_feed(CID))) == 1
