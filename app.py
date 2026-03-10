import os
import re
import csv
import io
import sqlite3
import argparse

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    send_file,
    session,
    Response,
)

# -------------
# CONFIGURATION
# -------------

VIDEO_BASE_PATH = "/"
CLIPS_PER_PAGE = 6
ALLOWED_CSV_DIR = os.environ.get("CLIPVIEWER_CSV_DIR", os.getcwd())

_REAL_VIDEO_BASE = os.path.realpath(VIDEO_BASE_PATH)
_REAL_CSV_DIR = os.path.realpath(ALLOWED_CSV_DIR)

app = Flask(__name__)
app.secret_key = os.environ.get("CLIPVIEWER_SECRET_KEY", os.urandom(24))

_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def is_path_within(path: str, allowed_dir: str) -> bool:
    real_path = os.path.realpath(path)
    return real_path.startswith(allowed_dir + os.sep) or real_path == allowed_dir


def get_db_path(csv_path: str) -> str:
    base, _ = os.path.splitext(csv_path)
    return f"{base}_clipviewer.db"


def get_db() -> sqlite3.Connection:
    db_path = session.get("db_path")
    if not db_path or not os.path.isfile(db_path):
        raise RuntimeError("No database loaded")
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def require_db():
    db_path = session.get("db_path")
    if not db_path or not os.path.isfile(db_path):
        return jsonify(
            {"status": "error", "message": "No CSV loaded. Please load a CSV first."}
        ), 400
    return None


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

        # Create/open database
        db_path = get_db_path(csv_path)
        conn = sqlite3.connect(db_path, timeout=10)
        conn.row_factory = sqlite3.Row

        # Create clips table
        conn.execute("DROP TABLE IF EXISTS clips")
        conn.execute("""
            CREATE TABLE clips (
                id INTEGER PRIMARY KEY,
                avi_path TEXT NOT NULL,
                filename TEXT NOT NULL UNIQUE,
                metadata TEXT NOT NULL DEFAULT '',
                comment TEXT NOT NULL DEFAULT ''
            )
        """)

        # Pre-format metadata and insert
        clip_rows = []
        for row in rows:
            filename = row["avi_path"].split("/")[-1]
            metadata = (
                ", ".join(f"{m}: {row.get(m, '')}" for m in metadata_fields)
                if metadata_fields
                else ""
            )
            clip_rows.append((row["avi_path"], filename, metadata))

        conn.executemany(
            "INSERT OR IGNORE INTO clips (avi_path, filename, metadata) VALUES (?, ?, ?)",
            clip_rows,
        )

        # Migrate existing _comments.csv if present
        base, ext = os.path.splitext(csv_path)
        comments_csv_path = f"{base}_comments{ext}"
        if os.path.isfile(comments_csv_path):
            with open(comments_csv_path, newline="") as f:
                comment_reader = csv.DictReader(f)
                for crow in comment_reader:
                    fn = crow.get("filename", "")
                    comment = crow.get("comments", "")
                    if fn and comment:
                        conn.execute(
                            "UPDATE clips SET comment = ? WHERE filename = ?",
                            (comment, fn),
                        )

        conn.commit()
        conn.close()

        session["db_path"] = db_path
        session["metadata_fields"] = metadata_fields

        return jsonify({"status": "success", "message": "CSV loaded successfully"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route("/get_clips")
def get_clips():
    if err := require_db():
        return err

    conn = get_db()
    page = int(request.args.get("page", 0))
    offset = page * CLIPS_PER_PAGE

    total = conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
    rows = conn.execute(
        "SELECT avi_path, filename, metadata, comment FROM clips LIMIT ? OFFSET ?",
        (CLIPS_PER_PAGE, offset),
    ).fetchall()
    conn.close()

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
    if err := require_db():
        return err

    conn = get_db()
    for item in request.json:
        filename = item["filename"]
        comment = item["comment"].replace("\n", " ").replace("\r", "")
        conn.execute(
            "UPDATE clips SET comment = ? WHERE filename = ?",
            (comment, filename),
        )
    conn.commit()
    conn.close()

    return jsonify({"status": "success"})


@app.route("/export_comments")
def export_comments():
    if err := require_db():
        return err

    conn = get_db()
    rows = conn.execute(
        "SELECT filename, comment FROM clips WHERE comment != '' ORDER BY filename"
    ).fetchall()
    conn.close()

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


@app.route("/video/<path:filename>")
def serve_video(filename):
    full_path = os.path.realpath(os.path.join(_REAL_VIDEO_BASE, filename))
    if not is_path_within(full_path, _REAL_VIDEO_BASE):
        return "Forbidden", 403
    return send_file(full_path)


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
