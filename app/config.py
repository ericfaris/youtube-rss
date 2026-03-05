import os

DATA_DIR = os.environ.get("DATA_DIR", "/data")
AUDIO_DIR = os.path.join(DATA_DIR, "audio")
THUMBNAIL_DIR = os.path.join(DATA_DIR, "thumbnails")
DB_PATH = os.path.join(DATA_DIR, "episodes.db")

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
AUTH_USER = os.environ.get("AUTH_USER", "")
AUTH_PASS = os.environ.get("AUTH_PASS", "")
MAX_EPISODES_PER_CHANNEL = int(os.environ.get("MAX_EPISODES_PER_CHANNEL", "20"))
POLL_INTERVAL_HOURS = int(os.environ.get("POLL_INTERVAL_HOURS", "6"))

