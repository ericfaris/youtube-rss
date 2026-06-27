import base64
import ipaddress
import logging
import os
import re
import secrets
import threading
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app import database as db
from app import jobs
from app import notify
from app.config import AUDIO_DIR, ALERT_EMAIL, AUTH_CREDENTIALS, BASE_URL, COOKIES_FILE, POLL_INTERVAL_HOURS, THUMBNAIL_DIR
from app.downloader import cookies_status, download_single, poll_all, poll_channel, remove_channel_data, valid_cookie_file
from app.feed import build_feed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

def _get_version() -> str:
    # Static package version is the source of truth (works inside Docker where
    # there's no git history). Append the short git sha when available locally.
    from app import __version__
    version = __version__
    try:
        import subprocess
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        if sha:
            version = f"{version}+{sha}"
    except Exception:
        pass
    return version

VERSION = _get_version()

_scheduler: BackgroundScheduler | None = None

# Paths that podcast apps access — no auth required
_PUBLIC_PREFIXES = ("/feed/", "/audio/", "/thumbnails/", "/health")

# Rate limiting: max failed auth attempts per IP within the window
_RATE_LIMIT_MAX = 10
_RATE_LIMIT_WINDOW = 60  # seconds
_failed_attempts: dict[str, list[float]] = defaultdict(list)
_rate_limit_lock = threading.Lock()
_CHANNEL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_MAX_COOKIE_BYTES = 5 * 1024 * 1024  # 5 MB


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    db.init_db()

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(poll_all, "interval", hours=POLL_INTERVAL_HOURS)
    _scheduler.add_job(_prune_rate_limit_table, "interval", hours=1)
    _scheduler.start()

    channels = db.get_channels()
    if channels:
        logger.info("Running initial poll for %d channel(s)", len(channels))
        threading.Thread(target=poll_all, daemon=True).start()
    else:
        logger.warning("No channels configured — add one at %s", BASE_URL)

    yield

    _scheduler.shutdown()


app = FastAPI(title="Slipcast", lifespan=lifespan)


