import os

DATA_DIR = os.environ.get("DATA_DIR", "/data")
AUDIO_DIR = os.path.join(DATA_DIR, "audio")
THUMBNAIL_DIR = os.path.join(DATA_DIR, "thumbnails")
DB_PATH = os.path.join(DATA_DIR, "episodes.db")

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
AUTH_USER = os.environ.get("AUTH_USER", "")
AUTH_PASS = os.environ.get("AUTH_PASS", "")

# Multi-user: AUTH_USERS=alice:pass1,bob:pass2 (takes precedence over AUTH_USER/AUTH_PASS)
_raw_users = os.environ.get("AUTH_USERS", "")
if _raw_users:
    AUTH_CREDENTIALS: list[tuple[str, str]] = [
        (e.strip().split(":", 1)[0], e.strip().split(":", 1)[1])
        for e in _raw_users.split(",")
        if ":" in e.strip()
    ]
elif AUTH_USER and AUTH_PASS:
    AUTH_CREDENTIALS = [(AUTH_USER, AUTH_PASS)]
else:
    AUTH_CREDENTIALS = []
MAX_EPISODES_PER_CHANNEL = int(os.environ.get("MAX_EPISODES_PER_CHANNEL", "20"))
POLL_INTERVAL_HOURS = int(os.environ.get("POLL_INTERVAL_HOURS", "6"))
COOKIES_FILE = os.environ.get("COOKIES_FILE", "/data/cookies.txt")

