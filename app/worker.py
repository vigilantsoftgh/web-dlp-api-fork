import os
import time
import json
import subprocess
import shutil
from pathlib import Path
from queue import Queue
from threading import Thread
from datetime import datetime, timedelta
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("web-dlp")

# Configuration
DOWNLOAD_DIR = Path("app/downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Job queue
job_queue = Queue()
jobs = {}

# Cookie setup
def get_cookie_file():
    cookie_string = os.environ.get('YOUTUBE_COOKIES')
    if not cookie_string:
        logger.warning("⚠️ No YOUTUBE_COOKIES environment variable found")
        return None
    
    cookie_file = DOWNLOAD_DIR / "cookies.txt"
    try:
        # Convert to Netscape format
        cookie_pairs = [c.strip() for c in cookie_string.split(';') if c.strip()]
        with open(cookie_file, 'w') as f:
            f.write("# Netscape HTTP Cookie File\n")
            f.write("# This is a generated file! Do not edit.\n")
            for cookie in cookie_pairs:
                if '=' in cookie:
                    name, value = cookie.split('=', 1)
                    # Format: domain\tTRUE\tpath\tFALSE\texpiry\tname\tvalue
                    expiry = int(time.time()) + 31536000  # 1 year
                    f.write(f".youtube.com\tTRUE\t/\tFALSE\t{expiry}\t{name}\t{value}\n")
        logger.info("✅ Cookie file created successfully")
        return str(cookie_file)
    except Exception as e:
        logger.error(f"❌ Error creating cookie file: {e}")
        return None

COOKIE_FILE = get_cookie_file()

def create_job(video_url, format_type):
    """Create a new download job"""
    job_id = f"{time.time_ns()}-{hash(video_url)}"
    job = {
        "id": job_id,
        "url": video_url,
        "format": format_type,
        "status": "queued",
        "progress": 0,
        "error": None,
        "created_at": datetime.now().isoformat(),
        "file_path": None
    }
    jobs[job_id] = job
    job_queue.put(job_id)
    return job_id

def get_job_status(job_id):
    """Get job status"""
    return jobs.get(job_id)

def download_worker():
    """Background worker process"""
    logger.info("🧵 Worker started, waiting for jobs...")
    
    while True:
        try:
            job_id = job_queue.get(timeout=5)
            job = jobs.get(job_id)
            
            if not job:
                continue
                
            logger.info(f"📥 Processing job {job_id}: {job['url']}")
            job["status"] = "processing"
            job["progress"] = 10
            
            # Build yt-dlp command
            cmd = [
                "yt-dlp",
                "--no-playlist",
                "--no-warnings",
                "--progress",
                "--newline",
                "--format", "bestaudio",
                "--extract-audio",
                "--audio-format", job["format"],
                "--audio-quality", "0",
                "-o", f"{DOWNLOAD_DIR}/{job_id}.%(ext)s",
                job["url"]
            ]
            
            # Add cookies if available
            if COOKIE_FILE:
                cmd.extend(["--cookies", COOKIE_FILE])
                logger.info("🍪 Using cookies for this job")
            
            # Add headers to mimic browser
            cmd.extend([
                "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "--add-header", "Accept: audio/mp4,audio/*;q=0.9,*/*;q=0.8",
                "--add-header", "Accept-Language: en-US,en;q=0.9",
                "--add-header", "Origin: https://www.youtube.com",
                "--add-header", "Referer: https://www.youtube.com"
            ])
            
            job["progress"] = 30
            job["status"] = "processing"
            
            # Run yt-dlp
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd="."
            )
            
            job["progress"] = 60
            
            stdout, stderr = process.communicate(timeout=180)  # 3 minute timeout
            
            if process.returncode != 0:
                error_msg = stderr.strip() or stdout.strip() or "Unknown error"
                job["status"] = "error"
                job["error"] = error_msg
                logger.error(f"❌ Job {job_id} failed: {error_msg}")
                job["progress"] = 0
                continue
            
            # Find the downloaded file
            downloaded_files = list(DOWNLOAD_DIR.glob(f"{job_id}.*"))
            if not downloaded_files:
                job["status"] = "error"
                job["error"] = "No file downloaded"
                logger.error(f"❌ Job {job_id} failed: No file found")
                job["progress"] = 0
                continue
            
            # Rename to .mp3 if needed
            if job["format"] == "mp3":
                for f in downloaded_files:
                    if f.suffix.lower() in ['.webm', '.m4a', '.aac']:
                        new_name = f.with_suffix('.mp3')
                        f.rename(new_name)
                        downloaded_files = [new_name]
                        break
            
            job["file_path"] = str(downloaded_files[0])
            job["status"] = "finished"
            job["progress"] = 100
            logger.info(f"✅ Job {job_id} completed: {downloaded_files[0].name}")
            
        except Queue.Empty:
            continue
        except Exception as e:
            logger.error(f"❌ Worker error: {e}")
            if job_id and job_id in jobs:
                jobs[job_id]["status"] = "error"
                jobs[job_id]["error"] = str(e)
                jobs[job_id]["progress"] = 0

def serve_file(job_id):
    """Serve the downloaded file"""
    job = jobs.get(job_id)
    if not job or job["status"] != "finished":
        return None, "not_ready"
    
    file_path = job["file_path"]
    if not file_path or not os.path.exists(file_path):
        return None, "file_not_found"
    
    return file_path, "ready"

# Cleanup old files
def cleanup_worker():
    """Periodically clean up old files"""
    while True:
        try:
            time.sleep(300)  # Every 5 minutes
            now = datetime.now()
            for job_id, job in list(jobs.items()):
                if job["status"] == "finished":
                    created = datetime.fromisoformat(job["created_at"])
                    if (now - created) > timedelta(minutes=10):
                        if job["file_path"] and os.path.exists(job["file_path"]):
                            os.remove(job["file_path"])
                            logger.info(f"🗑️ Deleted old file: {job['file_path']}")
                        del jobs[job_id]
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

# Start worker threads
def start_workers():
    worker_thread = Thread(target=download_worker, daemon=True)
    worker_thread.start()
    cleanup_thread = Thread(target=cleanup_worker, daemon=True)
    cleanup_thread.start()
    logger.info("✅ Worker threads started")
