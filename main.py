from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
import os
import uuid
import asyncio
from pathlib import Path
import subprocess
import tempfile
from typing import Optional, List, Dict
from urllib.parse import quote, unquote
import time
import threading
import hashlib
from functools import lru_cache
import json
import platform

app = FastAPI(title="spotDL API", description="API for downloading Spotify tracks and playlists")

# Cache for download URLs (URL -> {file_path, timestamp})
url_cache: Dict[str, Dict] = {}
CACHE_TTL = 3600  # 1 hour cache

# Platform-specific temp directory
# For Railway, use /tmp which is persistent within a deployment
if os.environ.get("RAILWAY_ENVIRONMENT"):
    TEMP_BASE = Path("/tmp/spotdl_api")
else:
    TEMP_BASE = Path(tempfile.gettempdir()) / "spotdl_api"
TEMP_BASE.mkdir(exist_ok=True)

# Pre-warm environment variables
os.environ["XDG_CACHE_HOME"] = str(TEMP_BASE / "cache")
os.environ["XDG_CONFIG_HOME"] = str(TEMP_BASE / "config")
os.environ["XDG_DATA_HOME"] = str(TEMP_BASE / "data")

# Create cache directories at startup
for subdir in ["cache", "config", "data"]:
    (TEMP_BASE / subdir).mkdir(exist_ok=True)

# Create downloads directory (cross-platform compatible)
DOWNLOAD_DIR = TEMP_BASE / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

class DownloadRequest(BaseModel):
    spotify_url: str
    format: Optional[str] = "mp3"
    quality: Optional[str] = "best"
    output_file: Optional[str] = None

class PlaylistRequest(BaseModel):
    playlist_url: str
    format: Optional[str] = "mp3"
    quality: Optional[str] = "best"
    output_file: Optional[str] = None

class SyncRequest(BaseModel):
    query: str
    save_file: str
    format: Optional[str] = "mp3"
    quality: Optional[str] = "best"

class SaveRequest(BaseModel):
    query: str
    save_file: str

class UrlRequest(BaseModel):
    query: str

class MetaRequest(BaseModel):
    file_paths: List[str]

class DownloadStatus(BaseModel):
    task_id: str
    status: str
    progress: Optional[float] = None
    file_path: Optional[str] = None
    error: Optional[str] = None

# Store task status (in production, use Redis or database)
task_status = {}

# Store temporary files for direct download
temp_files = {}

# Cleanup function to remove old temp files and cache
def cleanup_old_files():
    """Remove files older than 1 hour from downloads directory and clean cache"""
    while True:
        try:
            current_time = time.time()
            # Clean old directories
            for temp_dir in DOWNLOAD_DIR.glob("temp_*"):
                if temp_dir.is_dir():
                    dir_age = current_time - temp_dir.stat().st_mtime
                    if dir_age > 3600:  # 1 hour
                        import shutil
                        shutil.rmtree(temp_dir)
                        print(f"Cleaned up old temp directory: {temp_dir}")
            
            # Clean URL cache
            expired_keys = []
            for url, data in url_cache.items():
                if current_time - data.get('timestamp', 0) > CACHE_TTL:
                    expired_keys.append(url)
            for key in expired_keys:
                del url_cache[key]
                
        except Exception as e:
            print(f"Cleanup error: {e}")
        
        time.sleep(300)  # Check every 5 minutes

# Start cleanup thread
cleanup_thread = threading.Thread(target=cleanup_old_files, daemon=True)
cleanup_thread.start()

@app.get("/")
async def root():
    return {"message": "spotDL API is running", "version": "1.0.0"}

