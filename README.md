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
- **Basic auth** — management UI is password protected; feeds and audio are publicly accessible
- **Security hardening** — CSRF protection on all POST endpoints, Content-Security-Policy header, rate limiting on failed auth attempts, path traversal prevention

---

## Quick Start

The image is published to Docker Hub — no need to build locally.

**1. Create a project folder and add a `docker-compose.yml`:**

```yaml
services:
  app:
    image: ericfaris/youtube-rss:latest
    ports:
      - "127.0.0.1:8000:8000"
    volumes:
      - ./data:/data
    environment:
      # External URL used in RSS feed links — must be reachable by your podcast app
      - BASE_URL=http://localhost:8000

      # Web UI login credentials (set in .env file — see below)
      - AUTH_USER=${AUTH_USER}
      - AUTH_PASS=${AUTH_PASS}

      # How many episodes to keep per channel (older ones are pruned)
      - MAX_EPISODES_PER_CHANNEL=20

      # How often to check channels for new videos (in hours)
      - POLL_INTERVAL_HOURS=2

      # Internal data directory — leave this as-is
      - DATA_DIR=/data

      # Uncomment after uploading cookies via the UI
      # - COOKIES_FILE=/data/cookies.txt
```

**2. Create a `.env` file** in the same folder (never commit this):

```
AUTH_USER=youruser
AUTH_PASS=yourpassword
```

**3. Run it:**

```bash
docker compose up -d
```

The app starts at `http://localhost:8000`.

---

## Configuration

All configuration is via environment variables in `docker-compose.yml`. Credentials are kept in `.env` so they are never committed to git.

| Variable | Default | Description |
|---|---|---|
| `BASE_URL` | `http://localhost:8000` | Public URL of your app — used in feed and audio URLs |
| `AUTH_USER` | *(none)* | Management UI username |
| `AUTH_PASS` | *(none)* | Management UI password |
| `DATA_DIR` | `/data` | Where audio, thumbnails, and the database are stored |
| `MAX_EPISODES_PER_CHANNEL` | `20` | How many episodes to keep per channel |
| `POLL_INTERVAL_HOURS` | `2` | How often to check subscribed channels for new videos |
| `COOKIES_FILE` | *(none)* | Path to YouTube cookies file (upload via UI, then uncomment) |

### Important notes
- `BASE_URL` must be reachable by your podcast app. If using Pocket Casts or another server-side app, this must be a public URL. See [CLOUDFLARE_TUNNEL.md](CLOUDFLARE_TUNNEL.md) for how to expose the app publicly using Cloudflare Tunnel.
- The port is bound to `127.0.0.1` so the app is only reachable from localhost — external traffic must go through a reverse proxy or tunnel (e.g. Cloudflare Tunnel or Tailscale).
- The management UI (`/`) requires Basic Auth. Feed and audio endpoints (`/feed/`, `/audio/`) are public so podcast apps can access them without credentials.
- YouTube cookies expire every few weeks. When downloads start failing, re-upload cookies via the management UI and uncomment `COOKIES_FILE`.

---

## Management UI

Visit `https://yourapp/` and log in with your `AUTH_USER` / `AUTH_PASS`.

### Subscribed Channels
Channels being polled automatically on your schedule.

| Action | Description |
|---|---|
| **Copy** | Copies the RSS feed URL to your clipboard |
| **Poll Now** | Triggers an immediate download check in the background |
| **Remove** | Unsubscribes and deletes all downloaded files for that channel |

### One-off Downloads
Episodes downloaded individually without subscribing to the channel. These have a feed URL you can use in your podcast app, but the channel won't be polled automatically.

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
Paste any YouTube video URL and click **Download**. The episode is downloaded immediately.

- **Subscribe to channel** unchecked *(default)* — downloads the episode only
- **Subscribe to channel** checked — downloads the episode and subscribes the channel

Supported URL formats:
```
https://youtu.be/xxxxxxxxxxx
https://www.youtube.com/watch?v=xxxxxxxxxxx
```

---

## Shareable Links

Add channels or download episodes via URL — useful from your phone without opening a laptop.

### Add a channel
```
https://yourapp/add?channel=https://www.youtube.com/@ChannelHandle
```

