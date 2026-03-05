import sqlite3
from contextlib import contextmanager
from app.config import DB_PATH


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                url          TEXT PRIMARY KEY,
                channel_id   TEXT,
                channel_name TEXT,
                added_at     TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS unsubscribed_channels (
                channel_id   TEXT PRIMARY KEY,
                channel_name TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                id          TEXT PRIMARY KEY,
                channel_id  TEXT NOT NULL,
                channel_name TEXT NOT NULL,
                title       TEXT NOT NULL,
                description TEXT,
                published   TEXT NOT NULL,
                duration    INTEGER,
                filename    TEXT NOT NULL,
                filesize    INTEGER,
                thumbnail   TEXT,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # migrate existing DBs
        cols = {r[1] for r in conn.execute("PRAGMA table_info(episodes)").fetchall()}
        if "thumbnail" not in cols:
            conn.execute("ALTER TABLE episodes ADD COLUMN thumbnail TEXT")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_episode(ep: dict):
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO episodes
                (id, channel_id, channel_name, title, description, published, duration, filename, filesize, thumbnail)
            VALUES
                (:id, :channel_id, :channel_name, :title, :description, :published, :duration, :filename, :filesize, :thumbnail)
        """, ep)


def get_episodes(channel_id: str) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("""
            SELECT * FROM episodes
            WHERE channel_id = ?
            ORDER BY published DESC
        """, (channel_id,)).fetchall()


def get_all_channel_ids() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT DISTINCT channel_id FROM episodes").fetchall()
        return [r["channel_id"] for r in rows]


def delete_episode(episode_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM episodes WHERE id = ?", (episode_id,))


def add_channel(url: str):
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO channels (url) VALUES (?)", (url,))


def remove_channel(url: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM channels WHERE url = ?", (url,))


def get_channels() -> list:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM channels ORDER BY added_at").fetchall()


def update_channel_meta(url: str, channel_id: str, channel_name: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE channels SET channel_id = ?, channel_name = ? WHERE url = ?",
            (channel_id, channel_name, url)
        )


def get_unsubscribed_channels() -> list:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM unsubscribed_channels ORDER BY channel_name").fetchall()


def remove_unsubscribed_channel(channel_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM unsubscribed_channels WHERE channel_id = ?", (channel_id,))


def upsert_unsubscribed_channel(channel_id: str, channel_name: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO unsubscribed_channels (channel_id, channel_name) VALUES (?, ?)",
            (channel_id, channel_name)
        )


def delete_episodes_for_channel(channel_id: str) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM episodes WHERE channel_id = ?", (channel_id,)
        ).fetchall()
        conn.execute("DELETE FROM episodes WHERE channel_id = ?", (channel_id,))
    return rows
