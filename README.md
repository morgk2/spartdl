# spotDL API

A hosted API wrapper for spotDL v4 (Spotify Downloader) that allows you to download Spotify tracks and playlists via HTTP requests.

## Features

- Download individual Spotify tracks
- Download entire Spotify playlists
- Save metadata without downloading audio
- Get YouTube URLs for tracks
- Sync playlists with directories
- Update metadata for existing files
- Asynchronous processing with background tasks
- Task status tracking
- File download endpoints
- Docker support for easy deployment

## Quick Start

### Using Docker (Recommended)

1. Clone the repository:
```bash
git clone <repository-url>
cd spotdl-api
```

2. Run with Docker Compose:
```bash
docker-compose up -d
```

The API will be available at `http://localhost:8000`

### Manual Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the application:
```bash
python main.py
```

## API Endpoints

### Get Direct Download Link (YouTube URL)
```http
POST /get/download-link
Content-Type: application/json

{
    "spotify_url": "https://open.spotify.com/track/...",
    "format": "mp3",
    "quality": "best"
}
```

**Response:**
```json
{
    "spotify_url": "https://open.spotify.com/track/...",
    "download_url": "https://youtube.com/watch?v=...",
    "format": "mp3",
    "quality": "best",
    "note": "This is the YouTube URL. You can download the audio using this URL with any YouTube downloader."
}
```

### Get Direct Audio Download Link
```http
POST /get/audio-download-link
Content-Type: application/json

{
    "spotify_url": "https://open.spotify.com/track/...",
    "format": "mp3",
    "quality": "best"
}
```

**Response:**
```json
{
    "spotify_url": "https://open.spotify.com/track/...",
    "audio_download_url": "http://localhost:8000/temp-download/song_name.mp3",
    "filename": "song_name.mp3",
    "format": "mp3",
    "quality": "best",
    "file_size": 5242880,
    "note": "This download link is temporary and will be available for a short time."
}
```

### Download Track
```http
POST /download/track
Content-Type: application/json

{
    "spotify_url": "https://open.spotify.com/track/...",
    "format": "mp3",
    "quality": "best",
    "output_file": "optional_filename"
}
```

### Download Playlist
```http
POST /download/playlist
Content-Type: application/json

{
    "playlist_url": "https://open.spotify.com/playlist/...",
    "format": "mp3", 
    "quality": "best",
    "output_file": "optional_filename"
}
```

### Save Metadata Only
```http
POST /save/metadata
Content-Type: application/json

{
    "query": "https://open.spotify.com/playlist/...",
    "save_file": "playlist.spotdl"
}
```

### Get YouTube URLs
```http
POST /get/urls
Content-Type: application/json

{
    "query": "https://open.spotify.com/track/..."
}
```

### Sync Playlist with Directory
```http
POST /sync/playlist
Content-Type: application/json

{
    "query": "https://open.spotify.com/playlist/...",
    "save_file": "sync.spotdl",
    "format": "mp3",
    "quality": "best"
}
```

### Update Metadata for Files
```http
POST /update/metadata
Content-Type: application/json

{
    "file_paths": ["/path/to/song1.mp3", "/path/to/song2.mp3"]
}
```

### Get Task Status
```http
GET /status/{task_id}
```

### Download File
```http
GET /download/{task_id}
```

### List All Tasks
```http
GET /tasks
```

### Delete Task
```http
DELETE /task/{task_id}
```

## Usage Examples

### Get Direct Download Link (Instant)
```bash
curl -X POST "http://localhost:8000/get/download-link" \
     -H "Content-Type: application/json" \
     -d '{"spotify_url": "https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh"}'
```

### Get Direct Audio Download Link (Instant)
```bash
curl -X POST "http://localhost:8000/get/audio-download-link" \
     -H "Content-Type: application/json" \
     -d '{"spotify_url": "https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh", "format": "mp3"}'
```

### Download a Single Track
```bash
curl -X POST "http://localhost:8000/download/track" \
     -H "Content-Type: application/json" \
     -d '{"spotify_url": "https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh"}'
```

### Save Playlist Metadata
```bash
curl -X POST "http://localhost:8000/save/metadata" \
     -H "Content-Type: application/json" \
     -d '{"query": "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M", "save_file": "playlist.spotdl"}'
```

### Get YouTube URLs
```bash
curl -X POST "http://localhost:8000/get/urls" \
     -H "Content-Type: application/json" \
     -d '{"query": "https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh"}'
```

### Sync Playlist
```bash
curl -X POST "http://localhost:8000/sync/playlist" \
     -H "Content-Type: application/json" \
     -d '{"query": "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M", "save_file": "sync.spotdl"}'
```

## Configuration

- **Format**: Supported formats include mp3, flac, opus, m4a, etc.
- **Quality**: Options include best, worst, or specific bitrates
- **Output Directory**: Files are stored in the `downloads/` directory
- **Operations**: All spotDL operations are supported (download, save, url, sync, meta)

## spotDL Operations Supported

1. **download** - Downloads songs from YouTube with metadata
2. **save** - Saves only metadata without downloading audio
3. **url** - Gets YouTube URLs for songs
4. **sync** - Updates directories based on playlist changes
5. **meta** - Updates metadata for existing audio files

## Deployment

### Docker Deployment

The application is containerized and can be easily deployed to any platform supporting Docker:

1. Build the image:
```bash
docker build -t spotdl-api .
```

2. Run the container:
```bash
docker run -p 8000:8000 -v $(pwd)/downloads:/app/downloads spotdl-api
```

### Cloud Deployment

The API can be deployed to cloud platforms like:
- Heroku
- AWS ECS/Fargate
- Google Cloud Run
- Azure Container Instances

## Audio Quality

spotDL downloads music from YouTube and is designed to always download the highest possible bitrate:
- 128 kbps for regular YouTube users
- 256 kbps for YouTube Music premium users

## Notes

- Requires FFmpeg for audio processing (included in Docker image)
- Downloads are processed asynchronously
- Files are automatically cleaned up when tasks are deleted
- In production, consider using Redis or a database for task storage
- Users are responsible for their actions and potential legal consequences

## License

This project is a wrapper around spotDL. Please refer to the spotDL license for the underlying tool.
