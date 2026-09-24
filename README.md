# videoshare

A tiny `Flask` app allowing to access and compare data of test runs on a
remote server. The data is organised as CI run folders, each containing one
subfolder per test case with its videos and a `stats.json`. Users can pick
test cases to compare. The app shows them side by side — one column per
case, with its metadata as the header, its videos stacked below that, and
its stats at the bottom (with synced play / pause / restart,
and reasonably in-sync scrubbing).

## Table of Contents

<!-- vim-markdown-toc GFM -->

* [Installation](#installation)
    * [Repo Structure](#repo-structure)
    * [Where to place the data](#where-to-place-the-data)
* [Local development setup](#local-development-setup)
* [Allowing public access](#allowing-public-access)
    * [gunicorn (systemd service)](#gunicorn-systemd-service)
    * [zrok](#zrok)
    * [nginx](#nginx)
* [Authentication](#authentication)
* [How sharing works](#how-sharing-works)
* [TODO](#todo)

<!-- vim-markdown-toc -->

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Repo Structure

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

### Where to place the data

By default it looks for a `ci-results/` folder in your home directory
(`~/ci-results`). Point `VIDEO_DIR` elsewhere if the CI results live
somewhere else:

```bash
export VIDEO_DIR=/path/to/ci-results
```

The data is two levels deep: one folder per **CI run**, and inside it one
folder per **test case**. Each test case is one selectable column.

- Run folder: `<UTC timestamp>_<build ID>_<commit hash>`, e.g.
  `20260923_122816Z_LOCAL_01c35f89e`.
- Test case folder: `<scenario>_<car type>_<dataset>`, e.g.
  `sim_withCtl_EU-VF6-03_sim`.

Each test case folder holds:

- zero or more video files (`.mp4 .webm .ogg .mov .m4v .mkv` out of the
  box — edit `ALLOWED_EXTENSIONS` in `app.py` to add more), and
- a `stats.json` with the case's metadata and stats.

```
ci-results/
├── 20260923_122816Z_LOCAL_01c35f89e/
│   └── real_withCtl_EU-VF6-03_<dataset>/
│       ├── vparking_app.mp4
│       └── stats.json
└── 20260923_132430Z_NIGHTLY_ff0921028/
    ├── real_withoutCtl_EU-VF6-03_<dataset>/
    │   ├── vparking_app.mp4
    │   └── stats.json
    └── sim_perpendicularParking_EU-VF6-03_sim/
        ├── vparking_app.mp4
        └── stats.json
```

```json
{
  "build_id": "LOCAL",
  "commit": "01c35f89e15201db0e1a1e0c9bca8d5c61ba55ec",
  "run_timestamp": "20260923_122816Z",
  "scenario": "real_withCtl",
  "car_type": "EU-VF6-03",
  "dataset": "20260906_000000_Log13_..._compressed",
  "container_success": true
}
```

The metadata (timestamp, build, commit, scenario, car type, dataset) is
read from `stats.json` rather than parsed from folder names, because
scenario names contain underscores (`real_withCtl`) and so do dataset
names. If a case has no `stats.json`, the timestamp, build and commit fall
back to what the run folder name gives. The picker shows these as columns
you can filter on. On the compare page, `container_success` is shown as
✓/✗ in the first row of each column's header, above the videos. Every
other key in `stats.json` appears in the stats list under the videos.

A case folder is listed if it has at least one video or a `stats.json`.
This means failed runs with no video can still be compared by their stats.

Videos are matched across cases by sorted filename order (row 1 = each
case's first video alphabetically, and so on). Name videos consistently
across cases so the rows line up meaningfully. Cases can have different
numbers of videos; missing cells are left blank.

## Local development setup

After this setup, the web app is reachable from your public/LAN IP by default.

```bash
python3 app.py
# Serving videos from: /path/to/your/videos
# * Running on http://0.0.0.0:5000
```

Visit `http://YOUR_SERVER_IP:5000` (you may need to open the port: `sudo ufw allow 5000/tcp`).
Tick a few test cases, click **Compare selected**, and you'll land on a URL like:

```
http://YOUR_SERVER_IP:5000/compare?f=<run>/<case>&f=<run>/<case>
```

If you open the service publicly, it would be visible to anyone who opens it, they sees the same comparison using that URL.

## Allowing public access

Don't leave the dev server running long-term. Run `gunicorn` behind `systemd`
first, then pick how to expose it publicly: `zrok` for a quick tunnel with
no server config, or `nginx` for a stable domain/URL with HTTPS.

### gunicorn (systemd service)

Edit `videoshare.service` (set `User`, `WorkingDirectory`, `VIDEO_DIR`), then:

```bash
sudo cp videoshare.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now videoshare
sudo systemctl status videoshare
```

This binds `gunicorn` to `127.0.0.1:5000` — reachable only from the server
itself. That's different from `python3 app.py` above, which listens on
`0.0.0.0` (every interface) and is why it's reachable from your public/LAN
IP by default. Once you switch to the service, the same `http://YOUR_SERVER_IP:5000`
link will stop connecting even though the service is running — that's
expected, not a bug: `gunicorn` is meant to sit behind a tunnel or reverse
proxy rather than face the network directly. Use `zrok` or `nginx` below to
restore public access, or, if you'd rather skip both, change
`-b 127.0.0.1:5000` to `-b 0.0.0.0:5000` in `videoshare.service`'s
`ExecStart` (then `daemon-reload` + `restart`) — but note `APP_PASSWORD`
then travels over plain HTTP, so restrict access with a firewall rule if
the server is internet-facing.

### zrok

If you just want a public link without setting up `nginx`, DNS, or `certbot`,
[`zrok`](https://docs.zrok.io) tunnels a local port out to a public HTTPS URL
for you — no inbound firewall rule needed. Good for a quick share; `nginx`
below is still the better fit for a stable, permanent URL.

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

With `gunicorn` running (from the `systemd` service above, already bound to
`127.0.0.1:5000`) — or the dev server via `HOST=127.0.0.1 python3 app.py`
— run, in another terminal:

```bash
zrok share public http://127.0.0.1:5000
```

This prints a public `https://something.share.zrok.io` URL — that's your
shareable link. `zrok` terminates HTTPS for you, so `APP_PASSWORD` isn't sent
in the clear even though `gunicorn`/`Flask` itself only speaks plain HTTP
locally.

Notes:

- Each `zrok share public` run gets a new random URL by default (the
  session ends when you `Ctrl-C` it) — check `zrok`'s *reserved* shares if
  you want a stable URL that survives restarts.
- Keep `gunicorn`/`Flask` bound to `127.0.0.1`, not `0.0.0.0` — `zrok` reaches it
  locally, so it never needs to be reachable from the network directly, and
  no `ufw allow` rule is needed for this path.
- `APP_PASSWORD`/`SECRET_KEY` still matter exactly as much as with `nginx` —
  a `zrok` public share is reachable by anyone with the URL, same as any
  other public tunnel.

### nginx

`nginx` reverse proxy — gives you port 80/443 and a normal-looking URL
instead of `:5000`, and keeps `gunicorn` off the network directly.

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

Once `nginx` is proxying, visit `http://<server-ip>/` (or your domain) — no
`:5000` needed. You can also remove the `sudo ufw allow 5000/tcp` rule from
the dev-server step above, since `gunicorn` no longer needs to be reachable
from outside the server.

Please note that, this allows access from within your local network, not the
WWW. To share access globally, extra configurations are needed on how your
local network is exposed to global network.

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
HTTPS (see the `nginx` or `zrok` subsections above) or on a private
network/VPN/SSH tunnel — plain HTTP leaks the password to anyone who can
see the traffic.

## How sharing works

`/compare` reads repeated `?f=<run>/<case>` query params. It checks that
each one resolves to exactly `VIDEO_DIR/<run>/<case>` (path traversal and
other nesting are blocked) and renders one table column per case. The
column header shows the case's metadata. Below it are the case's videos in
sorted filename order, streamed from `/media/<run>/<case>/<filename>`,
which supports HTTP Range requests so scrubbing and seeking work normally.
At the bottom, the rest of `stats.json` is shown as a label/value list.

## TODO

- Include tags to filter
    - perception
    - motion-planning
