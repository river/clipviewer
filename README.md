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

Requires [uv](https://docs.astral.sh/uv/) and `ffmpeg` installed on the system.

```
git clone <repository-url>
cd clipviewer
```

## Usage

```
uv run clipviewer [OPTIONS]
```

Open `http://localhost:8888` in your browser.

| Option | Description | Default |
|---|---|---|
| `--port` | Port number | `8888` |
| `--csv-dir` | Allowed directory for CSV files | Current working directory |
| `--debug` | Use Flask dev server instead of gunicorn | Off |

## Notes

- Videos are automatically converted to H.264 MP4 for cross-browser compatibility. Videos already in H.264/yuv420p format are served directly.
- Annotations are stored in a SQLite database alongside the input CSV (e.g., `echoes_clipviewer.db`). Use "Export CSV" to download comments.
- Comments are preserved when reloading the same CSV.
