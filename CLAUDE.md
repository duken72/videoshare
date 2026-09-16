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

Configure via env vars (see top of `app.py`): `VIDEO_DIR` (default `./videos`),
`HOST` (default `0.0.0.0`), `PORT` (default `5000`).

There are no automated tests, linter, or build tooling in this repo.

## Architecture

The data model is folder-based: each **immediate subfolder** of `VIDEO_DIR`
is one selectable "run," expected to contain one or more videos plus an
optional stats `.csv` (two columns: label, value). Everything server-side
lives in `app.py` (three routes):

- `GET /` (`index`) — lists immediate subfolders of `VIDEO_DIR` that contain
  at least one video via `list_folders()`, renders the checkbox picker
  (`templates/index.html`).
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

**No authentication.** Anyone with a `/compare` link (or who guesses
folder/file names) can view videos and stats. The intended deployment model
(per README) is a private network, VPN/Tailscale, an SSH tunnel, or nginx
`auth_basic` in front — not adding auth to the app itself.

## Deployment shape

Meant to run behind gunicorn + systemd (`videoshare.service` is the unit
template) with nginx optionally reverse-proxying for TLS/port 80. Gunicorn
binds to `127.0.0.1` only; nginx is what exposes it publicly. See
`README.md` for the full nginx config and systemd setup.
