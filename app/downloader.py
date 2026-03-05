import logging
import os
import time
import urllib.request
from datetime import datetime, timezone

import yt_dlp

from app import database as db
from app.config import AUDIO_DIR, MAX_EPISODES_PER_CHANNEL, THUMBNAIL_DIR

logger = logging.getLogger(__name__)


def _download_thumbnail(url: str, dest: str) -> bool:
    if os.path.exists(dest):
        return True
    try:
        urllib.request.urlretrieve(url, dest)
        return True
    except Exception as exc:
        logger.warning("Failed to download thumbnail %s: %s", url, exc)
        return False


def _thumbnail_dir_for(channel_id: str) -> str:
    path = os.path.join(THUMBNAIL_DIR, channel_id)
    os.makedirs(path, exist_ok=True)
    return path


def _audio_dir_for(channel_id: str) -> str:
    path = os.path.join(AUDIO_DIR, channel_id)
    os.makedirs(path, exist_ok=True)
    return path


def _ydl_opts(channel_id: str) -> dict:
    return {
        "format": "bestaudio/best",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "128",
        }],
        "outtmpl": os.path.join(_audio_dir_for(channel_id), "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "sleep_interval": 2,
        "max_sleep_interval": 5,
    }


def _fetch_channel_entries(channel_url: str, max_entries: int) -> list[dict]:
    """Return metadata for the most recent max_entries videos without downloading."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "playlistend": max_entries,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)
    entries = info.get("entries") or []
    channel_id = info.get("channel_id") or info.get("id", "unknown")
    channel_name = info.get("channel") or info.get("uploader") or info.get("title", "Unknown")

    # download channel cover art
    channel_thumb_url = info.get("thumbnail")
    if channel_thumb_url:
        dest = os.path.join(_thumbnail_dir_for(channel_id), "channel.jpg")
        _download_thumbnail(channel_thumb_url, dest)

    return entries, channel_id, channel_name


def _download_entry(entry: dict, channel_id: str, channel_name: str) -> dict | None:
    video_id = entry.get("id")
    if not video_id:
        return None

    audio_dir = _audio_dir_for(channel_id)
    expected_file = os.path.join(audio_dir, f"{video_id}.mp3")

    if os.path.exists(expected_file):
        logger.debug("Already downloaded: %s", video_id)
        return None

    url = entry.get("url") or f"https://www.youtube.com/watch?v={video_id}"
    logger.info("Downloading %s: %s", video_id, entry.get("title", ""))

    try:
        with yt_dlp.YoutubeDL(_ydl_opts(channel_id)) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as exc:
        logger.warning("Failed to download %s: %s", video_id, exc)
        return None

    if not os.path.exists(expected_file):
        logger.warning("Expected file not found after download: %s", expected_file)
        return None

    published = info.get("upload_date", "")
    if published:
        published = datetime.strptime(published, "%Y%m%d").replace(tzinfo=timezone.utc).isoformat()
    else:
        published = datetime.now(timezone.utc).isoformat()

    # download episode thumbnail
    thumb_filename = None
    thumb_url = info.get("thumbnail")
    if thumb_url:
        thumb_dest = os.path.join(_thumbnail_dir_for(channel_id), f"{video_id}.jpg")
        if _download_thumbnail(thumb_url, thumb_dest):
            thumb_filename = os.path.basename(thumb_dest)

    return {
        "id": video_id,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "title": info.get("title", video_id),
        "description": info.get("description", ""),
        "published": published,
        "duration": info.get("duration"),
        "filename": os.path.basename(expected_file),
        "filesize": os.path.getsize(expected_file),
        "thumbnail": thumb_filename,
    }


def _prune_channel(channel_id: str):
    episodes = db.get_episodes(channel_id)
    to_delete = episodes[MAX_EPISODES_PER_CHANNEL:]
    for ep in to_delete:
        filepath = os.path.join(_audio_dir_for(channel_id), ep["filename"])
        if os.path.exists(filepath):
            os.remove(filepath)
            logger.info("Pruned %s", filepath)
        db.delete_episode(ep["id"])


def poll_channel(channel_url: str):
    original_url = channel_url.rstrip("/")
    channel_url = original_url + "/videos"
    logger.info("Polling channel: %s", channel_url)
    try:
        entries, channel_id, channel_name = _fetch_channel_entries(channel_url, MAX_EPISODES_PER_CHANNEL * 3)
    except Exception as exc:
        logger.error("Failed to fetch channel %s: %s", channel_url, exc)
        return
    db.update_channel_meta(original_url, channel_id, channel_name)

    downloaded = 0
    for entry in entries:
        if downloaded >= MAX_EPISODES_PER_CHANNEL:
            break
        if entry.get("availability") in ("subscriber_only", "needs_auth", "premium_only"):
            logger.debug("Skipping member-only video: %s", entry.get("id"))
            continue
        result = _download_entry(entry, channel_id, channel_name)
        if result:
            db.upsert_episode(result)
            downloaded += 1
        time.sleep(1)

    _prune_channel(channel_id)
    logger.info("Done polling %s (%s)", channel_name, channel_id)


def poll_all():
    channels = db.get_channels()
    for ch in channels:
        poll_channel(ch["url"])


def download_single(video_url: str, subscribe: bool = False):
    """Download a specific video URL, bypassing all availability filters."""
    logger.info("Downloading single video: %s", video_url)
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(video_url, download=False)
    except Exception as exc:
        logger.error("Failed to fetch video info %s: %s", video_url, exc)
        return

    video_id = info.get("id")
    if not video_id:
        logger.error("Could not get video ID from %s", video_url)
        return

    channel_id = info.get("channel_id") or info.get("uploader_id", "unknown")
    channel_name = info.get("channel") or info.get("uploader", "Unknown")

    if subscribe:
        channels = db.get_channels()
        if not any(ch["channel_id"] == channel_id for ch in channels):
            channel_page_url = f"https://www.youtube.com/channel/{channel_id}"
            db.add_channel(channel_page_url)
            db.update_channel_meta(channel_page_url, channel_id, channel_name)
            logger.info("Subscribed to channel: %s", channel_name)
    else:
        channels = db.get_channels()
        if not any(ch["channel_id"] == channel_id for ch in channels):
            db.upsert_unsubscribed_channel(channel_id, channel_name)

    result = _download_entry({"id": video_id}, channel_id, channel_name)
    if result:
        db.upsert_episode(result)
        logger.info("Downloaded single video: %s", result["title"])


def remove_channel_data(channel_id: str):
    """Delete all downloaded files for a channel."""
    import shutil
    audio_dir = os.path.join(AUDIO_DIR, channel_id)
    thumb_dir = os.path.join(THUMBNAIL_DIR, channel_id)
    for path in (audio_dir, thumb_dir):
        if os.path.exists(path):
            shutil.rmtree(path)
            logger.info("Removed directory: %s", path)
