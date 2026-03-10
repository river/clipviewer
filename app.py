import os
import argparse

from flask import Flask, render_template, request, jsonify, send_file
import pandas as pd

# -------------
# CONFIGURATION
# -------------

# additional columns from the csv file to show
VIDEO_BASE_PATH = "/"  # base directory for avi_paths
CLIPS_PER_PAGE = 6  # how many clips to show on each page
ALLOWED_CSV_DIR = os.environ.get("CLIPVIEWER_CSV_DIR", os.getcwd())

# -----------------------------
# DO NOT MODIFY BELOW THIS LINE
# -----------------------------

app = Flask(__name__)

# NOTE: These module-level globals are not thread-safe.
# This application should be run with threaded=False.
# For production use, consider a proper database or per-request state management.
echo_df = None
comments_df = None
comments_path = None
metadata_fields = None


@app.route("/")
def index():
    return render_template("index.jinja2")


@app.route("/load_csv", methods=["POST"])
def load_csv():
    global echo_df, comments_df, comments_path, metadata_fields

    csv_path = str(request.json["csv_path"])
    metadata_fields = [
        m.strip() for m in str(request.json["metadata_fields"]).split(",") if m.strip()
    ]

    real_csv = os.path.realpath(csv_path)
    if not real_csv.startswith(os.path.realpath(ALLOWED_CSV_DIR) + os.sep):
        return jsonify(
            {"status": "error", "message": "CSV path not in allowed directory"}
        ), 403

    try:
        echo_df = pd.read_csv(csv_path)
        if metadata_fields:
            check_required_columns(echo_df, metadata_fields)
        echo_df = echo_df.dropna(subset="avi_path")
        check_video_files(echo_df)

        # Load existing comments or create a new DataFrame
        base, ext = os.path.splitext(csv_path)
        comments_path = f"{base}_comments{ext}"
        if os.path.exists(comments_path):
            comments_df = pd.read_csv(comments_path, na_filter=False)
        else:
            comments_df = pd.DataFrame(columns=["filename", "comments"])

        return jsonify({"status": "success", "message": "CSV loaded successfully"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


def check_required_columns(df: pd.DataFrame, metadata_fields: list[str]):
    missing_columns = set(metadata_fields + ["avi_path"]) - set(df.columns)
    if missing_columns:
        raise ValueError(
            f"CSV is missing metadata columns: {', '.join(missing_columns)}"
        )


def check_video_files(df: pd.DataFrame):
    for _, row in df.iterrows():
        video_path = os.path.join(VIDEO_BASE_PATH, row["avi_path"])
        if not os.path.isfile(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")


@app.route("/get_clips")
def get_clips():
    global echo_df, comments_df, metadata_fields

    if echo_df is None:
        return jsonify(
            {"status": "error", "message": "No CSV loaded. Please load a CSV first."}
        ), 400

    page = int(request.args.get("page", 0))
    start_idx = page * CLIPS_PER_PAGE
    end_idx = min(start_idx + CLIPS_PER_PAGE, len(echo_df))

    clips = []
    for idx in range(start_idx, end_idx):
        row = echo_df.iloc[idx]
        filename = row.avi_path.split("/")[-1]
        metadata = (
            ", ".join([f"{m}: {str(row[m])}" for m in metadata_fields])
            if metadata_fields
            else ""
        )
        clip_reviewed = (
            "reviewed" if (comments_df["filename"] == filename).any() else ""
        )
        existing_comment = comments_df[comments_df["filename"] == filename][
            "comments"
        ].values
        comment = existing_comment[0] if len(existing_comment) > 0 else ""

        clips.append(
            {
                "video_path": row.avi_path,
                "metadata": metadata,
                "clip_reviewed": clip_reviewed,
                "comment": comment,
                "filename": filename,
            }
        )

    return jsonify(
        {
            "clips": clips,
            "total_pages": (len(echo_df) - 1) // CLIPS_PER_PAGE + 1,
            "total_clips": len(echo_df),
            "clips_per_page": CLIPS_PER_PAGE,
        }
    )


@app.route("/save_comments", methods=["POST"])
def save_comments():
    global comments_df, comments_path

    if comments_df is None or comments_path is None:
        return jsonify(
            {"status": "error", "message": "No CSV loaded. Please load a CSV first."}
        ), 400

    new_comments = request.json
    for comment in new_comments:
        filename, comment_text = comment["filename"], comment["comment"]

        # get rid of new lines in comment text
        comment_text = comment_text.replace("\n", " ").replace("\r", "")

        if filename in comments_df["filename"].values:
            # if file already has comment, replace comment
            comments_df.loc[comments_df["filename"] == filename, "comments"] = (
                comment_text
            )
        else:
            # comment about new file
            new_index = comments_df.index.max() + 1 if len(comments_df) > 0 else 0
            comments_df.loc[new_index] = [filename, comment_text]

    # Save comments to file
    comments_df.to_csv(comments_path, index=False)

    return jsonify({"status": "success", "file": comments_path})


@app.route("/video/<path:filename>")
def serve_video(filename):
    base = os.path.realpath(VIDEO_BASE_PATH)
    full_path = os.path.realpath(os.path.join(base, filename))
    if not full_path.startswith(base + os.sep):
        return "Forbidden", 403
    if not os.path.isfile(full_path):
        return "Not found", 404
    return send_file(full_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--port",
        type=int,
        default=8888,
        help="Port number to run the server on (default: 8888)",
    )
    args = parser.parse_args()

    debug = os.environ.get("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=args.port, debug=debug, threaded=False)