def _is_trusted_proxy(ip: str) -> bool:
    """Only believe forwarded-for headers from a loopback/private peer.

    Behind the Cloudflare tunnel the direct peer is cloudflared on the Docker
    bridge (loopback/RFC1918), and the real client is in CF-Connecting-IP. If a
    request arrives from a public peer we must NOT trust client-supplied
    forwarding headers, or an attacker could spoof IPs to evade the rate limiter.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.is_loopback or addr.is_private


def _client_ip(request: Request) -> str:
    """Return the real client IP, accounting for Cloudflare and other proxies."""
    peer = request.client.host if request.client else None
    if peer and _is_trusted_proxy(peer):
        for header in ("CF-Connecting-IP", "X-Real-IP", "X-Forwarded-For"):
            value = request.headers.get(header)
            if value:
                return value.split(",")[0].strip()
    return peer or "unknown"


def _check_rate_limit(ip: str) -> bool:
    """Return True if the IP is rate-limited (too many recent failures)."""
    now = time.monotonic()
    with _rate_limit_lock:
        _failed_attempts[ip] = [t for t in _failed_attempts[ip] if now - t < _RATE_LIMIT_WINDOW]
        return len(_failed_attempts[ip]) >= _RATE_LIMIT_MAX


def _record_failure(ip: str):
    now = time.monotonic()
    with _rate_limit_lock:
        _failed_attempts[ip].append(now)
    logger.warning("Failed auth attempt from %s", ip)


def _clear_failures(ip: str):
    with _rate_limit_lock:
        _failed_attempts.pop(ip, None)


def _prune_rate_limit_table():
    """Remove IPs with no recent failures to prevent unbounded memory growth."""
    now = time.monotonic()
    with _rate_limit_lock:
        stale = [ip for ip, attempts in _failed_attempts.items()
                 if all(now - t >= _RATE_LIMIT_WINDOW for t in attempts)]
        for ip in stale:
            del _failed_attempts[ip]


# GET endpoints that mutate state ("shareable links"). They bypass the usual
# POST-only CSRF gate, so they get the same Origin/Referer check.
_MUTATING_GET_PATHS = frozenset({"/add", "/download"})


def _is_state_changing(request: Request) -> bool:
    return request.method == "POST" or request.url.path in _MUTATING_GET_PATHS


def _csrf_ok(request: Request) -> bool:
    """Validate Origin/Referer against Host for state-changing requests.

    - POST (UI form submissions always carry Origin/Referer): fail **closed** —
      a missing header is rejected.
    - Mutating GET shareable links: allow a missing Origin/Referer (top-level
      navigation, bookmarks, address-bar) but reject a *mismatched* one, which
      blocks the embedded cross-site request (`<img src=".../add?...">`) attack.
    """
    host = request.headers.get("Host", "")
    for header in ("Origin", "Referer"):
        value = request.headers.get(header, "")
        if value and value != "null":
            return urlparse(value).netloc == host
    # No usable Origin/Referer: only allowed for non-POST (GET shareable links).
    return request.method != "POST"


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    is_public = request.url.path.startswith(_PUBLIC_PREFIXES)
    if not AUTH_CREDENTIALS:
        if not is_public and _is_state_changing(request) and not _csrf_ok(request):
            return Response(status_code=403, content="CSRF check failed")
        return await call_next(request)

    if is_public:
        return await call_next(request)

    ip = _client_ip(request)

    if _check_rate_limit(ip):
        logger.warning("Rate-limited auth attempt from %s", ip)
        return Response(status_code=429, content="Too many failed login attempts. Try again later.")

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode()
            username, password = decoded.split(":", 1)
            if any(
                secrets.compare_digest(username.encode(), u.encode()) and
                secrets.compare_digest(password.encode(), p.encode())
                for u, p in AUTH_CREDENTIALS
            ):
                _clear_failures(ip)
                if _is_state_changing(request) and not _csrf_ok(request):
                    return Response(status_code=403, content="CSRF check failed")
                return await call_next(request)
        except Exception:
            pass
    _record_failure(ip)
    return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Slipcast"'})

os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(THUMBNAIL_DIR, exist_ok=True)
app.mount("/audio", StaticFiles(directory=AUDIO_DIR), name="audio")
app.mount("/thumbnails", StaticFiles(directory=THUMBNAIL_DIR), name="thumbnails")
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_poll_label() -> str:
    """Return a human-readable 'next poll in X' string, or empty string if unknown."""
    if _scheduler is None:
        return ""
    for job in _scheduler.get_jobs():
        if job.func is poll_all and job.next_run_time:
            import datetime
            now = datetime.datetime.now(datetime.timezone.utc)
            delta = job.next_run_time - now
            total = int(delta.total_seconds())
            if total <= 0:
                return "polling now"
            h, rem = divmod(total, 3600)
            m = rem // 60
            if h:
                return f"next poll in {h}h {m:02d}m"
            return f"next poll in {m}m"
    return ""


def _feed_url(channel_id: str) -> str:
    return f"{BASE_URL}/feed/{channel_id}.xml"


def _channel_thumb_exists(channel_id: str) -> bool:
    return bool(channel_id) and os.path.exists(os.path.join(THUMBNAIL_DIR, channel_id, "channel.jpg"))


def _thumb_url(channel_id: str) -> str | None:
    return f"{BASE_URL}/thumbnails/{channel_id}/channel.jpg" if _channel_thumb_exists(channel_id) else None


def _episode_count(channel_id: str | None) -> int:
    return len(db.get_episodes(channel_id)) if channel_id else 0


def _total_episodes() -> int:
    return sum(len(db.get_episodes(cid)) for cid in db.get_all_channel_ids())


def _is_valid_channel_url(url: str) -> bool:
    try:
        p = urlparse(url)
    except ValueError:
        return False
    return p.scheme in ("http", "https") and bool(p.netloc)


# ---------------------------------------------------------------------------
# Background job wrappers — record progress so the UI can show it live
# ---------------------------------------------------------------------------

def _run_poll(url: str, label: str | None = None):
    rurl = url.rstrip("/")

    def lookup():
        ch = next((c for c in db.get_channels() if c["url"] == rurl), None)
        if not ch:
            return None, None
        return (ch["channel_name"] or None), (ch["channel_id"] or None)

    pre_name, pre_cid = lookup()
    label = label or pre_name or rurl
    before = _episode_count(pre_cid)
    jid = jobs.start("poll", label)
    try:
        poll_channel(url)
        post_name, post_cid = lookup()
        label = post_name or label
        added = _episode_count(post_cid) - before
        if added > 0:
            jobs.finish(jid, "success", f"{label}: {added} new episode(s)")
        else:
            jobs.finish(jid, "success", f"{label}: no new episodes")
    except Exception as exc:  # poll_channel is defensive, but never let a job hang
        logger.exception("Poll job failed for %s", rurl)
        jobs.finish(jid, "error", f"{label}: {exc}")


def _run_download(url: str, subscribe: bool):
    jid = jobs.start("download", url)
    before = _total_episodes()
    try:
        download_single(url, subscribe)
        if _total_episodes() > before:
            jobs.finish(jid, "success", "Episode downloaded")
        else:
            jobs.finish(jid, "error", "Nothing downloaded — video may be unavailable, private, or already saved")
    except Exception as exc:
        logger.exception("Download job failed for %s", url)
        jobs.finish(jid, "error", str(exc))


# ---------------------------------------------------------------------------
# Management UI shell — content is rendered client-side from /api/state
# ---------------------------------------------------------------------------

_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="color-scheme" content="light dark">
    <link rel="icon" href="/static/favicon.ico" type="image/x-icon">
    <link rel="stylesheet" href="/static/styles.css">
    <title>Slipcast</title>
</head>
<body>
    <a class="skip-link" href="#main">Skip to content</a>
    <header class="appbar">
        <div class="appbar-inner">
            <div class="brand">
                <svg class="brand-mark" viewBox="0 0 24 24" aria-hidden="true" width="26" height="26">
                    <path d="M4 14a8 8 0 0 1 8-8" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>
                    <path d="M4 19a13 13 0 0 1 13-13" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" opacity=".55"/>
                    <circle cx="6" cy="18" r="2.4" fill="currentColor"/>
                </svg>
                <span class="brand-name">Slipcast</span>
            </div>
            <div class="appbar-actions">
                <span id="activity" class="activity" hidden><span class="spinner"></span><span id="activity-text">Working…</span></span>
                <button id="poll-all" class="btn btn-ghost" type="button">Poll all</button>
            </div>
        </div>
    </header>

    <div id="cookie-banner" class="banner" hidden></div>

    <main id="main" class="wrap">
        <section class="section" aria-labelledby="subs-h">
            <div class="section-head">
                <h2 id="subs-h">Subscribed channels <span id="subs-count" class="count-pill"></span></h2>
                <div class="next-poll" id="next-poll"></div>
            </div>

            <form id="add-form" class="inline-form" autocomplete="off">
                <label class="visually-hidden" for="add-url">YouTube channel URL</label>
                <input id="add-url" name="url" type="text" inputmode="url"
                       placeholder="Paste a YouTube channel URL — e.g. https://youtube.com/@channel" required>
                <button class="btn btn-primary" type="submit">Add channel</button>
            </form>

            <div class="toolbar" id="subs-toolbar" hidden>
                <div class="search">
                    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" stroke-width="2"/><path d="m20 20-3.2-3.2" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
                    <input id="subs-search" type="search" placeholder="Search channels" aria-label="Search subscribed channels">
                </div>
                <label class="sort">Sort
                    <select id="subs-sort" aria-label="Sort channels">
                        <option value="added">Recently added</option>
                        <option value="name">Name (A–Z)</option>
                        <option value="episodes">Most episodes</option>
                    </select>
                </label>
            </div>

            <div id="bulk-bar" class="bulk-bar" hidden>
                <span id="bulk-count"></span>
                <div class="bulk-actions">
                    <button class="btn btn-ghost" type="button" id="bulk-poll">Poll selected</button>
                    <button class="btn btn-danger-ghost" type="button" id="bulk-remove">Remove selected</button>
                    <button class="btn btn-text" type="button" id="bulk-clear">Clear</button>
                </div>
            </div>

            <div id="subs-grid" class="grid"></div>
        </section>

        <section class="section" aria-labelledby="oneoff-h">
            <div class="section-head">
                <h2 id="oneoff-h">One-off downloads <span id="oneoff-count" class="count-pill"></span></h2>
            </div>
            <form id="dl-form" class="inline-form" autocomplete="off">
                <label class="visually-hidden" for="dl-url">YouTube video URL</label>
                <input id="dl-url" name="url" type="text" inputmode="url"
                       placeholder="Paste a video URL — e.g. https://youtu.be/abc123" required>
                <label class="check">
                    <input type="checkbox" id="dl-subscribe"> Also subscribe
                </label>
                <button class="btn btn-primary" type="submit">Download</button>
            </form>
            <div id="oneoff-grid" class="grid"></div>
        </section>

        <section class="section" aria-labelledby="cookies-h">
            <div class="section-head"><h2 id="cookies-h">YouTube cookies</h2></div>
            <div class="card cookies-card">
                <div id="cookies-status" class="cookies-status"></div>
                <form id="cookies-form" class="inline-form" enctype="multipart/form-data">
                    <input id="cookies-file" name="file" type="file" accept=".txt" required>
                    <button class="btn btn-primary" type="submit">Upload cookies.txt</button>
                </form>
                <div class="cookies-email" id="cookies-email"></div>
                <details class="howto">
                    <summary>How to export cookies.txt</summary>
                    <ol>
                        <li>Install the <a href="https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc" target="_blank" rel="noopener">Get cookies.txt LOCALLY</a> extension (Chrome) or <a href="https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/" target="_blank" rel="noopener">cookies.txt</a> (Firefox).</li>
                        <li>Open <a href="https://www.youtube.com" target="_blank" rel="noopener">youtube.com</a> while logged in.</li>
                        <li>Click the extension and export as <strong>cookies.txt</strong>.</li>
                        <li>Upload the file above. Re-upload every few weeks when downloads start failing.</li>
                    </ol>
                </details>
            </div>
        </section>
    </main>

    <div id="toaster" class="toaster" aria-live="polite" aria-atomic="false"></div>

    <!-- Feed share dialog -->
    <div id="share-modal" class="modal" hidden>
        <div class="modal-backdrop" data-close></div>
        <div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="share-title">
            <button class="modal-close" type="button" data-close aria-label="Close">&times;</button>
            <h3 id="share-title">Share feed</h3>
            <p id="share-name" class="share-name"></p>
            <div id="share-qr" class="share-qr"></div>
            <div class="share-url">
                <input id="share-url-input" type="text" readonly aria-label="Feed URL">
                <button class="btn btn-ghost" type="button" id="share-copy">Copy</button>
            </div>
            <div class="share-apps">
                <a id="share-pocketcasts" class="btn btn-ghost" target="_blank" rel="noopener">Pocket Casts</a>
                <a id="share-apple" class="btn btn-ghost">Apple Podcasts</a>
            </div>
        </div>
    </div>

    <!-- Episodes list dialog -->
    <div id="ep-modal" class="modal" hidden>
        <div class="modal-backdrop" data-close></div>
        <div class="modal-card modal-wide" role="dialog" aria-modal="true" aria-labelledby="ep-title">
            <button class="modal-close" type="button" data-close aria-label="Close">&times;</button>
            <h3 id="ep-title">Episodes</h3>
            <p id="ep-sub" class="share-name"></p>
            <div id="ep-list" class="ep-list"></div>
        </div>
    </div>

    <noscript><p style="padding:24px;text-align:center">Slipcast's dashboard needs JavaScript enabled.</p></noscript>
    <div class="version" id="version"></div>
    <script src="/static/vendor/qrcode.min.js"></script>
    <script src="/static/app.js"></script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(
        content=_PAGE,
        headers={"Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:"},
    )


# ---------------------------------------------------------------------------
# JSON API consumed by the dashboard
# ---------------------------------------------------------------------------

@app.get("/api/state")
def api_state():
    channels = []
    for ch in db.get_channels():
        cid = ch["channel_id"]
        channels.append({
            "url": ch["url"],
            "channel_id": cid,
            "name": ch["channel_name"] or ch["url"],
            "episodes": _episode_count(cid),
            "feed_url": _feed_url(cid) if cid else None,
            "thumbnail": _thumb_url(cid) if cid else None,
            "added_at": ch["added_at"],
        })

    unsubscribed = []
    for ch in db.get_unsubscribed_channels():
        cid = ch["channel_id"]
        unsubscribed.append({
            "channel_id": cid,
            "name": ch["channel_name"] or cid,
            "episodes": _episode_count(cid),
            "feed_url": _feed_url(cid),
            "thumbnail": _thumb_url(cid),
        })

    return JSONResponse({
        "channels": channels,
        "unsubscribed": unsubscribed,
        "cookies": cookies_status(),
        "email": {"configured": notify._smtp_configured(), "address": ALERT_EMAIL},
        "next_poll": _next_poll_label(),
        "jobs": jobs.snapshot(),
        "version": VERSION,
    })


@app.get("/api/channels/{channel_id}/episodes")
def api_channel_episodes(channel_id: str):
    if not _CHANNEL_ID_RE.match(channel_id):
        raise HTTPException(status_code=400, detail="Invalid channel ID")
    episodes = []
    for ep in db.get_episodes(channel_id):
        episodes.append({
            "id": ep["id"],
            "title": ep["title"],
            "published": ep["published"],
            "added_at": ep["created_at"],
            "duration": ep["duration"],
            "filesize": ep["filesize"],
            "audio_url": f"{BASE_URL}/audio/{channel_id}/{ep['filename']}",
            "thumbnail": f"{BASE_URL}/thumbnails/{channel_id}/{ep['thumbnail']}" if ep["thumbnail"] else None,
        })
    return JSONResponse({"channel_id": channel_id, "episodes": episodes})


def _ok(message: str, **extra) -> JSONResponse:
    return JSONResponse({"ok": True, "message": message, **extra})


# ---------------------------------------------------------------------------
# Mutating actions
# ---------------------------------------------------------------------------

@app.get("/download")
def download_via_link(url: str, subscribe: bool = False):
    """Shareable link — clicking it downloads a specific video."""
    threading.Thread(target=_run_download, args=[url, subscribe], daemon=True).start()
    return RedirectResponse("/", status_code=302)


@app.post("/episodes/download")
def download_episode(url: str = Form(...), subscribe: bool = Form(False)):
    if not _is_valid_channel_url(url):
        raise HTTPException(status_code=400, detail="Enter a valid http(s) video URL")
    threading.Thread(target=_run_download, args=[url, subscribe], daemon=True).start()
    return _ok("Download started — this can take a minute")


@app.get("/add")
def add_via_link(channel: str):
    """Shareable link — clicking it adds the channel and redirects to the UI."""
    db.add_channel(channel.rstrip("/"))
    threading.Thread(target=_run_poll, args=[channel], daemon=True).start()
    return RedirectResponse("/", status_code=302)


@app.post("/channels/add")
def add_channel(url: str = Form(...)):
    if not _is_valid_channel_url(url):
        raise HTTPException(status_code=400, detail="Enter a valid http(s) channel URL")
    db.add_channel(url.rstrip("/"))
    threading.Thread(target=_run_poll, args=[url], daemon=True).start()
    return _ok("Channel added — fetching episodes")


@app.post("/channels/subscribe")
def subscribe_channel(channel_id: str = Form(...), channel_name: str = Form(...)):
    if not _CHANNEL_ID_RE.match(channel_id):
        raise HTTPException(status_code=400, detail="Invalid channel ID")
    channel_page_url = f"https://www.youtube.com/channel/{channel_id}"
    db.add_channel(channel_page_url)
    db.update_channel_meta(channel_page_url, channel_id, channel_name)
    db.remove_unsubscribed_channel(channel_id)
    threading.Thread(target=_run_poll, args=[channel_page_url, channel_name], daemon=True).start()
    return _ok(f"Subscribed to {channel_name}")


def _remove_one(url: str):
    rurl = url.rstrip("/")
    channels = db.get_channels()
    channel_id = next((ch["channel_id"] for ch in channels if ch["url"] == rurl), None)
    db.remove_channel(rurl)
    if channel_id:
        db.delete_episodes_for_channel(channel_id)
        db.delete_skip_videos_for_channel(channel_id)
        remove_channel_data(channel_id)


@app.post("/channels/remove")
def remove_channel(url: str = Form(...)):
    _remove_one(url)
    return _ok("Channel removed")


@app.post("/channels/remove-bulk")
async def remove_channels_bulk(request: Request):
    data = await request.json()
    urls = [u for u in data.get("urls", []) if isinstance(u, str)]
    for u in urls:
        _remove_one(u)
    return _ok(f"Removed {len(urls)} channel(s)")


@app.post("/channels/poll")
def poll_now(url: str = Form(...)):
    threading.Thread(target=_run_poll, args=[url], daemon=True).start()
    return _ok("Polling channel")


@app.post("/channels/poll-bulk")
async def poll_channels_bulk(request: Request):
    data = await request.json()
    urls = [u for u in data.get("urls", []) if isinstance(u, str)]
    for u in urls:
        threading.Thread(target=_run_poll, args=[u], daemon=True).start()
    return _ok(f"Polling {len(urls)} channel(s)")


@app.post("/channels/poll-all")
def poll_all_now():
    channels = db.get_channels()
    for ch in channels:
        threading.Thread(target=_run_poll, args=[ch["url"]], daemon=True).start()
    return _ok(f"Polling {len(channels)} channel(s)")


@app.post("/auth/cookies")
async def upload_cookies(file: UploadFile = File(...)):
    if not COOKIES_FILE:
        raise HTTPException(status_code=500, detail="COOKIES_FILE env var not set")
    content = await file.read(_MAX_COOKIE_BYTES + 1)
    if len(content) > _MAX_COOKIE_BYTES:
        raise HTTPException(status_code=413, detail="Cookie file too large (max 5 MB)")
    os.makedirs(os.path.dirname(COOKIES_FILE), exist_ok=True)
    # Validate before overwriting the existing (possibly working) file so a
    # bad upload can't silently break every channel poll.
    tmp_path = COOKIES_FILE + ".upload"
    with open(tmp_path, "wb") as f:
        f.write(content)
    if not valid_cookie_file(tmp_path):
        os.remove(tmp_path)
        raise HTTPException(
            status_code=400,
            detail="Not a valid Netscape-format cookies.txt (file is empty or malformed).",
        )
    os.replace(tmp_path, COOKIES_FILE)
    logger.info("Cookies file updated (%d bytes)", len(content))
    return _ok("Cookies updated — downloads enabled")


@app.post("/auth/test-email")
def test_email():
    if not notify._smtp_configured():
        raise HTTPException(
            status_code=400,
            detail="Email alerts not configured — set SMTP_HOST/SMTP_USER/SMTP_PASS in .env",
        )
    if notify.send_cookie_alert(force=True):
        return _ok("Test email sent")
    raise HTTPException(status_code=502, detail="Failed to send test email — check server logs")


# ---------------------------------------------------------------------------
# Feed endpoints
# ---------------------------------------------------------------------------

@app.get("/feed/{channel_id}.xml", response_class=Response)
def get_feed(channel_id: str):
    rss = build_feed(channel_id)
    if not rss:
        raise HTTPException(status_code=404, detail="Channel not found or no episodes yet")
    return Response(content=rss, media_type="application/rss+xml")


@app.get("/health")
def health():
    return {"status": "ok", "version": VERSION}
