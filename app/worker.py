"""
Background worker process for downloading videos using yt-dlp.
"""
import os
import sys
import time
import subprocess
import threading
import json
from pathlib import Path
from datetime import datetime, timedelta
from app.queue import update_job_status
from app.utils import log_info, log_error
import logging

logger = logging.getLogger("web-dlp")

DOWNLOADS_DIR = Path(__file__).parent / "downloads"

# Cookie setup
def get_cookie_file():
    cookie_string = os.environ.get('YOUTUBE_COOKIES')
    if not cookie_string:
        logger.warning("⚠️ No YOUTUBE_COOKIES environment variable found")
        return None
    
    cookie_file = DOWNLOADS_DIR / "cookies.txt"
    try:
        # Convert to Netscape format
        cookie_pairs = [c.strip() for c in cookie_string.split(';') if c.strip()]
        with open(cookie_file, 'w') as f:
            f.write("# Netscape HTTP Cookie File\n")
            f.write("# This is a generated file! Do not edit.\n")
            for cookie in cookie_pairs:
                if '=' in cookie:
                    name, value = cookie.split('=', 1)
                    expiry = int(time.time()) + 31536000  # 1 year
                    f.write(f".youtube.com\tTRUE\t/\tFALSE\t{expiry}\t{name}\t{value}\n")
        logger.info("✅ Cookie file created successfully")
        return str(cookie_file)
    except Exception as e:
        logger.error(f"❌ Error creating cookie file: {e}")
        return None

COOKIE_FILE = get_cookie_file()


def download_video(job_id: str, url: str, format: str):
    """
    Download video or audio using yt-dlp.
    
    Args:
        job_id: Unique job identifier
        url: YouTube video URL
        format: Output format (mp3 or mp4)
    """
    try:
        logger.info(f"Starting download for job {job_id}: {url} ({format})")
        update_job_status(job_id, status='processing', progress=10)
        
        # Ensure downloads directory exists
        DOWNLOADS_DIR.mkdir(exist_ok=True)
        
        # Determine output filename
        if format == 'mp3':
            output_filename = f"{job_id}.mp3"
            output_path = DOWNLOADS_DIR / output_filename
            
            # yt-dlp command for audio extraction
            cmd = [
                'yt-dlp',
                '--extract-audio',
                '--audio-format', 'mp3',
                '--audio-quality', '192K',
                '--output', str(output_path),
                '--no-playlist',
                '--quiet',
                '--no-warnings',
            ]
            
            # Add cookies if available
            if COOKIE_FILE:
                cmd.extend(['--cookies', COOKIE_FILE])
                logger.info("🍪 Using cookies for audio extraction")
            
            # Add headers to mimic browser
            cmd.extend([
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                '--add-header', 'Accept: audio/mp4,audio/*;q=0.9,*/*;q=0.8',
                '--add-header', 'Accept-Language: en-US,en;q=0.9',
                '--add-header', 'Origin: https://www.youtube.com',
                '--add-header', 'Referer: https://www.youtube.com',
                '--add-header', 'Sec-Fetch-Mode: navigate',
                '--add-header', 'Sec-Fetch-Site: none',
                '--add-header', 'Sec-Fetch-User: ?1',
            ])
            
            cmd.append(url)
            
        else:  # mp4
            output_filename = f"{job_id}.mp4"
            output_path = DOWNLOADS_DIR / output_filename
            
            # yt-dlp command for video download (720p or best)
            cmd = [
                'yt-dlp',
                '--format', 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best',
                '--merge-output-format', 'mp4',
                '--output', str(output_path),
                '--no-playlist',
                '--quiet',
                '--no-warnings',
            ]
            
            # Add cookies if available
            if COOKIE_FILE:
                cmd.extend(['--cookies', COOKIE_FILE])
                logger.info("🍪 Using cookies for video extraction")
            
            # Add headers to mimic browser
            cmd.extend([
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                '--add-header', 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                '--add-header', 'Accept-Language: en-US,en;q=0.9',
                '--add-header', 'Origin: https://www.youtube.com',
                '--add-header', 'Referer: https://www.youtube.com',
                '--add-header', 'Sec-Fetch-Mode: navigate',
                '--add-header', 'Sec-Fetch-Site: none',
                '--add-header', 'Sec-Fetch-User: ?1',
            ])
            
            cmd.append(url)
        
        update_job_status(job_id, status='processing', progress=30)
        logger.info(f"📋 Running command: {' '.join(cmd)}")
        
        # Execute yt-dlp
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode != 0:
            error_msg = result.stderr or "Download failed"
            logger.error(f"❌ Job {job_id} failed: {error_msg}")
            update_job_status(
                job_id,
                status='error',
                error=error_msg,
                progress=0
            )
            return
        
        update_job_status(job_id, status='processing', progress=90)
        
        # Verify file exists
        if not output_path.exists():
            logger.error(f"❌ Job {job_id}: File not found after download")
            update_job_status(
                job_id,
                status='error',
                error='File not created',
                progress=0
            )
            return
        
        # Mark as finished
        update_job_status(
            job_id,
            status='finished',
            progress=100,
            filename=output_filename
        )
        logger.info(f"✅ Job {job_id} completed successfully: {output_filename}")
        
    except subprocess.TimeoutExpired:
        logger.error(f"⏰ Job {job_id} timed out")
        update_job_status(
            job_id,
            status='error',
            error='Download timeout (5 minutes)',
            progress=0
        )
    except Exception as e:
        logger.error(f"❌ Job {job_id} error: {str(e)}")
        update_job_status(
            job_id,
            status='error',
            error=str(e),
            progress=0
        )


# Keep the original import structure
# The download_video function is called directly by FastAPI BackgroundTasks.