@app.post("/get/audio-download-link")
async def get_audio_download_link(request: DownloadRequest, http_request: Request):
    """
    Get direct download link for the audio file (synchronous with caching)
    Returns immediately if cached, otherwise downloads and returns the link
    """
    try:
        # Check cache first for instant response
        cache_key = hashlib.md5(f"{request.spotify_url}_{request.format}_{request.quality}".encode()).hexdigest()
        if cache_key in url_cache:
            cached_data = url_cache[cache_key]
            if time.time() - cached_data['timestamp'] < CACHE_TTL:
                if os.path.exists(cached_data['file_path']):
                    # Return cached result INSTANTLY
                    base_url = str(http_request.base_url).rstrip('/')
                    filename = Path(cached_data['file_path']).name
                    download_url = f"{base_url}/temp-download/{quote(filename)}"
                    temp_files[download_url] = cached_data['file_path']
                    return {
                        "spotify_url": request.spotify_url,
                        "audio_download_url": download_url,
                        "filename": filename,
                        "format": request.format,
                        "quality": request.quality,
                        "file_size": Path(cached_data['file_path']).stat().st_size,
                        "cached": True
                    }
        
        # Not cached - download it now (with optimizations)
        temp_dir = DOWNLOAD_DIR / f"temp_{str(uuid.uuid4())}"
        temp_dir.mkdir(exist_ok=True)
        
        # HYPER-OPTIMIZED spotDL command for maximum speed
        cmd = [
            "spotdl",
            "download",
            request.spotify_url,
            "--output", str(temp_dir),
            "--format", request.format,
            "--threads", "8",           # 8 concurrent threads
            "--bitrate", "128k",        # Lower bitrate = faster download
            "--skip-album-art"          # Skip downloading/embedding album art (saves 2-5 seconds)
        ]
        
        # Run with timeout
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
            print(f"DEBUG: spotdl stdout: {stdout.decode()}")
            print(f"DEBUG: spotdl stderr: {stderr.decode()}")
            print(f"DEBUG: spotdl return code: {process.returncode}")
        except asyncio.TimeoutError:
            process.kill()
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise HTTPException(status_code=408, detail="Download timeout after 2 minutes")
        
        if process.returncode != 0:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=f"Download failed: {stderr.decode()}")
        
        # Find the downloaded file - more robust search
        downloaded_files = []
        
        # Try multiple file patterns
        for pattern in [f"*.{request.format}", "*.mp3", "*.m4a", "*.ogg", "*.wav"]:
            files = list(temp_dir.glob(pattern))
            if files:
                downloaded_files.extend(files)
        
        # Debug: List all files in temp directory
        all_files = list(temp_dir.glob("*"))
        print(f"DEBUG: Files in temp_dir {temp_dir}: {[f.name for f in all_files]}")
        
        if not downloaded_files:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=f"No audio file found after download. Files found: {[f.name for f in all_files]}")
        
        audio_file = downloaded_files[0]
        
        # Move file to stable location (important for Railway ephemeral storage)
        stable_filename = f"{cache_key}_{audio_file.name}"
        stable_path = DOWNLOAD_DIR / stable_filename
        
        try:
            # Copy file to stable location
            import shutil
            shutil.move(str(audio_file), str(stable_path))
            print(f"DEBUG: Moved file to {stable_path}")
            
            # Clean up temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)
            
            # Cache the stable path
            url_cache[cache_key] = {
                'file_path': str(stable_path),
                'timestamp': time.time()
            }
            audio_file = stable_path
            
        except Exception as e:
            print(f"DEBUG: Failed to move file: {e}")
            # Fall back to original location
            url_cache[cache_key] = {
                'file_path': str(audio_file),
                'timestamp': time.time()
            }
        
        # Create download URL
        base_url = str(http_request.base_url).rstrip('/')
        download_url = f"{base_url}/temp-download/{quote(audio_file.name)}"
        temp_files[download_url] = str(audio_file)
        
        return {
            "spotify_url": request.spotify_url,
            "audio_download_url": download_url,
            "filename": audio_file.name,
            "format": request.format,
            "quality": "128k",  # Actual bitrate being used for speed
            "file_size": audio_file.stat().st_size,
            "cached": False
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/temp-download/{filename}")
async def temp_download_file(filename: str):
    """
    Serve temporary downloaded files with streaming support
    """
    decoded_filename = unquote(filename)
    
    # Optimized file lookup using filename
    file_path = None
    for url, path in temp_files.items():
        if decoded_filename in path:
            file_path = path
            break
    
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    # Use FileResponse with streaming for better performance
    return FileResponse(
        file_path,
        media_type="audio/mpeg",
        filename=decoded_filename,
        headers={"Accept-Ranges": "bytes"}  # Enable range requests for streaming
    )

@app.post("/get/download-link")
async def get_download_link(request: DownloadRequest):
    """
    Get direct download link for a Spotify track (synchronous)
    """
    try:
        # Create temporary directory
        temp_dir = DOWNLOAD_DIR / f"temp_{str(uuid.uuid4())}"
        temp_dir.mkdir(exist_ok=True)
        
        # Build spotDL command to get URL
        cmd = [
            "spotdl",
            "url",
            request.spotify_url
        ]
        
        # Run spotDL to get YouTube URL
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            # Clean up temp directory
            import shutil
            shutil.rmtree(temp_dir)
            raise HTTPException(status_code=400, detail=f"Failed to get download link: {stderr.decode()}")
        
        # Extract YouTube URL from output
        youtube_url = stdout.decode().strip()
        
        if not youtube_url or not youtube_url.startswith('http'):
            # Clean up temp directory
            import shutil
            shutil.rmtree(temp_dir)
            raise HTTPException(status_code=400, detail="No valid download URL found")
        
        # Clean up temp directory
        import shutil
        shutil.rmtree(temp_dir)
        
        return {
            "spotify_url": request.spotify_url,
            "download_url": youtube_url,
            "format": request.format,
            "quality": request.quality,
            "note": "This is the YouTube URL. You can download the audio using this URL with any YouTube downloader."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.post("/download/track")
async def download_track(request: DownloadRequest, background_tasks: BackgroundTasks):
    """
    Download a single Spotify track
    """
    task_id = str(uuid.uuid4())
    
    # Initialize task status
    task_status[task_id] = DownloadStatus(
        task_id=task_id,
        status="queued"
    )
    
    # Add background task
    background_tasks.add_task(
        download_track_background,
        task_id,
        request.spotify_url,
        request.format,
        request.quality
    )
    
    return {"task_id": task_id, "message": "Download started"}

@app.post("/download/playlist")
async def download_playlist(request: PlaylistRequest, background_tasks: BackgroundTasks):
    """
    Download a Spotify playlist
    """
    task_id = str(uuid.uuid4())
    
    # Initialize task status
    task_status[task_id] = DownloadStatus(
        task_id=task_id,
        status="queued"
    )
    
    # Add background task
    background_tasks.add_task(
        download_playlist_background,
        task_id,
        request.playlist_url,
        request.format,
        request.quality
    )
    
    return {"task_id": task_id, "message": "Playlist download started"}

@app.get("/status/{task_id}")
async def get_download_status(task_id: str):
    """
    Get the status of a download task
    """
    if task_id not in task_status:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return task_status[task_id]

@app.get("/download/{task_id}")
async def get_download_file(task_id: str):
    """
    Download the completed file
    """
    if task_id not in task_status:
        raise HTTPException(status_code=404, detail="Task not found")
    
    status = task_status[task_id]
    
    if status.status != "completed":
        raise HTTPException(status_code=400, detail="Download not completed")
    
    if not status.file_path or not os.path.exists(status.file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    # For playlists, return a zip file
    if os.path.isdir(status.file_path):
        import zipfile
        zip_path = status.file_path + ".zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(status.file_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, status.file_path)
                    zipf.write(file_path, arcname)
        
        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename=f"playlist_{task_id}.zip"
        )
    
    return FileResponse(
        status.file_path,
        media_type="audio/mpeg",
        filename=os.path.basename(status.file_path)
    )

@app.post("/save/metadata")
async def save_metadata(request: SaveRequest, background_tasks: BackgroundTasks):
    """
    Save only metadata from Spotify without downloading anything
    """
    task_id = str(uuid.uuid4())
    
    task_status[task_id] = DownloadStatus(
        task_id=task_id,
        status="queued"
    )
    
    background_tasks.add_task(
        save_metadata_background,
        task_id,
        request.query,
        request.save_file
    )
    
    return {"task_id": task_id, "message": "Metadata save started"}

@app.post("/get/urls")
async def get_urls(request: UrlRequest, background_tasks: BackgroundTasks):
    """
    Get user-friendly URLs for each song from the query
    """
    task_id = str(uuid.uuid4())
    
    task_status[task_id] = DownloadStatus(
        task_id=task_id,
        status="queued"
    )
    
    background_tasks.add_task(
        get_urls_background,
        task_id,
        request.query
    )
    
    return {"task_id": task_id, "message": "URL extraction started"}

@app.post("/sync/playlist")
async def sync_playlist(request: SyncRequest, background_tasks: BackgroundTasks):
    """
    Sync directory with playlist state (download new songs, remove deleted ones)
    """
    task_id = str(uuid.uuid4())
    
    task_status[task_id] = DownloadStatus(
        task_id=task_id,
        status="queued"
    )
    
    background_tasks.add_task(
        sync_playlist_background,
        task_id,
        request.query,
        request.save_file,
        request.format,
        request.quality
    )
    
    return {"task_id": task_id, "message": "Playlist sync started"}

@app.post("/update/metadata")
async def update_metadata(request: MetaRequest, background_tasks: BackgroundTasks):
    """
    Update metadata for provided song files
    """
    task_id = str(uuid.uuid4())
    
    task_status[task_id] = DownloadStatus(
        task_id=task_id,
        status="queued"
    )
    
    background_tasks.add_task(
        update_metadata_background,
        task_id,
        request.file_paths
    )
    
    return {"task_id": task_id, "message": "Metadata update started"}
@app.delete("/task/{task_id}")
async def delete_task(task_id: str):
    """
    Delete a task and its files
    """
    if task_id not in task_status:
        raise HTTPException(status_code=404, detail="Task not found")
    
    status = task_status[task_id]
    
    # Clean up files
    if status.file_path and os.path.exists(status.file_path):
        if os.path.isdir(status.file_path):
            import shutil
            shutil.rmtree(status.file_path)
        else:
            os.remove(status.file_path)
    
    # Remove from status
    del task_status[task_id]
    
    return {"message": "Task deleted successfully"}

@app.get("/tasks")
async def list_tasks():
    """
    List all tasks and their status
    """
    return {"tasks": list(task_status.values())}

async def download_audio_link_background(task_id: str, spotify_url: str, format: str, quality: str, base_url: str, cache_key: str):
    """
    Optimized background task for audio download link
    """
    try:
        task_status[task_id].status = "downloading"
        
        temp_dir = DOWNLOAD_DIR / f"temp_{str(uuid.uuid4())}"
        temp_dir.mkdir(exist_ok=True)
        
        # Optimized spotDL command with threading
        cmd = [
            "spotdl",
            "download",
            spotify_url,
            "--output", str(temp_dir),
            "--format", format,
            "--threads", "4",  # Enable threading for faster downloads
            "--simple-tui"      # Reduce overhead from TUI
        ]
        
        if quality != "best":
            cmd.extend(["--quality", quality])
        
        # Run with timeout to prevent hanging
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)  # 2 min timeout
        except asyncio.TimeoutError:
            process.kill()
            task_status[task_id].status = "failed"
            task_status[task_id].error = "Download timeout after 2 minutes"
            return
        
        if process.returncode != 0:
            task_status[task_id].status = "failed"
            task_status[task_id].error = stderr.decode()
            import shutil
            shutil.rmtree(temp_dir)
            return
        
        downloaded_files = list(temp_dir.glob(f"*.{format}"))
        if not downloaded_files:
            downloaded_files = list(temp_dir.glob("*.mp3"))
        
        if not downloaded_files:
            task_status[task_id].status = "failed"
            task_status[task_id].error = "No audio file found"
            import shutil
            shutil.rmtree(temp_dir)
            return
        
        audio_file = downloaded_files[0]
        
        # Cache the result
        url_cache[cache_key] = {
            'file_path': str(audio_file),
            'timestamp': time.time()
        }
        
        # Create download URL
        download_url = f"{base_url}/temp-download/{quote(audio_file.name)}"
        temp_files[download_url] = str(audio_file)
        
        task_status[task_id].status = "completed"
        task_status[task_id].file_path = download_url  # Store the URL instead of file path
        
    except Exception as e:
        task_status[task_id].status = "failed"
        task_status[task_id].error = str(e)

async def download_track_background(task_id: str, spotify_url: str, format: str, quality: str, output_file: str = None):
    """
    Optimized background task to download a single track
    """
    try:
        task_status[task_id].status = "downloading"
        
        output_dir = DOWNLOAD_DIR / task_id
        output_dir.mkdir(exist_ok=True)
        
        # Build HYPER-optimized spotDL command
        cmd = [
            "spotdl",
            "download",
            spotify_url,
            "--output", str(output_dir),
            "--format", format,
            "--threads", "8",
            "--bitrate", "128k",
            "--skip-album-art"
        ]
        
        if output_file:
            cmd.extend(["--save-file", output_file])
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            task_status[task_id].status = "failed"
            task_status[task_id].error = stderr.decode()
            return
        
        downloaded_files = list(output_dir.glob("*.mp3"))
        if not downloaded_files:
            downloaded_files = list(output_dir.glob("*"))
        
        if downloaded_files:
            task_status[task_id].status = "completed"
            task_status[task_id].file_path = str(downloaded_files[0])
        else:
            task_status[task_id].status = "failed"
            task_status[task_id].error = "No file found after download"
            
    except Exception as e:
        task_status[task_id].status = "failed"
        task_status[task_id].error = str(e)

async def download_playlist_background(task_id: str, playlist_url: str, format: str, quality: str, output_file: str = None):
    """
    Optimized background task to download a playlist
    """
    try:
        task_status[task_id].status = "downloading"
        
        output_dir = DOWNLOAD_DIR / task_id
        output_dir.mkdir(exist_ok=True)
        
        # Build HYPER-optimized spotDL command for playlists
        cmd = [
            "spotdl",
            "download",
            playlist_url,
            "--output", str(output_dir),
            "--format", format,
            "--threads", "16",
            "--bitrate", "128k",
            "--skip-album-art"
        ]
        
        if output_file:
            cmd.extend(["--save-file", output_file])
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            task_status[task_id].status = "failed"
            task_status[task_id].error = stderr.decode()
            return
        
        downloaded_files = list(output_dir.rglob("*.mp3"))
        if downloaded_files:
            task_status[task_id].status = "completed"
            task_status[task_id].file_path = str(output_dir)
        else:
            task_status[task_id].status = "failed"
            task_status[task_id].error = "No files found after download"
            
    except Exception as e:
        task_status[task_id].status = "failed"
        task_status[task_id].error = str(e)

async def save_metadata_background(task_id: str, query: str, save_file: str):
    """
    Background task to save metadata only
    """
    try:
        task_status[task_id].status = "processing"
        
        output_dir = DOWNLOAD_DIR / task_id
        output_dir.mkdir(exist_ok=True)
        
        cmd = [
            "spotdl",
            "save",
            query,
            "--save-file", str(output_dir / save_file)
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            task_status[task_id].status = "completed"
            task_status[task_id].file_path = str(output_dir / save_file)
        else:
            task_status[task_id].status = "failed"
            task_status[task_id].error = stderr.decode()
            
    except Exception as e:
        task_status[task_id].status = "failed"
        task_status[task_id].error = str(e)

async def get_urls_background(task_id: str, query: str):
    """
    Background task to get URLs for songs
    """
    try:
        task_status[task_id].status = "processing"
        
        output_dir = DOWNLOAD_DIR / task_id
        output_dir.mkdir(exist_ok=True)
        
        output_file = output_dir / "urls.txt"
        
        cmd = [
            "spotdl",
            "url",
            query
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            with open(output_file, 'w') as f:
                f.write(stdout.decode())
            
            task_status[task_id].status = "completed"
            task_status[task_id].file_path = str(output_file)
        else:
            task_status[task_id].status = "failed"
            task_status[task_id].error = stderr.decode()
            
    except Exception as e:
        task_status[task_id].status = "failed"
        task_status[task_id].error = str(e)

async def sync_playlist_background(task_id: str, query: str, save_file: str, format: str, quality: str):
    """
    Background task to sync playlist with directory
    """
    try:
        task_status[task_id].status = "processing"
        
        output_dir = DOWNLOAD_DIR / task_id
        output_dir.mkdir(exist_ok=True)
        
        cmd = [
            "spotdl",
            "sync",
            query,
            "--save-file", str(output_dir / save_file)
        ]
        
        if format != "mp3":
            cmd.extend(["--format", format])
        
        if quality != "best":
            cmd.extend(["--quality", quality])
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            task_status[task_id].status = "completed"
            task_status[task_id].file_path = str(output_dir)
        else:
            task_status[task_id].status = "failed"
            task_status[task_id].error = stderr.decode()
            
    except Exception as e:
        task_status[task_id].status = "failed"
        task_status[task_id].error = str(e)

async def update_metadata_background(task_id: str, file_paths: List[str]):
    """
    Background task to update metadata for files
    """
    try:
        task_status[task_id].status = "processing"
        
        cmd = ["spotdl", "meta"] + file_paths
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            task_status[task_id].status = "completed"
        else:
            task_status[task_id].status = "failed"
            task_status[task_id].error = stderr.decode()
            
    except Exception as e:
        task_status[task_id].status = "failed"
        task_status[task_id].error = str(e)

if __name__ == "__main__":
    import uvicorn
    import os
    import platform
    
    port = int(os.environ.get("PORT", 8080))
    
    # Optimized Uvicorn configuration (Windows-compatible)
    config = {
        "app": app,
        "host": "0.0.0.0",
        "port": port,
        "limit_concurrency": 100,
        "backlog": 2048
    }
    
    # Use uvloop and workers only on Unix systems
    if platform.system() != "Windows":
        config["workers"] = 4
        config["loop"] = "uvloop"
        config["http"] = "httptools"
    else:
        # Windows: Use default asyncio loop
        print("⚡ Running on Windows - using default asyncio (uvloop not supported)")
    
    uvicorn.run(**config)
