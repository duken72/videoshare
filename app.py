#!/usr/bin/env python3

# Author: Huu Duc Nguyen

"""
videoshare - a tiny web app to pick run folders on your server and share a
link that compares them side by side: each folder is a column, with its
videos stacked on top and its stats.csv rendered below.

Configure with environment variables (or just edit the defaults below):
    VIDEO_DIR   - absolute path to the folder containing your run folders (default: ./videos)
    HOST        - interface to bind to (default: 0.0.0.0)
    PORT        - port to listen on (default: 5000)

Run directly for local testing:
    python3 app.py

Run in production with gunicorn (see README.md):
    gunicorn -w 2 -b 0.0.0.0:5000 app:app
"""

import csv
import os
from pathlib import Path

from flask import Flask, abort, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

VIDEO_DIR = Path(os.environ.get("VIDEO_DIR", Path(__file__).parent / "videos")).resolve()
ALLOWED_EXTENSIONS = {".mp4", ".webm", ".ogg", ".mov", ".m4v", ".mkv"}

app = Flask(__name__)


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


def csv_in(folder):
    """Return the first .csv file found directly inside folder, if any."""
    if not folder.is_dir():
        return None
    matches = sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".csv"),
        key=lambda p: p.name.lower(),
    )
    return matches[0] if matches else None


def read_stats(csv_path):
    """Read a folder's stats CSV as an ordered list of (label, value) pairs."""
    if csv_path is None:
        return []
    stats = []
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if not row or not row[0].strip():
                continue
            label = row[0].strip()
            value = row[1].strip() if len(row) > 1 else ""
            stats.append((label, value))
    return stats


def list_folders():
    """Return a sorted list of immediate subfolders of VIDEO_DIR that contain videos."""
    if not VIDEO_DIR.is_dir():
        return []
    folders = [
        p.name
        for p in VIDEO_DIR.iterdir()
        if p.is_dir() and list_videos_in(p)
    ]
    return sorted(folders, key=str.lower)


def safe_folder_for(name):
    """Resolve a requested folder name to a path guaranteed to be a direct child of VIDEO_DIR."""
    folder_name = secure_filename(name)
    if not folder_name:
        abort(404)
    candidate = (VIDEO_DIR / folder_name).resolve()
    if candidate.parent != VIDEO_DIR:
        abort(404)
    if not candidate.is_dir():
        abort(404)
    return candidate


def safe_path_for(folder, filename):
    """Resolve a requested filename to a path guaranteed to be a direct child of folder."""
    name = secure_filename(filename)
    if not name:
        abort(404)
    candidate = (folder / name).resolve()
    if candidate.parent != folder:
        abort(404)
    if not candidate.is_file():
        abort(404)
    return candidate


@app.route("/")
def index():
    folders = list_folders()
    return render_template("index.html", folders=folders, video_dir=str(VIDEO_DIR))


@app.route("/compare")
def compare():
    requested = request.args.getlist("f")
    folders = []
    for name in requested:
        # Validate each requested folder actually exists and has videos, but
        # don't 404 the whole page for one bad entry - just skip it.
        try:
            folder_path = safe_folder_for(name)
        except Exception:
            continue
        videos = list_videos_in(folder_path)
        if not videos:
            continue
        folders.append({
            "name": folder_path.name,
            "videos": videos,
            "stats": read_stats(csv_in(folder_path)),
        })

    if not folders:
        abort(404, description="No valid folders selected.")

    max_videos = max(len(f["videos"]) for f in folders)
    share_url = request.url
    return render_template(
        "compare.html", folders=folders, max_videos=range(max_videos), share_url=share_url
    )


@app.route("/media/<folder>/<path:filename>")
def media(folder, filename):
    folder_path = safe_folder_for(folder)
    path = safe_path_for(folder_path, filename)
    # send_from_directory / Werkzeug's send_file supports HTTP Range requests
    # natively, so seeking/scrubbing in the <video> element works correctly.
    return send_from_directory(folder_path, path.name, conditional=True)


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    print(f"Serving videos from: {VIDEO_DIR}")
    if not VIDEO_DIR.is_dir():
        print(f"WARNING: {VIDEO_DIR} does not exist yet - create it or set VIDEO_DIR.")
    app.run(host=host, port=port, debug=False)
