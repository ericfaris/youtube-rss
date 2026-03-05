# youtube-rss

A self-hosted server that turns YouTube channels into podcast RSS feeds. Subscribe to any YouTube channel in your podcast app and listen to new videos as audio episodes — automatically downloaded on a schedule.

## Features

- **Podcast RSS feeds** — standard RSS with iTunes extensions, works with any podcast app
- **Automatic polling** — checks subscribed channels on a configurable schedule
- **Channel management UI** — add/remove channels, copy feed URLs, trigger manual polls
- **Shareable links** — add a channel or download an episode by clicking a URL (great for mobile)
- **One-off downloads** — download any specific YouTube video without subscribing to the channel
- **Cover art** — channel and per-episode thumbnails included in the feed
- **Member content filtering** — skips subscriber-only videos during automatic polls
- **Persistent storage** — SQLite database + audio files survive container restarts

---

## Quick Start

**1. Clone the repo**
```bash
git clone https://github.com/yourname/youtube-rss
cd youtube-rss
```

**2. Edit `docker-compose.yml`** — set your base URL:
```yaml
environment:
  - BASE_URL=http://localhost:8000
```

**3. Run it**
```bash
docker compose up --build
```

The app starts at `http://localhost:8000`. On first launch it immediately polls your configured channels.

---

## Configuration

All configuration is via environment variables, set in `docker-compose.yml` (or `.env` for local runs).

| Variable | Default | Description |
|---|---|---|
| `BASE_URL` | `http://localhost:8000` | Public URL of your app — used in feed enclosure URLs |
| `DATA_DIR` | `/data` | Where audio, thumbnails, and the database are stored |
| `MAX_EPISODES_PER_CHANNEL` | `20` | How many episodes to keep per channel |
| `POLL_INTERVAL_HOURS` | `6` | How often to check subscribed channels for new videos |

### Notes
- Change `BASE_URL` to your public domain when deploying — podcast apps need this to reach the audio files.

---

## Management UI

Visit `http://yourapp/` to manage everything through a simple web interface.

### Subscribed Channels
Channels being polled automatically on your schedule.

| Action | Description |
|---|---|
| **Copy** | Copies the RSS feed URL to your clipboard |
| **Poll Now** | Triggers an immediate download check in the background |
| **Remove** | Unsubscribes and deletes all downloaded files for that channel |

### One-off Downloads
Episodes downloaded individually without subscribing to the channel. These have a feed URL you can subscribe to in your podcast app, but the channel won't be polled automatically.

| Action | Description |
|---|---|
| **Copy** | Copies the RSS feed URL to your clipboard |
| **Subscribe** | Promotes the channel to a full subscription and starts polling it |

### Add Channel
Paste any YouTube channel URL or handle and click **Add Channel**. The channel is immediately polled in the background.

Supported URL formats:
```
https://www.youtube.com/@ChannelHandle
https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxxxx
```

### Download Episode
Paste any YouTube video URL and click **Download**. The episode is downloaded immediately regardless of length, date, or file size.

- **Subscribe to channel** unchecked *(default)* — downloads the episode only, channel appears under "One-off Downloads"
- **Subscribe to channel** checked — downloads the episode and subscribes to the channel for automatic future updates

Supported URL formats:
```
https://youtu.be/xxxxxxxxxxx
https://www.youtube.com/watch?v=xxxxxxxxxxx
https://youtu.be/xxxxxxxxxxx?si=xxxxxxxxxxxxxxxxxx
```

---

## Shareable Links

You can add channels or download episodes by sharing a URL — useful for adding content from your phone without opening a laptop.

### Add a channel
```
http://yourapp/add?channel=https://www.youtube.com/@ChannelHandle
```
Clicking this adds the channel and redirects to the management UI.

### Download a specific episode
```
http://yourapp/download?url=https://youtu.be/xxxxxxxxxxx
```
Clicking this downloads the episode (no subscription) and redirects to the management UI.

### Download and subscribe
```
http://yourapp/download?url=https://youtu.be/xxxxxxxxxxx&subscribe=true
```

---

## RSS Feeds

Each channel has its own RSS feed:
```
http://yourapp/feed/<channel_id>.xml
```

Channel IDs are shown in the management UI. You can also list all available feeds:
```
GET http://yourapp/feeds
```

Subscribe to these URLs in any podcast app (Pocket Casts, Overcast, Apple Podcasts, etc.).

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Management UI |
| `GET` | `/feed/<channel_id>.xml` | RSS feed for a channel |
| `GET` | `/feeds` | JSON list of all feed URLs |
| `GET` | `/add?channel=<url>` | Add a channel via shareable link |
| `GET` | `/download?url=<url>` | Download an episode via shareable link |
| `GET` | `/download?url=<url>&subscribe=true` | Download + subscribe via shareable link |
| `POST` | `/channels/add` | Add a channel (form) |
| `POST` | `/channels/remove` | Remove a channel (form) |
| `POST` | `/channels/poll` | Trigger immediate poll (form) |
| `POST` | `/channels/subscribe` | Promote one-off channel to subscription (form) |
| `POST` | `/episodes/download` | Download a specific episode (form) |
| `GET` | `/health` | Health check — returns `{"status": "ok"}` |

---

## How It Works

1. **Polling** — on startup and every `POLL_INTERVAL_HOURS`, the app fetches the `/videos` tab of each subscribed channel using yt-dlp
2. **Filtering** — member-only, subscriber-only, and premium videos are skipped during automatic polls
3. **Downloading** — new videos are downloaded as MP3 (128kbps) to `DATA_DIR/audio/<channel_id>/`
4. **Thumbnails** — channel cover art and per-episode thumbnails are saved to `DATA_DIR/thumbnails/<channel_id>/`
5. **Pruning** — once a channel exceeds `MAX_EPISODES_PER_CHANNEL`, the oldest episodes are deleted
6. **Feed generation** — RSS feeds are built dynamically from the SQLite database on each request
7. **Deduplication** — already-downloaded files are detected by file existence check and skipped

---

## Data Layout

```
./data/
├── episodes.db              # SQLite database
├── audio/
│   └── <channel_id>/
│       ├── <video_id>.mp3
│       └── ...
└── thumbnails/
    └── <channel_id>/
        ├── channel.jpg      # Channel cover art
        ├── <video_id>.jpg   # Per-episode thumbnails
        └── ...
```

---

## Deploying

This app is designed to run on [Railway](https://railway.app) but works on any Docker host.

**Railway**
- Connect your repo, Railway auto-detects the `Dockerfile`
- Set environment variables in the Railway dashboard
- Add a volume mounted at `/data`
- Set `BASE_URL` to your Railway public URL

**Other hosts**
- Any host that runs Docker Compose works
- Make sure `./data` is on persistent storage
- Set `BASE_URL` to your public domain so podcast apps can reach audio files
