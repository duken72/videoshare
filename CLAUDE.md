# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A tiny single-file Flask app: pick run folders from a folder on the server,
hit **Compare**, and get a shareable link that lays them out side by side —
one table column per folder, its videos stacked on top (synced
play/pause/restart, best-effort synced scrubbing) and its stats CSV
rendered as a label/value list below. No database, no build step, no
frontend framework — server-rendered Jinja templates plus vanilla JS.

## Commands

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run locally (dev server, debug off)
python3 app.py

# Run like production
gunicorn -w 2 -b 0.0.0.0:5000 app:app
```

Configure via env vars (see top of `app.py`): `VIDEO_DIR` (default `~/data`),
`HOST` (default `0.0.0.0`), `PORT` (default `5000`), `APP_PASSWORD` (default
`adas123` — the login password), `SECRET_KEY` (session-cookie signing key).

There are no automated tests, linter, or build tooling in this repo.

## Architecture

The data model is folder-based: each **immediate subfolder** of `VIDEO_DIR`
is one selectable "run," expected to contain one or more videos plus an
optional stats `.csv` (two columns: label, value). Everything server-side
lives in `app.py`. Every route except `/login` is wrapped in
`@login_required`, which checks `session["authenticated"]` (set by
`/login` after checking `request.form["password"]` against `APP_PASSWORD`)
and redirects to `/login?next=<original path>` otherwise; `next` is
validated to be a same-site relative path to avoid becoming an open
redirect. Routes:

- `GET/POST /login` (`login`) — renders the password form
  (`templates/login.html`, which also shows `CONTACT_EMAILS` as a "need
  access?" link) and, on a correct password, sets the session cookie and
  redirects to `next` (or `/`).
- `POST /logout` (`logout`) — clears the session.
- `GET /` (`index`) — lists immediate subfolders of `VIDEO_DIR` that contain
  at least one video via `list_folders()`, renders the picker
  (`templates/index.html`): a native `<select multiple>` (scales to many
  folders better than a checkbox list) with a JS-driven text filter above it
  that hides non-matching `<option>`s client-side.
- `GET /compare?f=<folder>&f=<folder>...` (`compare`) — takes repeated `f`
  query params, silently drops any that don't resolve to a real folder with
  videos (per-entry, not a hard 404), and for each surviving folder gathers
  its videos (`list_videos_in()`, sorted filename order) and stats
  (`read_stats(csv_in(folder))`). Renders `templates/compare.html` as a
  table: one column per folder, one row per video index (videos align
  across folders by sorted-filename position, not by name — folders with
  fewer videos just get blank cells at the bottom), plus a final stats row.
  The full request URL is the shareable link — state lives entirely in the
  query string, not a database.
- `GET /media/<folder>/<filename>` (`media`) — streams the actual video via
  `send_from_directory(..., conditional=True)`, which is what makes HTTP
  Range requests (scrubbing/seeking) work.

**Path safety**: `safe_folder_for()` and `safe_path_for()` are the
chokepoints all filesystem access goes through — both run
`secure_filename()` then require the resolved path's *immediate* parent to
be `VIDEO_DIR` (for folders) or the folder itself (for files) before
returning it. This blocks both path traversal and picking a nested/grandchild
folder as if it were a top-level run. `/compare` and `/media` both depend on
this; don't bypass it when adding new routes that touch `VIDEO_DIR`.

**Sync behavior is client-side only** (in `templates/compare.html`): the
toolbar buttons iterate all `video.synced` elements directly, and a
`seeked` listener on each video nudges the others to match (within a 0.2s
tolerance) when one is scrubbed. There's no server coordination — each
browser tab syncs its own set of `<video>` elements independently.

**Authentication is a single shared password**, not per-user accounts — see
`login_required`/`APP_PASSWORD`/`SECRET_KEY` above. There's no rate
limiting or lockout on `/login`, and the session cookie's security depends
entirely on `SECRET_KEY` being a real secret in production (the fallback in
`app.py` is dev-only) and on the app being served over HTTPS or a private
network (per README) so the password isn't sent in the clear.

## Deployment shape

Meant to run behind gunicorn + systemd (`videoshare.service` is the unit
template) with nginx optionally reverse-proxying for TLS/port 80. Gunicorn
binds to `127.0.0.1` only; nginx is what exposes it publicly. See
`README.md` for the full nginx config and systemd setup.
