import atexit
import hashlib
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
from pathlib import Path

import polars as pl
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
FILE_DIR = os.path.realpath(os.getcwd())

VIDEO_EXTENSIONS = {".avi", ".mp4", ".mov", ".mkv", ".wmv", ".flv", ".webm"}

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


def get_db_path(file_path: str, use_tmpdir: bool = False) -> str:
    base, _ = os.path.splitext(file_path)
    if use_tmpdir:
        path_hash = hashlib.md5(file_path.encode()).hexdigest()
        basename = os.path.basename(base)
        return os.path.join(TMPDIR, f"{basename}_{path_hash}_clipviewer.db")
    return f"{base}_clipviewer.db"


def detect_video_column(first_row: dict) -> str | None:
    """Auto-detect which column contains video file paths by checking the first row."""
    for col, value in first_row.items():
        value = str(value).strip()
        if not value:
            continue
        ext = os.path.splitext(value)[1].lower()
        if ext not in VIDEO_EXTENSIONS:
            continue
        if os.path.isfile(os.path.join(VIDEO_BASE, value)):
            return col
    return None


def _detect_video_column_or_raise(first_row: dict) -> str:
    detected = detect_video_column(first_row)
    if detected is None:
        raise ValueError(
            "No 'avi_path' column found, and no column could be auto-detected "
            "as containing video file paths. Ensure at least one column contains "
            "paths to existing video files with extensions: "
            + ", ".join(sorted(VIDEO_EXTENSIONS))
        )
    return detected


def get_db() -> sqlite3.Connection:
    """Open a DB connection from the session, or abort 400 if none loaded."""
    db_path = session.get("db_path")
    if not db_path or not os.path.isfile(db_path):
        abort(
            400, description="No file loaded. Please load a CSV or Parquet file first."
        )
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


@app.errorhandler(400)
def bad_request(e):
    return jsonify({"status": "error", "message": e.description}), 400


@app.route("/")
def index():
    return render_template("index.jinja2")


