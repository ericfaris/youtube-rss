import base64
import html as _html
import logging
import os
import secrets
import threading
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app import database as db
from app.config import AUDIO_DIR, AUTH_PASS, AUTH_USER, BASE_URL, COOKIES_FILE, POLL_INTERVAL_HOURS, THUMBNAIL_DIR
from app.downloader import cookies_status, download_single, poll_all, poll_channel, remove_channel_data
from app.feed import build_feed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

def _get_version() -> str:
    try:
        import subprocess
        return subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0"],
            stderr=subprocess.DEVNULL
        ).decode().strip().lstrip("v")
    except Exception:
        return "unknown"

VERSION = _get_version()

# Paths that podcast apps access — no auth required
_PUBLIC_PREFIXES = ("/feed/", "/audio/", "/thumbnails/", "/health")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()

    scheduler = BackgroundScheduler()
    scheduler.add_job(poll_all, "interval", hours=POLL_INTERVAL_HOURS)
    scheduler.start()

    channels = db.get_channels()
    if channels:
        logger.info("Running initial poll for %d channel(s)", len(channels))
        threading.Thread(target=poll_all, daemon=True).start()
    else:
        logger.warning("No channels configured — add one at %s", BASE_URL)

    yield

    scheduler.shutdown()


app = FastAPI(title="YouTube RSS", lifespan=lifespan)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if not AUTH_USER and not AUTH_PASS:
        return await call_next(request)
    if request.url.path.startswith(_PUBLIC_PREFIXES):
        return await call_next(request)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode()
            username, password = decoded.split(":", 1)
            if (secrets.compare_digest(username.encode(), AUTH_USER.encode()) and
                    secrets.compare_digest(password.encode(), AUTH_PASS.encode())):
                return await call_next(request)
        except Exception:
            pass
    return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="YouTube RSS"'})

os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(THUMBNAIL_DIR, exist_ok=True)
app.mount("/audio", StaticFiles(directory=AUDIO_DIR), name="audio")
app.mount("/thumbnails", StaticFiles(directory=THUMBNAIL_DIR), name="thumbnails")
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")


# ---------------------------------------------------------------------------
# Management UI
# ---------------------------------------------------------------------------

def _feed_url(channel_id: str) -> str:
    return f"{BASE_URL}/feed/{channel_id}.xml"


def _render_auth_card() -> str:
    cs = cookies_status()
    if cs["present"]:
        badge = f'<span style="color:#4a7c3f;font-weight:600">&#10003; Cookies active</span> <span style="font-size:0.8rem;color:#96acb7">updated {cs["updated"]}</span>'
    else:
        badge = '<span style="color:#a03030;font-weight:600">&#10007; No cookies</span> <span style="font-size:0.8rem;color:#96acb7">YouTube may block downloads</span>'

    return f"""
        <div class="card">
            <div class="card-header">YouTube Cookies</div>
            <div class="card-body">
                <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:14px">
                    {badge}
                </div>
                <form class="add-form" method="post" action="/auth/cookies" enctype="multipart/form-data">
                    <input type="file" name="file" accept=".txt" required
                           style="flex:1;min-width:200px;padding:8px;border:1px solid #d4e4bc;border-radius:6px;background:#f8fbf5;font-size:0.85rem">
                    <button type="submit" class="btn-primary">Upload cookies.txt</button>
                </form>
                <details style="margin-top:14px">
                    <summary style="font-size:0.82rem;color:#36558f;cursor:pointer;user-select:none">How to export cookies.txt</summary>
                    <ol style="margin:10px 0 0 18px;font-size:0.82rem;color:#1a2335;line-height:1.9">
                        <li>Install the <a href="https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc" target="_blank" style="color:#36558f">Get cookies.txt LOCALLY</a> extension in Chrome (or <a href="https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/" target="_blank" style="color:#36558f">cookies.txt</a> in Firefox)</li>
                        <li>Go to <a href="https://www.youtube.com" target="_blank" style="color:#36558f">youtube.com</a> and make sure you are logged in</li>
                        <li>Click the extension icon and export as <strong>cookies.txt</strong></li>
                        <li>Upload the file using the form above</li>
                        <li>Cookies expire after a few weeks — repeat when downloads start failing with a bot error</li>
                    </ol>
                </details>
            </div>
        </div>"""


