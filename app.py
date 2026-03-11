import atexit
import os
import csv
import io
import sqlite3
import argparse
import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    send_file,
    session,
    Response,
    abort,
)

# -------------
# CONFIGURATION
# -------------

VIDEO_BASE_PATH = "/"
CLIPS_PER_PAGE = 6
ALLOWED_CSV_DIR = os.environ.get("CLIPVIEWER_CSV_DIR", os.getcwd())

_REAL_VIDEO_BASE = os.path.realpath(VIDEO_BASE_PATH)
_REAL_CSV_DIR = os.path.realpath(ALLOWED_CSV_DIR)

# Temp directory for converted MP4 files (for cross-browser compatibility)
_tmpdir = tempfile.mkdtemp(prefix="clipviewer_")
atexit.register(shutil.rmtree, _tmpdir, ignore_errors=True)

# -----------------------------
# DO NOT MODIFY BELOW THIS LINE
# -----------------------------


app = Flask(__name__)
app.secret_key = os.environ.get("CLIPVIEWER_SECRET_KEY", os.urandom(24))


def is_path_within(path: str, allowed_dir: str) -> bool:
    real_path = os.path.realpath(path)
    return real_path.startswith(allowed_dir + os.sep) or real_path == allowed_dir


def get_db_path(csv_path: str) -> str:
    base, _ = os.path.splitext(csv_path)
    return f"{base}_clipviewer.db"


def get_db() -> sqlite3.Connection:
    """Open a DB connection from the session, or abort 400 if none loaded."""
    db_path = session.get("db_path")
    if not db_path or not os.path.isfile(db_path):
        abort(400, description="No CSV loaded. Please load a CSV first.")
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


@app.errorhandler(400)
def bad_request(e):
    return jsonify({"status": "error", "message": e.description}), 400


@app.route("/")
def index():
    return render_template("index.jinja2")


@app.route("/load_csv", methods=["POST"])
def load_csv():
    csv_path = str(request.json["csv_path"])
    metadata_fields = [
        m.strip() for m in str(request.json["metadata_fields"]).split(",") if m.strip()
    ]

    if not is_path_within(csv_path, _REAL_CSV_DIR):
        return jsonify(
            {"status": "error", "message": "CSV path not in allowed directory"}
        ), 403

    try:
        # Read CSV
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            rows = list(reader)

        # Validate columns
        required = set(metadata_fields + ["avi_path"])
        missing = required - set(fieldnames)
        if missing:
            raise ValueError(f"CSV is missing columns: {', '.join(missing)}")

        # Filter rows with avi_path
        rows = [r for r in rows if r.get("avi_path")]

        # Check video files (first 100)
        for row in rows[:100]:
            video_path = os.path.join(VIDEO_BASE_PATH, row["avi_path"])
            if not os.path.isfile(video_path):
                raise FileNotFoundError(f"Video file not found: {video_path}")

        # Build clip tuples with pre-formatted metadata
        clip_rows = []
        for row in rows:
            filename = row["avi_path"].split("/")[-1]
            metadata = (
                ", ".join(f"{m}: {row.get(m, '')}" for m in metadata_fields)
                if metadata_fields
                else ""
            )
            clip_rows.append((row["avi_path"], filename, metadata))

        # Create/open database and import
        db_path = get_db_path(csv_path)
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS clips (
                    id INTEGER PRIMARY KEY,
                    avi_path TEXT NOT NULL,
                    filename TEXT NOT NULL UNIQUE,
                    metadata TEXT NOT NULL DEFAULT '',
                    comment TEXT NOT NULL DEFAULT ''
                )
            """)

            # Upsert: update avi_path and metadata, preserve existing comments
            conn.executemany(
                """INSERT INTO clips (avi_path, filename, metadata)
                   VALUES (?, ?, ?)
                   ON CONFLICT(filename) DO UPDATE SET
                       avi_path = excluded.avi_path,
                       metadata = excluded.metadata""",
                clip_rows,
            )

            # Migrate existing _comments.csv if present
            base, ext = os.path.splitext(csv_path)
            comments_csv_path = f"{base}_comments{ext}"
            if os.path.isfile(comments_csv_path):
                with open(comments_csv_path, newline="") as f:
                    comment_reader = csv.DictReader(f)
                    updates = [
                        (crow.get("comments", ""), crow.get("filename", ""))
                        for crow in comment_reader
                        if crow.get("filename") and crow.get("comments")
                    ]
                if updates:
                    conn.executemany(
                        "UPDATE clips SET comment = ? WHERE filename = ?",
                        updates,
                    )

        session["db_path"] = db_path

        return jsonify({"status": "success", "message": "CSV loaded successfully"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route("/get_clips")
def get_clips():
    with get_db() as conn:
        page = int(request.args.get("page", 0))
        offset = page * CLIPS_PER_PAGE

        total = conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
        rows = conn.execute(
            "SELECT avi_path, filename, metadata, comment FROM clips ORDER BY id LIMIT ? OFFSET ?",
            (CLIPS_PER_PAGE, offset),
        ).fetchall()

    clips = [
        {
            "video_path": row["avi_path"],
            "metadata": row["metadata"],
            "clip_reviewed": "reviewed" if row["comment"] else "",
            "comment": row["comment"],
            "filename": row["filename"],
        }
        for row in rows
    ]

    total_pages = max(1, (total - 1) // CLIPS_PER_PAGE + 1)

    return jsonify(
        {
            "clips": clips,
            "total_pages": total_pages,
            "total_clips": total,
            "clips_per_page": CLIPS_PER_PAGE,
        }
    )


@app.route("/save_comments", methods=["POST"])
def save_comments():
    updates = [
        (item["comment"].replace("\n", " ").replace("\r", ""), item["filename"])
        for item in request.json
    ]
    with get_db() as conn:
        conn.executemany(
            "UPDATE clips SET comment = ? WHERE filename = ?",
            updates,
        )

    return jsonify({"status": "success"})


@app.route("/export_comments")
def export_comments():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT filename, comment FROM clips WHERE comment != '' ORDER BY filename"
        ).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["filename", "comments"])
    for row in rows:
        writer.writerow([row["filename"], row["comment"]])

    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=comments.csv"},
    )


def _to_mp4(video_path: str) -> str:
    """Convert video to H.264 MP4 in temp dir for cross-browser playback."""
    src = Path(video_path)
    path_hash = hashlib.md5(str(src).encode()).hexdigest()
    dst = Path(_tmpdir) / f"{src.stem}_{path_hash}.mp4"
    if dst.exists():
        return str(dst)
    tmp_dst = dst.with_suffix(".tmp.mp4")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(tmp_dst),
        ],
        check=True,
        timeout=120,
    )
    os.replace(str(tmp_dst), str(dst))
    return str(dst)


@app.route("/video/<path:filename>")
def serve_video(filename):
    full_path = os.path.realpath(os.path.join(_REAL_VIDEO_BASE, filename))
    if not is_path_within(full_path, _REAL_VIDEO_BASE):
        return "Forbidden", 403
    try:
        mp4_path = _to_mp4(full_path)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return "Video conversion failed", 500
    return send_file(mp4_path, mimetype="video/mp4")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--port",
        type=int,
        default=8888,
        help="Port number to run the server on (default: 8888)",
    )
    args = parser.parse_args()

    debug = os.environ.get("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=args.port, debug=debug)


if __name__ == "__main__":
    main()
