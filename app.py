#!/usr/bin/env python3

# Author: Huu Duc Nguyen

"""
videoshare - a tiny web app to pick CI test cases on your server and share a
link that compares them side by side: each case is a column, with its
videos stacked on top and its stats.json rendered below.

Data layout under VIDEO_DIR:
    <UTC timestamp>_<build ID>_<commit hash>/     one CI run, e.g. 20260923_122816Z_LOCAL_01c35f89e
        <scenario>_<car type>_<dataset>/          one test case, e.g. sim_withCtl_EU-VF6-03_sim
            *.mp4 ...                             its videos
            stats.json                            metadata + stats

Configure with environment variables (or just edit the defaults below):
    VIDEO_DIR     - absolute path to the folder containing the CI run folders (default: ~/ci-results)
    HOST          - interface to bind to (default: 0.0.0.0)
    PORT          - port to listen on (default: 5000)
    APP_PASSWORD  - shared password required to log in (default: adas123 - override in production)
    SECRET_KEY    - key used to sign the login session cookie (set a real one in production)

Run directly for local testing:
    python3 app.py

Run in production with gunicorn (see README.md):
    gunicorn -w 2 -b 0.0.0.0:5000 app:app
"""

import functools
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from flask import (
    Flask,
    abort,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

VIDEO_DIR = Path(os.environ.get("VIDEO_DIR", Path.home() / "ci-results")).resolve()
ALLOWED_EXTENSIONS = {".mp4", ".webm", ".ogg", ".mov", ".m4v", ".mkv"}
APP_PASSWORD = os.environ.get("APP_PASSWORD", "adas123")
CONTACT_EMAILS = ["huuduc.nguyen@vinfastauto.com", "huu.lee@vinfastauto.com"]

app = Flask(__name__)
# NOTE: the fallback below only keeps sessions valid across a single gunicorn
# worker set between restarts. Set a real SECRET_KEY in production so logins
# survive redeploys and are consistent across all workers.
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me-in-production")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapped


def list_videos_in(folder):
    """Return a sorted list of video filenames found directly inside folder."""
    if not folder.is_dir():
        return []
    files = [
        p.name
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS
    ]
    return sorted(files, key=str.lower)


STATS_FILE = "stats.json"
# stats.json keys shown as the case's header rather than in its stats list.
METADATA_KEYS = ("run_timestamp", "build_id", "commit", "scenario", "car_type", "dataset")


def read_stats(folder):
    """Read a case's stats.json as a dict ({} if missing or unreadable)."""
    path = folder / STATS_FILE
    if not path.is_file():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def parse_run_name(name):
    """Split a run folder name <YYYYMMDD>_<HHMMSS>Z_<build ID>_<commit> into its parts.

    Used as a fallback when a case has no stats.json. Returns {} if the name
    doesn't follow the scheme.
    """
    parts = name.split("_")
    if len(parts) < 4:
        return {}
    return {
        "run_timestamp": f"{parts[0]}_{parts[1]}",
        "build_id": "_".join(parts[2:-1]),
        "commit": parts[-1],
    }


def format_timestamp(ts):
    """Render 20260923_122816Z as '2026-09-23 12:28:16 UTC' (or return ts as-is)."""
    try:
        return datetime.strptime(ts, "%Y%m%d_%H%M%SZ").strftime("%Y-%m-%d %H:%M:%S UTC")
    except (TypeError, ValueError):
        return ts or ""


def case_info(run_path, case_path):
    """Gather everything the templates need to show one test case."""
    stats = read_stats(case_path)
    meta = {**parse_run_name(run_path.name), **{k: stats[k] for k in METADATA_KEYS if k in stats}}
    meta = {k: "" if meta.get(k) is None else str(meta.get(k, "")) for k in METADATA_KEYS}
    return {
        "id": f"{run_path.name}/{case_path.name}",
        "run": run_path.name,
        "case": case_path.name,
        "meta": meta,
        "time": format_timestamp(meta["run_timestamp"]),
        "short_commit": meta["commit"][:9],
        "videos": list_videos_in(case_path),
        # True/False, or None if the case's stats.json doesn't say.
        "success": stats.get("container_success"),
        "stats": [
            (k, v) for k, v in stats.items()
            if k not in METADATA_KEYS and k != "container_success"
        ],
    }


def is_case(folder):
    return folder.is_dir() and ((folder / STATS_FILE).is_file() or bool(list_videos_in(folder)))


def list_cases():
    """Return every test case (<run>/<case> folder with videos or a stats.json), newest run first."""
    if not VIDEO_DIR.is_dir():
        return []
    cases = []
    for run_path in VIDEO_DIR.iterdir():
        if not run_path.is_dir():
            continue
        for case_path in run_path.iterdir():
            if is_case(case_path):
                cases.append(case_info(run_path, case_path))
    cases.sort(key=lambda c: c["case"].lower())
    cases.sort(key=lambda c: (c["meta"]["run_timestamp"], c["run"]), reverse=True)
    return cases


def safe_child(parent, name, want_dir):
    """Resolve name to a path guaranteed to be a direct child of parent (dir or file)."""
    child_name = secure_filename(name)
    if not child_name:
        abort(404)
    candidate = (parent / child_name).resolve()
    if candidate.parent != parent:
        abort(404)
    if not (candidate.is_dir() if want_dir else candidate.is_file()):
        abort(404)
    return candidate


def safe_case_for(run, case):
    """Resolve <run>/<case> to a path guaranteed to be exactly VIDEO_DIR/<run>/<case>."""
    run_path = safe_child(VIDEO_DIR, run, want_dir=True)
    return run_path, safe_child(run_path, case, want_dir=True)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password", "") == APP_PASSWORD:
            session.clear()
            session["authenticated"] = True
            session.permanent = True
            next_url = request.args.get("next")
            if not next_url or not next_url.startswith("/") or next_url.startswith("//"):
                next_url = url_for("index")
            return redirect(next_url)
        error = "Wrong password."
    return render_template("login.html", error=error, contact_emails=CONTACT_EMAILS)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    cases = list_cases()
    return render_template("index.html", cases=cases, video_dir=str(VIDEO_DIR))


@app.route("/compare")
@login_required
def compare():
    cases = []
    for case_id in request.args.getlist("f"):
        # Validate each requested <run>/<case> actually exists, but don't 404
        # the whole page for one bad entry - just skip it.
        run, _, case = case_id.partition("/")
        try:
            run_path, case_path = safe_case_for(run, case)
        except Exception:
            continue
        if is_case(case_path):
            cases.append(case_info(run_path, case_path))

    if not cases:
        abort(404, description="No valid test cases selected.")

    max_videos = max(len(c["videos"]) for c in cases)
    share_url = request.url
    return render_template(
        "compare.html", cases=cases, max_videos=range(max_videos), share_url=share_url
    )


@app.route("/media/<run>/<case>/<path:filename>")
@login_required
def media(run, case, filename):
    _, case_path = safe_case_for(run, case)
    path = safe_child(case_path, filename, want_dir=False)
    # send_from_directory / Werkzeug's send_file supports HTTP Range requests
    # natively, so seeking/scrubbing in the <video> element works correctly.
    return send_from_directory(case_path, path.name, conditional=True)


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    print(f"Serving videos from: {VIDEO_DIR}")
    if not VIDEO_DIR.is_dir():
        print(f"WARNING: {VIDEO_DIR} does not exist yet - create it or set VIDEO_DIR.")
    app.run(host=host, port=port, debug=False)
