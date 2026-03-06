# Cloudflare Tunnel Setup

This document explains how to expose your self-hosted youtube-rss app to the internet using a Cloudflare Tunnel, so that podcast apps like Pocket Casts (which fetch feeds through their own servers) can reach it.

## Why Cloudflare Tunnel?

Pocket Casts and some other podcast apps do not fetch feeds directly from your phone or device — they route requests through their own servers. This means your app needs a publicly reachable URL, even if you are only using it personally.

**Cloudflare Tunnel** solves this without:
- Opening ports on your router
- Having a static IP
- Any inbound firewall rules

It works by running a small agent (`cloudflared`) on your machine that creates an outbound connection to Cloudflare's edge network. Cloudflare then routes public HTTPS traffic to your local app through that connection. Your machine initiates the connection — nothing needs to reach in.

---

## What You Need

- A domain name (e.g. purchased from Namecheap — any registrar works)
- A free [Cloudflare account](https://cloudflare.com)
- `cloudflared` installed on your machine (WSL2 instructions below)
- Your youtube-rss container running locally

---

## Step 1 — Add Your Domain to Cloudflare

1. Log into [cloudflare.com](https://cloudflare.com) and click **Add a Site**
2. Enter your domain (e.g. `mooseflip.com`) and select the **Free** plan
3. Cloudflare will scan your existing DNS records and show you two nameserver addresses, e.g.:
   ```
   ada.ns.cloudflare.com
   vera.ns.cloudflare.com
   ```
4. Go to your domain registrar (e.g. Namecheap) and update the nameservers:
   - Namecheap: **Domain List** → **Manage** → **Nameservers** → select **Custom DNS** → enter the two Cloudflare nameservers
5. Save and wait. DNS propagation can take anywhere from 5 minutes to a few hours. Cloudflare will email you when it's active.

---

## Step 2 — Install cloudflared

On WSL2 (Ubuntu/Debian):

```bash
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared
chmod +x cloudflared
sudo mv cloudflared /usr/local/bin/
```

Verify it installed:
```bash
cloudflared --version
```

---

## Step 3 — Authenticate cloudflared with Cloudflare

```bash
cloudflared tunnel login
```

This opens a browser window. Log into your Cloudflare account and select your domain (`mooseflip.com`). After authorizing, a certificate file is saved to `~/.cloudflared/cert.pem`. This certificate gives cloudflared permission to create tunnels for your domain.

---

## Step 4 — Create the Tunnel

```bash
cloudflared tunnel create youtube-rss
```

This creates a named tunnel and saves a credentials JSON file:
```
Tunnel credentials written to /home/eric/.cloudflared/<TUNNEL-ID>.json
Created tunnel youtube-rss with id <TUNNEL-ID>
```

The tunnel ID is a UUID like `83441a36-f288-40e3-ab39-9393b284ccc5`. Note it down — you will need it in the next step.

The credentials file is a secret. Anyone with this file can send traffic through your tunnel. Do not commit it to git.

---

## Step 5 — Create the Config File

Create the cloudflared configuration file at `/etc/cloudflared/config.yml` (the system-wide location used by the service):

```bash
sudo mkdir -p /etc/cloudflared
```

Create the file (replace `<TUNNEL-ID>` with your actual tunnel ID):

```bash
sudo nano /etc/cloudflared/config.yml
```

Paste:

```yaml
tunnel: <TUNNEL-ID>
credentials-file: /etc/cloudflared/<TUNNEL-ID>.json

ingress:
  - hostname: rss.mooseflip.com
    service: http://localhost:8000
  - service: http_status:404
```

**What this does:**
- `tunnel` — the name or ID of the tunnel to run
- `credentials-file` — path to the credentials JSON (identifies this machine to Cloudflare)
- `ingress` — routing rules: requests to `rss.mooseflip.com` are forwarded to `http://localhost:8000` on your machine; anything else returns a 404
- The last `service: http_status:404` is required as a catch-all rule

---

## Step 6 — Copy Credentials to /etc/cloudflared

The credentials file needs to be accessible to the system service:

```bash
sudo cp ~/.cloudflared/<TUNNEL-ID>.json /etc/cloudflared/
sudo chmod 644 /etc/cloudflared/<TUNNEL-ID>.json
```

---

## Step 7 — Create the DNS Record

Tell Cloudflare to route `rss.mooseflip.com` to your tunnel:

```bash
cloudflared tunnel route dns youtube-rss rss.mooseflip.com
```

This creates a `CNAME` record in your Cloudflare DNS pointing `rss.mooseflip.com` to `<TUNNEL-ID>.cfargotunnel.com`. You can verify it in the Cloudflare dashboard under **DNS**.

---

## Step 8 — Test the Tunnel

Before installing as a service, test that it works:

```bash
cloudflared tunnel --config /etc/cloudflared/config.yml run youtube-rss
```

Leave this running and open `https://rss.mooseflip.com` in a browser. You should see the management UI login prompt. If it works, hit `Ctrl+C` to stop it.

---

## Step 9 — Install as a System Service

Install cloudflared as a systemd service so it starts automatically:

```bash
sudo cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
```

Verify it is running:

```bash
sudo systemctl status cloudflared
```

You should see `Active: active (running)` and log lines showing registered tunnel connections.

---

## Step 10 — Update BASE_URL

Update `BASE_URL` in your `docker-compose.yml` to the public URL:

```yaml
- BASE_URL=https://rss.mooseflip.com
```

Restart the container:

```bash
docker compose down && docker compose up -d
```

Feed URLs shown in the management UI will now use the public domain, which is what you paste into Pocket Casts.

---

## How to Verify Everything Is Working

1. **Management UI** — open `https://rss.mooseflip.com` in a browser. You should see a login prompt.
2. **Feed** — open `https://rss.mooseflip.com/feed/<channel_id>.xml` — you should see RSS XML without being prompted for a password (feeds are public).
3. **Pocket Casts** — add the feed URL in the Pocket Casts mobile app. It should find the podcast immediately.

---

## File Reference

| File | Purpose |
|---|---|
| `~/.cloudflared/cert.pem` | Cloudflare origin certificate — authorizes tunnel creation for your domain |
| `/etc/cloudflared/config.yml` | Tunnel configuration used by the system service |
| `/etc/cloudflared/<TUNNEL-ID>.json` | Tunnel credentials — identifies your machine to Cloudflare |

---

## Managing the Service

```bash
# Check status
sudo systemctl status cloudflared

# View logs
sudo journalctl -u cloudflared -f

# Restart
sudo systemctl restart cloudflared

# Stop
sudo systemctl stop cloudflared
```

---

## Recreating from Scratch

If you lose your machine and need to set this up again on a new one:

1. Install `cloudflared` (Step 2)
2. Run `cloudflared tunnel login` (Step 3) — this re-authenticates with Cloudflare
3. The tunnel already exists in Cloudflare — list it with:
   ```bash
   cloudflared tunnel list
   ```
4. Download the credentials for the existing tunnel from the Cloudflare dashboard (**Zero Trust** → **Networks** → **Tunnels** → select your tunnel → **Configure** → **Credentials**)
   - Or delete the old tunnel and create a new one with `cloudflared tunnel create youtube-rss`, then update the DNS record
5. Place the credentials JSON in `/etc/cloudflared/`
6. Recreate `config.yml` using the tunnel ID (Step 5)
7. Install the service (Step 9)
8. The DNS record (`rss.mooseflip.com → CNAME → <tunnel-id>.cfargotunnel.com`) already exists in Cloudflare — no changes needed there unless you deleted and recreated the tunnel

---

## Notes

- **HTTPS is automatic** — Cloudflare terminates TLS. Your local app runs plain HTTP on port 8000; Cloudflare handles the certificate and serves it as HTTPS.
- **WSL2 caveat** — the cloudflared systemd service runs inside WSL2, not Windows. WSL2 must be running for the tunnel to be active. If you restart Windows, open a WSL2 terminal once and the service will start automatically (WSL2 starts on first terminal open).
- **Free tier limits** — Cloudflare Tunnel is free with no bandwidth limits for personal use.
- **Security** — feeds and audio are public (required for podcast apps). The management UI at `/` requires your `AUTH_USER` / `AUTH_PASS` credentials.
