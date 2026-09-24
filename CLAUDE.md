# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working
with code in this repository.

## What this is

A tiny single-file Flask app: pick CI test cases from a folder on the
server, hit **Compare**, and get a shareable link that lays them out side
by side — one table column per case, its metadata as the header, its videos
stacked below (synced play/pause/restart, best-effort synced scrubbing) and
its `stats.json` rendered as a label/value list at the bottom. No database, no build step, no
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

Configure via env vars (see top of `app.py`): `VIDEO_DIR` (default `~/ci-results`),
`HOST` (default `0.0.0.0`), `PORT` (default `5000`), `APP_PASSWORD` (default
`adas123` — the login password), `SECRET_KEY` (session-cookie signing key).

There are no automated tests, linter, or build tooling in this repo.

## Architecture

The data model is two levels of folders:
`VIDEO_DIR/<run>/<case>/`. A **run** folder is named
`<UTC timestamp>_<build ID>_<commit>` (e.g. `20260923_122816Z_LOCAL_01c35f89e`).
A **case** folder inside it is named `<scenario>_<car type>_<dataset>` (e.g.
`sim_withCtl_EU-VF6-03_sim`). Each case folder holds zero or more videos
plus a `stats.json`. Cases, not runs, are the selectable unit, identified
as `"<run>/<case>"`. Scenario and dataset names contain underscores, so
the metadata (`METADATA_KEYS`: run_timestamp, build_id, commit, scenario,
car_type, dataset) comes from `stats.json`. `parse_run_name()` is only a
fallback for the run-level fields when `stats.json` is missing.
`case_info()` builds the dict the templates use: id, meta, `times` (the
UTC run timestamp, plus it converted to each zone in `TIMEZONES`: DE =
Europe/Berlin, VN = Asia/Ho_Chi_Minh), short commit, videos, and `stats`,
which holds the `stats.json` keys that aren't metadata or in
`HIDDEN_STATS_KEYS`. On the compare page the first metadata row is Time,
listing the UTC, DE and VN times on aligned lines. `container_success`
is pulled out as `success` and shown right after it. A case is listed (`is_case()`)
if it has a video *or* a `stats.json`, so failed runs with no video still
show up.

Everything server-side lives in `app.py`. Every route except `/login` is
wrapped in `@login_required`, which checks `session["authenticated"]` (set
by `/login` after checking `request.form["password"]` against
`APP_PASSWORD`) and redirects to `/login?next=<original path>` otherwise;
`next` is validated to be a same-site relative path to avoid becoming an
open redirect. Routes:

- `GET/POST /login` (`login`) — renders the password form
  (`templates/login.html`, which also shows `CONTACT_EMAILS` as a "need
  access?" link) and, on a correct password, sets the session cookie and
  redirects to `next` (or `/`).
- `POST /logout` (`logout`) — clears the session.
- `GET /` (`index`) — lists every case via `list_cases()`, newest run
  first, and renders the picker (`templates/index.html`). The picker is a
  table with one checkbox row per case and columns for time (DE), time (VN),
  build, commit, scenario, car type, dataset and video count. Above it are a free
  text filter and dropdown filters for build, scenario, car type and
  dataset. All filtering happens client-side by hiding rows. Tabs above
  the filters switch to a **Builds** or **Commits** table (one checkbox row
  per `group_cases()` group, with its CI-run count and successful/total
  runs); those submit to `/compare/group`. The dropdowns only apply to the
  case table; the text filter applies to all three.
- `GET /compare?f=<run>/<case>&f=...` (`compare`) — takes repeated `f`
  query params and silently drops any that don't resolve to a real case
  (per entry, not a hard 404). Renders `templates/compare.html` as a table
  with a sticky label column on the left (row names appear only once) and
  one column per case. The header is just the case title. Below it are
  one row per metadata field, then one row per video index, then one row
  per stats key (the union of keys across cases, in first-seen order;
  cases missing a key get a blank cell). Videos align across cases by
  sorted-filename position, not by name, and cases with fewer videos get
  blank cells. The full request URL is the
  shareable link — state lives entirely in the query string, not a
  database.
- `GET /compare/group?by=build_id|commit&g=<value>&g=...` (`compare_group`)
  — compares whole builds or commits (`GROUP_KEYS`), each spanning many
  cases/runs. Renders `templates/compare_group.html` with the same
  left-hand label column as `/compare` and one column per group: rows
  for "successful / total runs" (`summarize()`: a run is one
  case, success is `container_success`; missing counts as unknown, not
  successful), commits/builds, CI runs and latest time, then one row per
  case folder name so the same test case
  lines up across groups. Cells list that group's runs of the case with a
  link to `/compare`; each row links to `/compare` with all its runs.
  Unknown `g` values are skipped. No videos are embedded on this page.
- `GET /media/<run>/<case>/<filename>` (`media`) — streams the actual video via
  `send_from_directory(..., conditional=True)`, which is what makes HTTP
  Range requests (scrubbing/seeking) work.

**Path safety**: `safe_child()` is the chokepoint all filesystem access
goes through. It runs `secure_filename()`, then requires the resolved
path's *immediate* parent to be the expected parent directory.
`safe_case_for(run, case)` applies it twice (`VIDEO_DIR` → run → case), and
`/media` applies it once more for the file. This blocks path traversal
and any other nesting depth. `/compare` and `/media` both depend on this;
don't bypass it when adding new routes that touch `VIDEO_DIR`.

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

## Git workflow

Work directly on the current branch in the main checkout — no need to
create a worktree or a new branch. Do **not** commit or push unless
explicitly asked to; leave changes uncommitted for review.

Multiple sessions/conversations may be working on the same branch and
checkout at the same time. Expect files to change underneath you: re-read
a file before editing it, treat unfamiliar uncommitted changes as another
session's work (don't revert or overwrite them), and when asked to commit,
stage only the changes you made.
