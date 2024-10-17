# clipviewer

**clipviewer** is a simple web app for viewing and annotating video clips; it was designed with viewing and annotating echo clips in mind

## Features

- Browse through a collection of video clips
- View metadata for each clip
- Add and save comments for individual clips
- Navigate using previous/next buttons (including left and right keys on your keyboard) or jump to a specific page
- Progress bar to show current position in the clip collection
- Reviewed clips are highlighted

## Setup

1. Clone the repository:
   ```
   git clone <repository-url>
   cd clipviewer
   ```

2. Install the required Python packages:
   ```
   pip install flask pandas
   ```

3. (Optional:) Adjust `METADATA_TO_SHOW`, `VIDEO_BASE_PATH`, `CLIPS_PER_PAGE`, `PORT` in `app.py`

## Usage

1. Start the Flask server:
   ```
   python app.py [-h] csv_path comments_path port(optional)
   ```
   Where `csv_path` is the path to the csv file containing the avi file paths and any additional optional metadata about the clips; and `comments_path` is a directory in which to write the annotations. `port` is optional and defaults to 8888.

2. Open a web browser and navigate to `http://localhost:8888` (or the appropriate port if you've changed it).

## Notes

- Comments are saved with timestamped backups created each time comments are saved. The `comments.csv` file contains the most up to date annotations. 
