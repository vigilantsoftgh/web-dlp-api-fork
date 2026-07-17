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

def download_with_retry(job_id: str, url: str, format: str, max_retries: int = 3):
    """Download with retry logic - returns M4A for iOS compatibility"""
    for attempt in range(max_retries):
        try:
            logger.info(f"🔄 Attempt {attempt + 1}/{max_retries} for job {job_id}")
            
            # ============ FIX: Use M4A instead of MP3 for iOS ============
            # Format selectors - prioritize M4A/AAC for iOS
            format_selectors = [
                "bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]/bestaudio[protocol^=http]/bestaudio",
                "bestaudio[ext=aac]/bestaudio[acodec^=mp4a]/bestaudio",
                "bestaudio/best"
            ]
            
            format_selector = format_selectors[attempt % len(format_selectors)]
            logger.info(f"📋 Using format selector: {format_selector}")
            
            # Build command with current format selector
            cmd = [
                'yt-dlp',
                '--extract-audio',
                '--audio-format', 'm4a',  # Use M4A instead of MP3
                '--audio-quality', '0',   # Best quality
                '--output', str(DOWNLOADS_DIR / f"{job_id}.%(ext)s"),
                '--no-playlist',
                '--quiet',
                '--no-warnings',
                '--format', format_selector,
                '--extractor-args', 'youtube:skip=hls,dash,livestream;player_client=web,android',
                '--sleep-interval', str(2 + attempt),
                '--retries', '10',
                '--fragment-retries', '10',
            ]
            
            # Add cookies if available
            if COOKIE_FILE:
                cmd.extend(['--cookies', COOKIE_FILE])
            
            # Add headers to mimic browser
            cmd.extend([
                '--user-agent', 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
                '--add-header', 'Accept: audio/mp4,audio/*;q=0.9,*/*;q=0.8',
                '--add-header', 'Accept-Language: en-US,en;q=0.9',
                '--add-header', 'Origin: https://www.youtube.com',
                '--add-header', 'Referer: https://www.youtube.com',
            ])
            
            cmd.append(url)
            
            logger.info(f"📋 Running command: {' '.join(cmd)}")
            
            # Execute yt-dlp
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                # Check for downloaded files
                downloaded_files = list(DOWNLOADS_DIR.glob(f"{job_id}.*"))
                if downloaded_files:
                    final_path = downloaded_files[0]
                    
                    # If it's not m4a, try to convert
                    if final_path.suffix.lower() not in ['.m4a', '.aac']:
                        logger.info(f"🔄 Converting {final_path.suffix} to M4A...")
                        try:
                            # Convert to M4A using ffmpeg
                            new_path = DOWNLOADS_DIR / f"{job_id}.m4a"
                            import subprocess as sp
                            convert_cmd = [
                                'ffmpeg', '-i', str(final_path),
                                '-acodec', 'aac', '-b:a', '192k',
                                '-movflags', '+faststart',
                                str(new_path), '-y'
                            ]
                            sp.run(convert_cmd, capture_output=True, timeout=60)
                            if new_path.exists():
                                final_path.unlink()  # Remove original
                                final_path = new_path
                                logger.info(f"✅ Converted to M4A: {final_path.name}")
                        except Exception as e:
                            logger.warning(f"⚠️ Conversion failed: {e}, using original format")
                    
                    logger.info(f"✅ Job {job_id} completed successfully on attempt {attempt + 1}")
                    update_job_status(
                        job_id,
                        status='finished',
                        progress=100,
                        filename=final_path.name
                    )
                    return True
            
            # Check for bot detection error
            if result.stderr and ('Sign in to confirm' in result.stderr or 'bot' in result.stderr.lower()):
                logger.warning(f"⚠️ Bot detection on attempt {attempt + 1}, waiting longer...")
                time.sleep(5 + (attempt * 3))
                continue
                
            # Check for other errors
            error_msg = result.stderr or "Download failed"
            logger.warning(f"⚠️ Attempt {attempt + 1} failed: {error_msg[:200]}")
            
            if attempt < max_retries - 1:
                time.sleep(3 + attempt * 2)  # Progressive backoff
                
        except subprocess.TimeoutExpired:
            logger.warning(f"⏰ Attempt {attempt + 1} timed out")
            if attempt < max_retries - 1:
                time.sleep(3)
        except Exception as e:
            logger.error(f"❌ Attempt {attempt + 1} error: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(3)
    
    # All retries failed
    logger.error(f"❌ Job {job_id} failed after {max_retries} attempts")
    update_job_status(
        job_id,
        status='error',
        error='Download failed after multiple retries',
        progress=0
    )
    return False


def download_video(job_id: str, url: str, format: str):
    """
    Download video or audio using yt-dlp with retry logic.
    """
    try:
        logger.info(f"🎵 Starting download for job {job_id}: {url} ({format})")
        update_job_status(job_id, status='processing', progress=10)
        
        # Ensure downloads directory exists
        DOWNLOADS_DIR.mkdir(exist_ok=True)
        
        # Try download with retry
        success = download_with_retry(job_id, url, format, max_retries=3)
        
        if not success:
            # Final cleanup of any partial files
            for f in DOWNLOADS_DIR.glob(f"{job_id}.*"):
                try:
                    f.unlink()
                except:
                    pass
                    
    except Exception as e:
        logger.error(f"❌ Job {job_id} fatal error: {str(e)}")
        update_job_status(
            job_id,
            status='error',
            error=str(e),
            progress=0
        )
