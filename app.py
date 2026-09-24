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
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

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
# stats.json keys left out of the stats list: shown in the header instead, or
# redundant with the times computed from run_timestamp.
HIDDEN_STATS_KEYS = ("container_success", "run_timestamp_germany", "run_timestamp_vietnam")


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


# Local time zones the run timestamp is shown in, as (label, zone).
TIMEZONES = (("DE", ZoneInfo("Europe/Berlin")), ("VN", ZoneInfo("Asia/Ho_Chi_Minh")))
app.jinja_env.globals["timezones"] = TIMEZONES


def format_times(ts):
    """Render 20260923_122816Z as {'UTC': '2026-09-23 12:28:16', 'DE': '2026-09-23 14:28:16', ...}.

    Keys are 'UTC' plus each TIMEZONES label. If ts doesn't parse, every key gets ts as-is.
    """
    zones = (("UTC", timezone.utc),) + TIMEZONES
    try:
        utc = datetime.strptime(ts, "%Y%m%d_%H%M%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return {label: ts or "" for label, _ in zones}
    return {label: utc.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S") for label, tz in zones}


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
        "times": format_times(meta["run_timestamp"]),
        "short_commit": meta["commit"][:9],
        "videos": list_videos_in(case_path),
        # True/False, or None if the case's stats.json doesn't say.
        "success": stats.get("container_success"),
        "stats": [
            (k, v) for k, v in stats.items()
            if k not in METADATA_KEYS and k not in HIDDEN_STATS_KEYS
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


# Metadata keys cases can be grouped by for a group comparison, with their labels.
GROUP_KEYS = {"build_id": "Build", "commit": "Commit"}


def summarize(cases):
    """Count how many of cases succeeded: {'ok': .., 'total': .., 'unknown': ..}."""
    return {
        "ok": sum(c["success"] is True for c in cases),
        "total": len(cases),
        "unknown": sum(c["success"] is None for c in cases),
    }


def stats_summary(cases):
    """Mean and sample std of each numeric stats key across cases: {key: {'mean', 'std', 'n'}}.

    Booleans and non-numeric values are ignored; std is None with fewer than two values.
    """
    values = {}
    for c in cases:
        for k, v in c["stats"]:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                values.setdefault(k, []).append(v)
    return {
        k: {
            "mean": statistics.fmean(vs),
            "std": statistics.stdev(vs) if len(vs) > 1 else None,
            "n": len(vs),
        }
        for k, vs in values.items()
    }


def group_cases(cases, key):
    """Group cases (as returned by list_cases()) by meta[key], newest group first."""
    groups = {}
    for c in cases:
        groups.setdefault(c["meta"][key], []).append(c)
    return [
        {
            "value": value,
            "label": (value[:9] if key == "commit" else value) or "(none)",
            "cases": members,
            "runs": sorted({c["run"] for c in members}, reverse=True),
            "builds": sorted({c["meta"]["build_id"] for c in members}),
            "commits": sorted({c["short_commit"] for c in members}),
            # members keep list_cases() order, so the first one is the newest.
            "times": members[0]["times"],
            "summary": summarize(members),
        }
        for value, members in groups.items()
    ]


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
    groups = {key: group_cases(cases, key) for key in GROUP_KEYS}
    return render_template(
        "index.html", cases=cases, groups=groups, group_keys=GROUP_KEYS, video_dir=str(VIDEO_DIR)
    )


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
    # One stats row per key, in first-seen order across cases, so the labels
    # can be shown once on the left; cases missing a key get a blank cell.
    stat_keys = list(dict.fromkeys(k for c in cases for k, _ in c["stats"]))
    for c in cases:
        c["stats_by_key"] = dict(c["stats"])
    share_url = request.url
    return render_template(
        "compare.html",
        cases=cases,
        max_videos=range(max_videos),
        stat_keys=stat_keys,
        has_success=any(c["success"] is not None for c in cases),
        share_url=share_url,
    )


@app.route("/compare/group")
@login_required
def compare_group():
    key = request.args.get("by", "")
    if key not in GROUP_KEYS:
        abort(404, description="Unknown grouping.")
    all_groups = {g["value"]: g for g in group_cases(list_cases(), key)}
    # Unknown values are skipped, like bad entries on /compare.
    groups = [all_groups[v] for v in dict.fromkeys(request.args.getlist("g")) if v in all_groups]
    if not groups:
        abort(404, description=f"No valid {GROUP_KEYS[key].lower()}s selected.")

    for g in groups:
        g["stats_summary"] = stats_summary(g["cases"])
    # One mean/std row per numeric stats key, in first-seen order across groups.
    stat_keys = list(dict.fromkeys(k for g in groups for k in g["stats_summary"]))

    # One row per case folder name (<scenario>_<car type>_<dataset>), so the
    # same test case lines up across groups; each cell holds that group's runs of it.
    names = sorted({c["case"] for g in groups for c in g["cases"]}, key=str.lower)
    rows = []
    for name in names:
        cells = [[c for c in g["cases"] if c["case"] == name] for g in groups]
        members = [c for cell in cells for c in cell]
        rows.append({"name": name, "meta": members[0]["meta"], "cells": cells,
                     "ids": [c["id"] for c in members]})
    return render_template(
        "compare_group.html", key=key, key_label=GROUP_KEYS[key],
        groups=groups, rows=rows, stat_keys=stat_keys, share_url=request.url,
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