def _render_ui() -> str:
    channels = db.get_channels()
    rows = ""
    for ch in channels:
        channel_id = ch["channel_id"]
        name = ch["channel_name"] or ch["url"]
        episode_count = len(db.get_episodes(channel_id)) if channel_id else 0
        feed_url = _feed_url(channel_id) if channel_id else "—"
        feed_link = f'<a href="{feed_url}" target="_blank">{feed_url}</a> <button type="button" class="btn-copy" data-url="{_html.escape(feed_url, quote=True)}">&#128203;</button>' if channel_id else "—"
        rows += f"""
        <tr>
            <td>{name}</td>
            <td>{episode_count}</td>
            <td class="feed-url">{feed_link}</td>
            <td>
                <form method="post" action="/channels/poll" style="display:inline">
                    <input type="hidden" name="url" value="{ch['url']}">
                    <button class="btn-secondary">Poll Now</button>
                </form>
                <form method="post" action="/channels/remove" style="display:inline"
                      onsubmit="return confirm('Remove {name}?')">
                    <input type="hidden" name="url" value="{ch['url']}">
                    <button class="btn-danger">Remove</button>
                </form>
            </td>
        </tr>"""

    empty = "<tr><td colspan='4' class='empty'>No channels yet — add one below.</td></tr>" if not channels else ""

    unsubscribed = db.get_unsubscribed_channels()
    unsub_rows = ""
    for ch in unsubscribed:
        channel_id = ch["channel_id"]
        name = ch["channel_name"] or channel_id
        episode_count = len(db.get_episodes(channel_id))
        feed_url = _feed_url(channel_id)
        feed_link = f'<a href="{feed_url}" target="_blank">{feed_url}</a> <button type="button" class="btn-copy" data-url="{_html.escape(feed_url, quote=True)}">&#128203;</button>'
        unsub_rows += f"""
        <tr>
            <td>{name}</td>
            <td>{episode_count}</td>
            <td class="feed-url">{feed_link}</td>
            <td>
                <form method="post" action="/channels/subscribe" style="display:inline">
                    <input type="hidden" name="channel_id" value="{channel_id}">
                    <input type="hidden" name="channel_name" value="{name}">
                    <button class="btn-secondary">Subscribe</button>
                </form>
            </td>
        </tr>"""
    unsub_empty = "<tr><td colspan='4' class='empty'>No one-off downloads yet.</td></tr>" if not unsubscribed else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="icon" href="/static/favicon.ico" type="image/x-icon">
    <title>YouTube RSS</title>
    <style>
        *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

        body {{
            font-family: system-ui, -apple-system, sans-serif;
            background: #f0f4f8;
            color: #1a2335;
            min-height: 100vh;
        }}

        header {{
            background: #36558f;
            padding: 0 32px;
            height: 56px;
            display: flex;
            align-items: center;
            box-shadow: 0 2px 8px rgba(54,85,143,0.3);
        }}
        header h1 {{
            color: #d4e4bc;
            font-size: 1.1rem;
            font-weight: 600;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }}

        main {{
            max-width: 1000px;
            margin: 36px auto;
            padding: 0 24px;
            display: flex;
            flex-direction: column;
            gap: 24px;
        }}

        .card {{
            background: #fff;
            border-radius: 10px;
            box-shadow: 0 1px 4px rgba(54,85,143,0.08);
            overflow: hidden;
        }}
        .card-header {{
            background: #36558f;
            color: #d4e4bc;
            padding: 14px 20px;
            font-size: 0.8rem;
            font-weight: 600;
            letter-spacing: 0.07em;
            text-transform: uppercase;
        }}
        .card-body {{
            padding: 20px;
        }}

        table {{ width: 100%; border-collapse: collapse; }}
        th {{
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: .06em;
            color: #96acb7;
            text-align: left;
            padding: 10px 14px;
            border-bottom: 2px solid #d4e4bc;
        }}
        td {{
            padding: 12px 14px;
            border-bottom: 1px solid #f0f4f0;
            vertical-align: middle;
            font-size: 0.9rem;
        }}
        tr:last-child td {{ border-bottom: none; }}
        .feed-url {{ font-size: 0.78rem; color: #96acb7; }}
        .feed-url a {{ color: #36558f; text-decoration: none; }}
        .feed-url a:hover {{ text-decoration: underline; }}
        .empty {{ color: #96acb7; font-style: italic; padding: 20px 14px; font-size: 0.88rem; }}

        .add-form {{
            display: flex;
            gap: 10px;
            align-items: center;
            flex-wrap: wrap;
        }}
        input[type=text] {{
            flex: 1;
            min-width: 200px;
            padding: 10px 14px;
            border: 1px solid #d4e4bc;
            border-radius: 6px;
            font-size: 0.9rem;
            background: #f8fbf5;
            color: #1a2335;
            transition: border-color 0.15s;
        }}
        input[type=text]:focus {{
            outline: none;
            border-color: #96acb7;
            background: #fff;
        }}

        button {{
            padding: 10px 18px;
            border-radius: 6px;
            font-size: 0.85rem;
            font-weight: 500;
            cursor: pointer;
            border: none;
            white-space: nowrap;
            transition: background 0.15s, opacity 0.15s;
        }}
        .btn-primary {{ background: #36558f; color: #d4e4bc; }}
        .btn-primary:hover {{ background: #2a4275; }}
        .btn-secondary {{
            background: none;
            color: #36558f;
            border: 1px solid #96acb7;
            padding: 6px 12px;
            font-size: 0.8rem;
        }}
        .btn-secondary:hover {{ background: #f0f4f8; }}
        .btn-danger {{
            background: none;
            color: #a03030;
            border: 1px solid #d4a0a0;
            padding: 6px 12px;
            font-size: 0.8rem;
        }}
        .btn-danger:hover {{ background: #fff5f5; }}
        .btn-copy {{
            background: none;
            border: none;
            padding: 2px 5px;
            font-size: 1rem;
            vertical-align: middle;
            cursor: pointer;
            opacity: 0.4;
            transition: opacity 0.15s;
        }}
        .btn-copy:hover {{ opacity: 1; }}

        .version {{
            position: fixed;
            bottom: 12px;
            right: 16px;
            font-size: 0.72rem;
            color: #96acb7;
            opacity: 0.6;
        }}

        .toggle-label {{
            display: flex;
            align-items: center;
            gap: 7px;
            font-size: 0.85rem;
            color: #96acb7;
            white-space: nowrap;
            cursor: pointer;
        }}
        .toggle-label input {{ accent-color: #36558f; }}

        .actions {{ display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }}
    </style>
</head>
<body>
    <header>
        <h1>YouTube RSS</h1>
    </header>
    <main>
        <div class="card">
            <div class="card-header">Subscribed Channels</div>
            <table>
                <thead>
                    <tr>
                        <th>Channel</th>
                        <th>Episodes</th>
                        <th>Feed URL</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}{empty}
                </tbody>
            </table>
            <div class="card-body">
                <form class="add-form" method="post" action="/channels/add">
                    <input type="text" name="url" placeholder="https://www.youtube.com/@channel" required>
                    <button type="submit" class="btn-primary">Add Channel</button>
                </form>
            </div>
        </div>

        {_render_auth_card()}

        <div class="card">
            <div class="card-header">One-off Downloads</div>
            <table>
                <thead>
                    <tr>
                        <th>Channel</th>
                        <th>Episodes</th>
                        <th>Feed URL</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {unsub_rows}{unsub_empty}
                </tbody>
            </table>
            <div class="card-body">
                <form class="add-form" method="post" action="/episodes/download">
                    <input type="text" name="url" placeholder="https://youtu.be/abc123 or youtube.com/watch?v=..." required>
                    <label class="toggle-label">
                        <input type="checkbox" name="subscribe" value="true">
                        Subscribe to channel
                    </label>
                    <button type="submit" class="btn-primary">Download Episode</button>
                </form>
            </div>
        </div>
    </main>
    <div class="version">v{VERSION}</div>
    <script>
        document.addEventListener('click', function(e) {{
            const btn = e.target.closest('.btn-copy');
            if (!btn) return;
            const url = btn.dataset.url;
            function onSuccess() {{
                btn.textContent = '\u2713';
                setTimeout(() => btn.innerHTML = '&#128203;', 1500);
            }}
            if (navigator.clipboard && navigator.clipboard.writeText) {{
                navigator.clipboard.writeText(url).then(onSuccess).catch(() => fallback(url, onSuccess));
            }} else {{
                fallback(url, onSuccess);
            }}
        }});
        function fallback(text, onSuccess) {{
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            try {{ document.execCommand('copy'); onSuccess(); }} catch(e) {{ prompt('Copy this URL:', text); }}
            document.body.removeChild(ta);
        }}
    </script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return _render_ui()


@app.get("/download")
def download_via_link(url: str, subscribe: bool = False):
    """Shareable link — clicking it downloads a specific video."""
    threading.Thread(target=download_single, args=[url, subscribe], daemon=True).start()
    return RedirectResponse("/", status_code=302)


@app.post("/episodes/download")
def download_episode(url: str = Form(...), subscribe: bool = Form(False)):
    threading.Thread(target=download_single, args=[url, subscribe], daemon=True).start()
    return RedirectResponse("/", status_code=302)


@app.get("/add")
def add_via_link(channel: str):
    """Shareable link — clicking it adds the channel and redirects to the UI."""
    db.add_channel(channel.rstrip("/"))
    threading.Thread(target=poll_channel, args=[channel], daemon=True).start()
    return RedirectResponse("/", status_code=302)


@app.post("/channels/add")
def add_channel(url: str = Form(...)):
    db.add_channel(url.rstrip("/"))
    threading.Thread(target=poll_channel, args=[url], daemon=True).start()
    return RedirectResponse("/", status_code=302)


@app.post("/channels/subscribe")
def subscribe_channel(channel_id: str = Form(...), channel_name: str = Form(...)):
    channel_page_url = f"https://www.youtube.com/channel/{channel_id}"
    db.add_channel(channel_page_url)
    db.update_channel_meta(channel_page_url, channel_id, channel_name)
    db.remove_unsubscribed_channel(channel_id)
    threading.Thread(target=poll_channel, args=[channel_page_url], daemon=True).start()
    return RedirectResponse("/", status_code=302)


@app.post("/channels/remove")
def remove_channel(url: str = Form(...)):
    channels = db.get_channels()
    channel_id = next((ch["channel_id"] for ch in channels if ch["url"] == url.rstrip("/")), None)
    db.remove_channel(url.rstrip("/"))
    if channel_id:
        db.delete_episodes_for_channel(channel_id)
        remove_channel_data(channel_id)
    return RedirectResponse("/", status_code=302)


@app.post("/auth/cookies")
async def upload_cookies(file: UploadFile = File(...)):
    if not COOKIES_FILE:
        raise HTTPException(status_code=500, detail="COOKIES_FILE env var not set")
    os.makedirs(os.path.dirname(COOKIES_FILE), exist_ok=True)
    content = await file.read()
    with open(COOKIES_FILE, "wb") as f:
        f.write(content)
    logger.info("Cookies file updated (%d bytes)", len(content))
    return RedirectResponse("/", status_code=302)


@app.post("/channels/poll")
def poll_now(url: str = Form(...)):
    threading.Thread(target=poll_channel, args=[url], daemon=True).start()
    return RedirectResponse("/", status_code=302)


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
    return {"status": "ok"}