### Download a specific episode
```
https://yourapp/download?url=https://youtu.be/xxxxxxxxxxx
```

### Download and subscribe
```
https://yourapp/download?url=https://youtu.be/xxxxxxxxxxx&subscribe=true
```

---

## RSS Feeds

Each channel has its own RSS feed at:
```
https://yourapp/feed/<channel_id>.xml
```

Feed and audio URLs are **publicly accessible** — no credentials required. This is necessary for podcast apps to fetch and stream content. The management UI remains password protected.

Subscribe to feed URLs in any podcast app (Pocket Casts, AntennaPod, Overcast, Apple Podcasts, etc.).

> **Note:** Some podcast apps (including Pocket Casts) fetch feeds through their own servers rather than directly from your device. In this case `BASE_URL` must be a publicly reachable URL. See [CLOUDFLARE_TUNNEL.md](CLOUDFLARE_TUNNEL.md).

---

## API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/` | Required | Management UI |
| `GET` | `/feed/<channel_id>.xml` | None | RSS feed for a channel |
| `GET` | `/audio/<channel_id>/<file>.mp3` | None | Audio file stream |
| `GET` | `/thumbnails/<channel_id>/<file>.jpg` | None | Thumbnail image |
| `GET` | `/health` | None | Health check |
| `GET` | `/add?channel=<url>` | Required | Add a channel via shareable link |
| `GET` | `/download?url=<url>` | Required | Download an episode via shareable link |
| `POST` | `/channels/add` | Required | Add a channel (form) |
| `POST` | `/channels/remove` | Required | Remove a channel (form) |
| `POST` | `/channels/poll` | Required | Trigger immediate poll (form) |
| `POST` | `/channels/subscribe` | Required | Promote one-off to subscription (form) |
| `POST` | `/episodes/download` | Required | Download a specific episode (form) |
| `POST` | `/auth/cookies` | Required | Upload YouTube cookies file (max 5 MB) |

---

## How It Works

1. **Polling** — on startup and every `POLL_INTERVAL_HOURS`, yt-dlp fetches the `/videos` tab of each subscribed channel
2. **Filtering** — member-only, subscriber-only, and premium videos are skipped during automatic polls
3. **Downloading** — new videos are downloaded as MP3 (128kbps) to `DATA_DIR/audio/<channel_id>/`
4. **Thumbnails** — channel cover art and per-episode thumbnails are downloaded and converted to JPEG (YouTube often serves WebP; ffmpeg converts them for podcast app compatibility)
5. **Pruning** — once a channel exceeds `MAX_EPISODES_PER_CHANNEL`, the oldest episodes are deleted
6. **Feed generation** — RSS feeds are built dynamically from the SQLite database on each request
7. **Deduplication** — already-downloaded files are skipped by file existence check

---

## Data Layout

```
./data/
├── episodes.db              # SQLite database
├── cookies.txt              # YouTube cookies (uploaded via UI)
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

### Docker Hub (recommended)

The image is published to Docker Hub at `ericfaris/youtube-rss:latest`. Pull it with:

```bash
docker compose pull && docker compose up -d
```

No local build required.

### Building locally

```bash
docker compose up --build
```

### Making the app publicly accessible

If your podcast app fetches feeds through its own servers (Pocket Casts does this), you need a public URL. The recommended approach is a **Cloudflare Tunnel** — free, no port forwarding required, works from any network including WSL2.

See **[CLOUDFLARE_TUNNEL.md](CLOUDFLARE_TUNNEL.md)** for full step-by-step instructions.

### Important: Do not deploy to Railway or other datacenter hosts

YouTube blocks requests from datacenter IP ranges. The app must run on your own hardware (home server, PC, NAS, etc.) where requests originate from a residential IP.

---

## YouTube Cookies

YouTube increasingly requires authentication to avoid rate limiting and to access some content. Upload a cookies file via the management UI:

1. Export cookies from your browser using a browser extension (e.g. "Get cookies.txt LOCALLY" for Chrome)
2. Go to the management UI → **YouTube Cookies** section → upload the file
3. Uncomment `COOKIES_FILE=/data/cookies.txt` in `docker-compose.yml`
4. Restart the container

Cookies expire every few weeks. Re-upload when downloads start failing.