@app.route("/load_file", methods=["POST"])
def load_file():
    file_path = str(request.json["file_path"])
    metadata_fields = [
        m.strip() for m in str(request.json["metadata_fields"]).split(",") if m.strip()
    ]
    video_path_column = "avi_path"

    if not is_path_within(file_path, FILE_DIR):
        return jsonify(
            {"status": "error", "message": "File path not in allowed directory"}
        ), 403

    # Check write access to determine read-only mode
    file_dir = os.path.dirname(os.path.realpath(file_path))
    read_only = not os.access(file_dir, os.W_OK)

    # Skip re-processing if DB is already up-to-date AND metadata fields match
    db_path = get_db_path(file_path, use_tmpdir=read_only)
    requested_meta = ",".join(metadata_fields)
    try:
        if os.path.isfile(db_path) and os.path.getmtime(db_path) >= os.path.getmtime(
            file_path
        ):
            with sqlite3.connect(db_path, timeout=10) as conn:
                try:
                    stored_meta = conn.execute(
                        "SELECT key, value FROM meta WHERE key IN ('metadata_fields', 'source_file_path', 'video_path_column')"
                    ).fetchall()
                    stored = {k: v for k, v in stored_meta}
                    if (
                        stored.get("metadata_fields") == requested_meta
                        and stored.get("source_file_path") == file_path
                        and stored.get("video_path_column")
                    ):
                        session["db_path"] = db_path
                        return jsonify(
                            {
                                "status": "success",
                                "message": "File loaded successfully",
                                "read_only": read_only,
                            }
                        )
                except sqlite3.OperationalError:
                    try:
                        stored = conn.execute(
                            "SELECT value FROM meta WHERE key = 'metadata_fields'"
                        ).fetchone()
                        if stored and stored[0] == requested_meta:
                            session["db_path"] = db_path
                            return jsonify(
                                {
                                    "status": "success",
                                    "message": "File loaded successfully",
                                    "read_only": read_only,
                                }
                            )
                    except sqlite3.OperationalError:
                        pass  # meta table missing (old DB) -- fall through to re-import
                except Exception:
                    pass

    except OSError:
        pass

    try:
        ext = os.path.splitext(file_path)[1].lower()

        # Format-specific loading: parquet reads only needed columns
        if ext == ".parquet":
            all_columns = list(pl.read_parquet_schema(file_path).keys())

            missing_meta = set(metadata_fields) - set(all_columns)
            if missing_meta:
                raise ValueError(f"File is missing columns: {', '.join(missing_meta)}")

            if "avi_path" not in all_columns:
                sample = pl.read_parquet(file_path, n_rows=1)
                first_row = sample.row(0, named=True) if len(sample) > 0 else {}
                video_path_column = _detect_video_column_or_raise(first_row)

            needed_cols = [video_path_column] + [m for m in metadata_fields if m != video_path_column]
            df = pl.read_parquet(file_path, columns=needed_cols)
        else:
            df = pl.read_csv(file_path)

        # Format-agnostic: detect video column, validate, filter
        if "avi_path" not in df.columns:
            if video_path_column == "avi_path":
                first_row = df.row(0, named=True) if len(df) > 0 else {}
                video_path_column = _detect_video_column_or_raise(first_row)
            df = df.rename({video_path_column: "avi_path"})

        missing_meta = set(metadata_fields) - set(df.columns)
        if missing_meta:
            raise ValueError(f"File is missing columns: {', '.join(missing_meta)}")

        df = df.filter(pl.col("avi_path").is_not_null() & (pl.col("avi_path").cast(pl.Utf8) != ""))

        for avi_path in df["avi_path"].head(100).to_list():
            video_path = os.path.join(VIDEO_BASE, str(avi_path))
            if not os.path.isfile(video_path):
                raise FileNotFoundError(f"Video file not found: {video_path}")

        # Build clip tuples using Polars expressions
        if metadata_fields:
            meta_expr = pl.concat_str(
                [pl.format("{}: {}", pl.lit(m), pl.col(m).cast(pl.Utf8).fill_null("")) for m in metadata_fields],
                separator="\n",
            )
            clip_df = df.select(pl.col("avi_path").cast(pl.Utf8), meta_expr.alias("metadata"))
        else:
            clip_df = df.select(pl.col("avi_path").cast(pl.Utf8), pl.lit("").alias("metadata"))
        clip_rows = list(clip_df.iter_rows())

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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT ''
                )
            """)
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('metadata_fields', ?)",
                (requested_meta,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('source_file_path', ?)",
                (file_path,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('video_path_column', ?)",
                (video_path_column,),
            )

            # Upsert: update metadata, preserve existing comments
            conn.executemany(
                """INSERT INTO clips (avi_path, metadata)
                   VALUES (?, ?)
                   ON CONFLICT(avi_path) DO UPDATE SET
                       metadata = excluded.metadata""",
                clip_rows,
            )

        session["db_path"] = db_path
        return jsonify(
            {
                "status": "success",
                "message": "File loaded successfully",
                "read_only": read_only,
            }
        )
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
        meta_rows = conn.execute(
            "SELECT key, value FROM meta WHERE key IN ('source_file_path', 'video_path_column')"
        ).fetchall()
        meta = {row["key"]: row["value"] for row in meta_rows}

        source_file_path = meta.get("source_file_path")
        video_path_column = meta.get("video_path_column")
        if not source_file_path or not video_path_column:
            abort(
                400,
                description="Missing export metadata. Reload the source file first.",
            )

        clip_rows = conn.execute(
            "SELECT avi_path, comment, reviewed_at FROM clips"
        ).fetchall()

    ext = os.path.splitext(source_file_path)[1].lower()
    if ext == ".parquet":
        df = pl.read_parquet(source_file_path)
    else:
        df = pl.read_csv(source_file_path)

    source_columns = list(df.columns)
    if video_path_column not in source_columns:
        abort(
            400,
            description=f"Configured video path column '{video_path_column}' not found in source file.",
        )

    annotation_comment_col = "clipviewer_comment"
    annotation_reviewed_col = "clipviewer_reviewed_at"
    if (
        annotation_comment_col in source_columns
        or annotation_reviewed_col in source_columns
    ):
        abort(
            400,
            description="Source file already contains clipviewer export columns.",
        )

    annotations_df = pl.DataFrame(
        {
            "avi_path": [str(row["avi_path"]) for row in clip_rows],
            annotation_comment_col: [row["comment"] for row in clip_rows],
            annotation_reviewed_col: [row["reviewed_at"] or "" for row in clip_rows],
        }
    )
    df = df.with_columns(pl.col(video_path_column).cast(pl.Utf8).alias("_join_key"))
    df = df.join(annotations_df, left_on="_join_key", right_on="avi_path", how="left")
    df = df.drop("_join_key")
    df = df.with_columns(
        pl.col(annotation_comment_col).fill_null(""),
        pl.col(annotation_reviewed_col).fill_null(""),
    )

    export_cols = source_columns + [annotation_comment_col, annotation_reviewed_col]
    csv_bytes = df.select(export_cols).fill_null("").write_csv()

    return Response(
        csv_bytes,
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
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name,pix_fmt",
                "-of",
                "csv=p=0",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
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
    file_dir: Path = typer.Option(
        Path.cwd(),
        help="Allowed directory for CSV / Parquet files.",
        exists=True,
        file_okay=False,
        resolve_path=True,
    ),
    debug: bool = typer.Option(False, help="Enable Flask debug mode."),
) -> None:
    global FILE_DIR
    FILE_DIR = str(file_dir)

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
                if self.cfg is None:
                    return
                for key, value in self.options.items():
                    self.cfg.set(key, value)

            def load(self):
                return self.application

        GunicornApp(
            app,
            {
                "bind": f"0.0.0.0:{port}",
                "workers": 4,
                "threads": 2,
                "timeout": 300,
                "preload_app": True,
                "accesslog": "-",
            },
        ).run()


def cli() -> None:
    typer.run(main)


if __name__ == "__main__":
    cli()
