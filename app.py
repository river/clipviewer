import os, sys, argparse
from datetime import datetime

from flask import Flask, render_template, request, jsonify, send_file
import pandas as pd

# -------------
# CONFIGURATION
# -------------

# additional columns from the csv file to show
METADATA_TO_SHOW = [
    "gt_labels",
    "split",
    "study_type",
]
VIDEO_BASE_PATH = "/"  # base directory for avipaths
CLIPS_PER_PAGE = 6  # how many clips to show on each page
PORT = 8889

# -----------------------------
# DO NOT MODIFY BELOW THIS LINE
# -----------------------------

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html", clips_per_page=CLIPS_PER_PAGE)


@app.route("/get_clips")
def get_clips():
    page = int(request.args.get("page", 0))
    start_idx = page * CLIPS_PER_PAGE
    end_idx = min(start_idx + CLIPS_PER_PAGE, len(df))

    clips = []
    for idx in range(start_idx, end_idx):
        row = df.iloc[idx]
        filename = row.avipath.split("/")[-1]
        metadata = " | ".join([f"{m}: {str(row[m])}" for m in METADATA_TO_SHOW])
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
            "total_pages": (len(df) - 1) // CLIPS_PER_PAGE + 1,
            "total_clips": len(df),
            "clips_per_page": CLIPS_PER_PAGE,
        }
    )


@app.route("/save_comments", methods=["POST"])
def save_comments():
    global comments_df
    new_comments = request.json

    for comment in new_comments:  # type: ignore
        filename = comment["filename"]
        comment_text = comment["comment"]

        if filename in comments_df["filename"].values:
            comments_df.loc[comments_df["filename"] == filename, "comments"] = (
                comment_text
            )
        else:
            new_row = pd.DataFrame({"filename": [filename], "comments": [comment_text]})
            comments_df = pd.concat([comments_df, new_row], ignore_index=True)

    # Save comments to file
    comments_df.to_csv(comments_file, index=False)

    # Also save a timestamped version
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_file = os.path.join(args.comments_path, f"comments_{timestamp}.csv")
    comments_df.to_csv(save_file, index=False)

    return jsonify({"status": "success", "file": save_file})


@app.route("/video/<path:filename>")
def serve_video(filename):
    full_path = os.path.join(VIDEO_BASE_PATH, filename)
    return send_file(full_path, mimetype="video/mp4")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "csv_path", help="Path to the CSV file containing echo clips in avipath column"
    )
    parser.add_argument("comments_path", help="Path to directory to write comments")

    def check_file_exists(path):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"The file {path} does not exist.")

    def check_required_columns(df):
        missing_columns = set(METADATA_TO_SHOW + ["avipath"]) - set(df.columns)
        if missing_columns:
            raise ValueError(
                f"CSV is missing required columns: {', '.join(missing_columns)}"
            )

    def check_video_files(df):
        for _, row in df.head(10).iterrows():
            video_path = os.path.join(VIDEO_BASE_PATH, row["avipath"])
            if not os.path.isfile(video_path):
                raise FileNotFoundError(f"Video file not found: {video_path}")

    try:
        args = parser.parse_args()

        check_file_exists(args.csv_path)
        df = pd.read_csv(args.csv_path)
        check_required_columns(df)
        df = df.dropna(subset="avipath")
        check_video_files(df)

        # Load existing comments or create a new DataFrame
        if not os.path.exists(args.comments_path):
            os.makedirs(args.comments_path, exist_ok=True)
        comments_file = os.path.join(args.comments_path, "comments.csv")
        if os.path.exists(comments_file):
            comments_df = pd.read_csv(comments_file, na_filter=False)
        else:
            comments_df = pd.DataFrame(columns=["filename", "comments"])

    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)

    app.run(host="0.0.0.0", port=PORT)
