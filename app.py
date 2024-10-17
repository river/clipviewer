import os, sys, argparse
from datetime import datetime
from typing import List

from flask import Flask, render_template, request, jsonify, send_file
import pandas as pd

# -------------
# CONFIGURATION
# -------------

# additional columns from the csv file to show
VIDEO_BASE_PATH = "/"  # base directory for avipaths
CLIPS_PER_PAGE = 6  # how many clips to show on each page

# -----------------------------
# DO NOT MODIFY BELOW THIS LINE
# -----------------------------

app = Flask(__name__)

echo_df = None
comments_df = None
comments_path = None
metadata_fields = None

@app.route("/")
def index():
    return render_template("index.html", clips_per_page=CLIPS_PER_PAGE)


@app.route('/load_csv', methods=['POST'])
def load_csv():
    global echo_df, comments_df, comments_path, metadata_fields
    
    csv_path = str(request.json['csv_path'])
    metadata_fields = [m.strip() for m in str(request.json['metadata_fields']).split(',') if m.strip()]

    try:
        echo_df = pd.read_csv(csv_path)
        if metadata_fields:
            check_required_columns(echo_df, metadata_fields)
        echo_df = echo_df.dropna(subset="avipath")
        check_video_files(echo_df)

        # Load existing comments or create a new DataFrame
        comments_path = csv_path.replace(".csv", "_comments.csv")
        if os.path.exists(comments_path):
            comments_df = pd.read_csv(comments_path, na_filter=False)
        else:
            comments_df = pd.DataFrame(columns=["filename", "comments"])
        
        return jsonify({"status": "success", "message": "CSV loaded successfully"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


def check_required_columns(df: pd.DataFrame, metadata_fields: List[str]):
    missing_columns = set(metadata_fields + ["avipath"]) - set(df.columns)
    if missing_columns:
        raise ValueError(
            f"CSV is missing metadata columns: {', '.join(missing_columns)}"
        )

def check_video_files(df: pd.DataFrame):
    for _, row in df.head(10).iterrows():
        video_path = os.path.join(VIDEO_BASE_PATH, row["avipath"])
        if not os.path.isfile(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")


@app.route("/get_clips")
def get_clips():
    global echo_df, comments_df, metadata_fields
    
    page = int(request.args.get("page", 0))
    start_idx = page * CLIPS_PER_PAGE
    end_idx = min(start_idx + CLIPS_PER_PAGE, len(echo_df))

    clips = []
    for idx in range(start_idx, end_idx):
        row = echo_df.iloc[idx]
        filename = row.avipath.split("/")[-1]
        metadata = ", ".join([f"{m}: {str(row[m])}" for m in metadata_fields]) if metadata_fields else ""
        clip_reviewed = str((comments_df["filename"] == filename).any())
        existing_comment = comments_df[comments_df["filename"] == filename][
            "comments"
        ].values
        comment = existing_comment[0] if len(existing_comment) > 0 else ""

        clips.append(
            {
                "video_path": row.avipath,
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
    
    new_comments = request.json
    for comment in new_comments:  # type: ignore
        filename, comment_text = comment["filename"], comment["comment"]

        if filename in comments_df["filename"].values:
            # if file already has comment, replace comment
            comments_df.loc[comments_df["filename"] == filename, "comments"] = comment_text
        else:
            # comment about new file
            new_index = comments_df.index.max() + 1 if len(comments_df) > 0 else 0
            comments_df.loc[new_index] = [filename, comment_text]

    # Save comments to file
    comments_df.to_csv(comments_path, index=False)

    # Also save a timestamped version
    # timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # comments_path_timestamp = comments_path.replace(".csv", f"_{timestamp}.csv")
    # comments_df.to_csv(comments_path_timestamp, index=False)

    return jsonify({"status": "success", "file": comments_path})


@app.route("/video/<path:filename>")
def serve_video(filename):
    full_path = os.path.join(VIDEO_BASE_PATH, filename)
    return send_file(full_path, mimetype="video/mp4")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8888, help="Port number to run the server on (default: 8888)")
    args = parser.parse_args()

    app.run(host="0.0.0.0", port=args.port)