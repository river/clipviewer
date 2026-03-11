import atexit
import csv
import hashlib
import io
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
from pathlib import Path

import typer
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

CLIPS_PER_PAGE = 6

VIDEO_BASE = os.path.realpath("/")
CSV_DIR = os.path.realpath(os.getcwd())

# Temp directory for converted MP4 files (for cross-browser compatibility)
TMPDIR = tempfile.mkdtemp(prefix="clipviewer_")
atexit.register(shutil.rmtree, TMPDIR, ignore_errors=True)

# -----------------------------
# DO NOT MODIFY BELOW THIS LINE
# -----------------------------


app = Flask(__name__)
app.secret_key = os.urandom(24)


def is_path_within(path: str, allowed_dir: str) -> bool:
    """Check if path is within allowed_dir. Callers must pass an already-resolved allowed_dir."""
    return Path(path).resolve().is_relative_to(allowed_dir)


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

    if not is_path_within(csv_path, CSV_DIR):
        return jsonify(
            {"status": "error", "message": "CSV path not in allowed directory"}
        ), 403

    # Skip re-processing if DB is already up-to-date
    db_path = get_db_path(csv_path)
    try:
        if os.path.isfile(db_path) and os.path.getmtime(db_path) >= os.path.getmtime(csv_path):
            session["db_path"] = db_path
            return jsonify({"status": "success", "message": "CSV loaded successfully"})
    except OSError:
        pass

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
            video_path = os.path.join(VIDEO_BASE, row["avi_path"])
            if not os.path.isfile(video_path):
                raise FileNotFoundError(f"Video file not found: {video_path}")

        # Build clip tuples with pre-formatted metadata
        clip_rows = []
        for row in rows:
            metadata = (
                ", ".join(f"{m}: {row.get(m, '')}" for m in metadata_fields)
                if metadata_fields
                else ""
            )
            clip_rows.append((row["avi_path"], metadata))

        # Create/open database and import
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS clips (
                    id INTEGER PRIMARY KEY,
                    avi_path TEXT NOT NULL UNIQUE,
                    metadata TEXT NOT NULL DEFAULT '',
                    comment TEXT NOT NULL DEFAULT '',
                    reviewed_at TEXT DEFAULT NULL
                )
            """)

            # Upsert: update metadata, preserve existing comments
            conn.executemany(
                """INSERT INTO clips (avi_path, metadata)
                   VALUES (?, ?)
                   ON CONFLICT(avi_path) DO UPDATE SET
                       metadata = excluded.metadata""",
                clip_rows,
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
            "SELECT avi_path, metadata, comment, reviewed_at FROM clips ORDER BY id LIMIT ? OFFSET ?",
            (CLIPS_PER_PAGE, offset),
        ).fetchall()

    clips = [
        {
            "metadata": row["metadata"],
            "clip_reviewed": "reviewed" if row["reviewed_at"] else "",
            "comment": row["comment"],
            "avi_path": row["avi_path"],
            "reviewed_at": row["reviewed_at"] or "",
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


@app.route("/mark_reviewed", methods=["POST"])
def mark_reviewed():
    avi_paths = request.json
    if not isinstance(avi_paths, list) or not avi_paths:
        return jsonify({"status": "success"})
    avi_paths = [str(p) for p in avi_paths]
    placeholders = ",".join("?" * len(avi_paths))
    with get_db() as conn:
        conn.execute(
            f"UPDATE clips SET reviewed_at = COALESCE(reviewed_at, datetime('now')) WHERE avi_path IN ({placeholders})",
            avi_paths,
        )
    return jsonify({"status": "success"})


@app.route("/save_comments", methods=["POST"])
def save_comments():
    updates = [
        (item["comment"].replace("\n", " ").replace("\r", ""), item["avi_path"])
        for item in request.json
    ]
    with get_db() as conn:
        conn.executemany(
            "UPDATE clips SET comment = ? WHERE avi_path = ?",
            updates,
        )

    return jsonify({"status": "success", "db_path": session["db_path"]})


@app.route("/export_comments")
def export_comments():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT avi_path, comment, reviewed_at FROM clips WHERE reviewed_at IS NOT NULL ORDER BY avi_path"
        ).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["avi_path", "comments", "reviewed_at"])
    for row in rows:
        writer.writerow([row["avi_path"], row["comment"], row["reviewed_at"] or ""])

    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=comments.csv"},
    )


_convert_locks: dict[str, threading.Lock] = {}
_convert_locks_guard = threading.Lock()


def _is_browser_compatible(path: str) -> bool:
    """Check if video is already H.264/yuv420p MP4 (playable in all browsers)."""
    if not path.lower().endswith(".mp4"):
        return False
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name,pix_fmt",
                "-of", "csv=p=0",
                path,
            ],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() == "h264,yuv420p"
    except Exception:
        return False


def _to_mp4(video_path: str) -> str:
    """Convert video to H.264 MP4 in temp dir for cross-browser playback."""
    if _is_browser_compatible(video_path):
        return video_path

    stem = os.path.splitext(os.path.basename(video_path))[0]
    path_hash = hashlib.md5(video_path.encode()).hexdigest()
    dst = os.path.join(TMPDIR, f"{stem}_{path_hash}.mp4")

    # Per-path lock prevents duplicate concurrent ffmpeg conversions
    with _convert_locks_guard:
        lock = _convert_locks.setdefault(path_hash, threading.Lock())

    with lock:
        # Serve cached file if it exists and source hasn't changed
        if os.path.isfile(dst):
            if os.path.getmtime(dst) >= os.path.getmtime(video_path):
                return dst

        tmp_fd, tmp_dst = tempfile.mkstemp(suffix=".mp4", dir=TMPDIR)
        os.close(tmp_fd)
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    video_path,
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-pix_fmt",
                    "yuv420p",
                    "-an",
                    tmp_dst,
                ],
                check=True,
                timeout=120,
            )
            os.replace(tmp_dst, dst)
        except BaseException:
            os.unlink(tmp_dst)
            raise

    return dst


@app.route("/video/<path:filename>")
def serve_video(filename):
    full_path = os.path.realpath(os.path.join(VIDEO_BASE, filename))
    if not is_path_within(full_path, VIDEO_BASE):
        return "Forbidden", 403
    try:
        mp4_path = _to_mp4(full_path)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return "Video conversion failed", 500
    return send_file(mp4_path, mimetype="video/mp4")


def main(
    port: int = typer.Option(8888, help="Port number to run the server on."),
    csv_dir: Path = typer.Option(
        Path.cwd(),
        help="Allowed directory for CSV files.",
        exists=True,
        file_okay=False,
        resolve_path=True,
    ),
    debug: bool = typer.Option(False, help="Enable Flask debug mode."),
) -> None:
    global CSV_DIR
    CSV_DIR = str(csv_dir)

    if debug:
        app.run(host="0.0.0.0", port=port, debug=True, threaded=True)
    else:
        from gunicorn.app.base import BaseApplication

        class GunicornApp(BaseApplication):
            def __init__(self, application, options=None):
                self.application = application
                self.options = options or {}
                super().__init__()

            def load_config(self):
                for key, value in self.options.items():
                    self.cfg.set(key, value)

            def load(self):
                return self.application

        GunicornApp(app, {
            "bind": f"0.0.0.0:{port}",
            "workers": 4,
            "threads": 2,
            "timeout": 300,
            "preload_app": True,
            "accesslog": "-",
        }).run()


def cli() -> None:
    typer.run(main)


if __name__ == "__main__":
    cli()
