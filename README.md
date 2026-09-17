# videoshare

A tiny Flask app: pick subfolders, each corresponds to a test output,
from a folder on your server, hit **Compare**, and get a shareable link
that shows them side by side — one column per folder, its videos stacked
on top and its stats CSV rendered below (with synced play / pause / restart,
and reasonably in-sync scrubbing).

## Table of Contents

<!-- vim-markdown-toc GFM -->

    * [Files](#files)
    * [Installation](#installation)
    * [Point it at your run folders](#point-it-at-your-run-folders)
    * [Test locally on the server](#test-locally-on-the-server)
    * [Create a Service (recommended)](#create-a-service-recommended)
    * [Quick public share with zrok](#quick-public-share-with-zrok)
    * [Authentication](#authentication)
    * [How sharing works](#how-sharing-works)
* [TODO](#todo)

<!-- vim-markdown-toc -->

## Files

```
videoshare/
├── app.py              # the app
├── templates/
│   ├── index.html      # picker page
│   └── compare.html    # side-by-side comparison page
├── static/style.css
├── requirements.txt
└── videoshare.service  # example systemd unit
```

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Point it at your run folders

By default it looks for a `data/` folder in your home directory (`~/data`).
Either put your run folders there, or point `VIDEO_DIR` at wherever they
already live:

```bash
export VIDEO_DIR=/path/to/your/runs
```

Each **immediate subfolder** of `VIDEO_DIR` is one selectable "run" / test — it
should contain:

- one or more video files (`.mp4 .webm .ogg .mov .m4v .mkv` out of the box —
  edit `ALLOWED_EXTENSIONS` in `app.py` to add more), and
- optionally, a `.csv` file with two columns (`label,value` per row) — its
  rows are shown as stats under that folder's videos on the compare page.

```
videos/
├── run_1/
│   ├── vid1.mp4
│   ├── vid2.mp4
│   └── stats.csv
└── run_2/
    ├── vid1.mp4
    ├── vid2.mp4
    └── stats.csv
```

Videos are matched across folders by sorted filename order (row 1 = each
folder's first video alphabetically, and so on) — name videos consistently
across folders (e.g. `cam_front.mp4`, `cam_rear.mp4` in every folder) so the
rows line up meaningfully. Folders can have different numbers of videos;
missing cells are just left blank. If a folder has more than one `.csv`
file, the first one alphabetically is used.

## Test locally on the server

```bash
python3 app.py
# Serving videos from: /path/to/your/videos
# * Running on http://0.0.0.0:5000
```

Visit `http://YOUR_SERVER_IP:5000` (you may need to open the port: `sudo ufw allow 5000/tcp`).
Check a few boxes, click **Compare selected**, and you'll land on a URL like:

```
http://YOUR_SERVER_IP:5000/compare?f=run_a&f=run_b
```

If you open the service publicly, it would be visible to anyone who opens it, they sees the same comparison using that URL.

## Create a Service (recommended)

Don't leave the dev server running long-term. Use gunicorn behind systemd,
optionally with nginx in front for a clean URL/port and HTTPS.

**systemd service:**

Edit `videoshare.service` (set `User`, `WorkingDirectory`, `VIDEO_DIR`), then:

```bash
sudo cp videoshare.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now videoshare
sudo systemctl status videoshare
```

This binds gunicorn to `127.0.0.1:5000` — reachable only from the server
itself. That's different from `python3 app.py` above, which listens on
`0.0.0.0` (every interface) and is why it's reachable from your public/LAN
IP by default. Once you switch to the service, the same `http://YOUR_SERVER_IP:5000`
link will stop connecting even though the service is running — that's
expected, not a bug: gunicorn is meant to sit behind nginx rather than face
the network directly. Put nginx in front (below) to restore public access,
or, if you'd rather skip nginx, change `-b 127.0.0.1:5000` to
`-b 0.0.0.0:5000` in `videoshare.service`'s `ExecStart` (then `daemon-reload`
+ `restart`) — but note `APP_PASSWORD` then travels over plain HTTP, so
restrict access with a firewall rule if the server is internet-facing.

**nginx reverse proxy** (recommended — gives you port 80/443 and a
normal-looking URL instead of `:5000`, and keeps gunicorn off the network
directly):

If you have a domain pointed at the server:

```nginx
server {
    listen 80;
    server_name videos.example.com;

    client_max_body_size 0;       # videos can be large
    proxy_read_timeout 3600;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Then `sudo systemctl reload nginx`, and optionally get HTTPS with
`sudo certbot --nginx -d videos.example.com`.

No domain — just serving by IP? Use a catch-all server block instead (no
HTTPS is possible this way, since Let's Encrypt requires a real domain):

```nginx
server {
    listen 80 default_server;
    server_name _;

    client_max_body_size 0;
    proxy_read_timeout 3600;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Save either block as `/etc/nginx/sites-available/videoshare`, then:

```bash
sudo ln -sf /etc/nginx/sites-available/videoshare /etc/nginx/sites-enabled/videoshare
sudo rm -f /etc/nginx/sites-enabled/default   # avoid a port-80 conflict
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl enable nginx
sudo ufw allow 80/tcp
```

Once nginx is proxying, visit `http://<server-ip>/` (or your domain) — no
`:5000` needed. You can also remove the `sudo ufw allow 5000/tcp` rule from
the dev-server step above, since gunicorn no longer needs to be reachable
from outside the server.

## Quick public share with zrok

If you just want a public link without setting up nginx, DNS, or certbot,
[zrok](https://docs.zrok.io) tunnels a local port out to a public HTTPS URL
for you — no inbound firewall rule needed. Good for a quick share; the
nginx setup above is still the better fit for a stable, permanent URL.

**One-time setup:**

```bash
curl -sSLf https://get.openziti.io/install.bash | sudo bash -s zrok
zrok version   # confirms it installed

zrok invite                # creates a free zrok.io account (email verification)
zrok enable <your_token>   # links this machine to your account (token is emailed to you)
```

If you already have a zrok account, skip `zrok invite` and just run `zrok
enable <your_token>` with the token from your account page.

**Share the app:**

Run the app bound to `127.0.0.1` — either the dev server:

```bash
HOST=127.0.0.1 python3 app.py
```

or the systemd service from above, which already binds to `127.0.0.1:5000`.
Then, in another terminal:

```bash
zrok share public http://127.0.0.1:5000
```

This prints a public `https://something.share.zrok.io` URL — that's your
shareable link. zrok terminates HTTPS for you, so `APP_PASSWORD` isn't sent
in the clear even though gunicorn/Flask itself only speaks plain HTTP
locally.

Notes:

- Each `zrok share public` run gets a new random URL by default (the
  session ends when you `Ctrl-C` it) — check zrok's *reserved* shares if
  you want a stable URL that survives restarts.
- Keep gunicorn/Flask bound to `127.0.0.1`, not `0.0.0.0` — zrok reaches it
  locally, so it never needs to be reachable from the network directly, and
  no `ufw allow` rule is needed for this path.
- `APP_PASSWORD`/`SECRET_KEY` still matter exactly as much as with nginx —
  a zrok public share is reachable by anyone with the URL, same as any
  other public tunnel.

## Authentication

The app is protected by a single shared password (session-cookie login, not
HTTP Basic Auth) — every route redirects to `/login` until you sign in.
Configure it with environment variables:

```bash
export APP_PASSWORD=your-password      # default: adas123 - change this
export SECRET_KEY=some-long-random-string  # signs the session cookie
```

Set both in `videoshare.service` (or your shell) before running for real —
the defaults baked into `app.py` are for local testing only. `SECRET_KEY`
in particular must be a real secret in production: anyone who knows it can
forge a valid login session.

This is a single shared password with no per-user accounts or audit trail —
fine for a small trusted team, not a substitute for real access control on
sensitive data. The login page shows a "need access?" contact link; edit
`CONTACT_EMAILS` in `app.py` to change who that points to.

Since the password travels in the login POST body, only run this over
HTTPS (see the nginx + certbot section above) or on a private
network/VPN/SSH tunnel — plain HTTP leaks the password to anyone who can
see the traffic.

## How sharing works

`/compare` reads repeated `?f=foldername` query params, validates each name
resolves to an immediate subfolder of `VIDEO_DIR` (path traversal and nested
folders are blocked), and renders one table column per folder: its videos
(streamed from `/media/<folder>/<filename>`, which supports HTTP Range
requests so scrubbing/seeking works normally) stacked in sorted filename
order, with its stats CSV rendered as a label/value list underneath.

# TODO

- Include tags to filter
    - perception
    - motion-planning
