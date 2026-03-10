<img src="static/screenshot.png" alt="Screenshot of clipviewer web app" width="400px">


# clipviewer

**clipviewer** is a simple web app for viewing and annotating video clips; it was designed with viewing and annotating echo clips in mind

## Features

- Browse through a collection of video clips
- View metadata for each clip
- Add and save comments for individual clips
- Export comments as a CSV file
- Navigate using previous/next buttons (including left and right keys on your keyboard) or jump to a specific page
- Progress bar to show current position in the clip collection
- Reviewed clips are highlighted

## Setup

1. Clone the repository:
   ```
   git clone <repository-url>
   cd clipviewer
   ```

2. Install dependencies:
   ```
   uv sync
   ```

## Usage

1. Start the Flask server:
   ```
   uv run python app.py [--port PORT]
   ```

2. Open a web browser and navigate to `http://localhost:8888` (or the appropriate port if you've changed it).

## Notes

- Currently videos only load and display properly in Safari. Videos do not load in Chrome for an unknown reason (pull requests welcome).
- Annotations are stored in a SQLite database alongside the input CSV file (e.g., `echoes_clipviewer.db`). Use the "Export CSV" button to download comments as a CSV file.
- Existing `_comments.csv` files are automatically imported on first load.
