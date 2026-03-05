from datetime import datetime, timezone
from feedgen.feed import FeedGenerator

from app import database as db
from app.config import BASE_URL


def build_feed(channel_id: str) -> bytes:
    episodes = db.get_episodes(channel_id)
    if not episodes:
        return b""

    channel_name = episodes[0]["channel_name"]

    fg = FeedGenerator()
    fg.load_extension("podcast")

    feed_url = f"{BASE_URL}/feed/{channel_id}.xml"
    fg.id(feed_url)
    fg.title(channel_name)
    fg.link(href=feed_url, rel="self")
    fg.language("en")
    fg.description(f"Audio podcast feed for {channel_name}")
    fg.podcast.itunes_author(channel_name)
    fg.podcast.itunes_explicit("no")
    fg.podcast.itunes_image(f"{BASE_URL}/thumbnails/{channel_id}/channel.jpg")

    for ep in episodes:
        fe = fg.add_entry()
        fe.id(ep["id"])
        fe.title(ep["title"])
        fe.description(ep["description"] or ep["title"])

        try:
            pub = datetime.fromisoformat(ep["published"])
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pub = datetime.now(timezone.utc)
        fe.published(pub)

        audio_url = f"{BASE_URL}/audio/{channel_id}/{ep['filename']}"
        fe.enclosure(audio_url, str(ep["filesize"] or 0), "audio/mpeg")

        if ep["duration"]:
            fe.podcast.itunes_duration(ep["duration"])

        if ep["thumbnail"]:
            fe.podcast.itunes_image(f"{BASE_URL}/thumbnails/{channel_id}/{ep['thumbnail']}")

    return fg.rss_str(pretty=True)
