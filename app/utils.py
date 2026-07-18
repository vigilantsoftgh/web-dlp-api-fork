# app/utils.py
import re
import time
from collections import defaultdict
from typing import Dict
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('web-dlp')

# Rate limiting - increased limits
rate_limit_storage: Dict[str, list] = defaultdict(list)
RATE_LIMIT_WINDOW = 60  # 1 minute
RATE_LIMIT_MAX = 20  # Increased from 5 to 20 requests per minute


def is_valid_youtube_url(url: str) -> bool:
    """Validate if the URL is a valid YouTube URL."""
    youtube_patterns = [
        r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+',
        r'(https?://)?(www\.)?youtube\.com/watch\?v=[\w-]+',
        r'(https?://)?(www\.)?youtu\.be/[\w-]+',
        r'(https?://)?(www\.)?youtube\.com/shorts/[\w-]+',
        r'(https?://)?(www\.)?youtube\.com/embed/[\w-]+',
        r'(https?://)?(www\.)?youtube\.com/v/[\w-]+',
        r'(https?://)?(www\.)?youtube\.com/playlist\?list=[\w-]+',
    ]
    
    for pattern in youtube_patterns:
        if re.match(pattern, url):
            return True
    
    return False


# Alias for compatibility
validate_url = is_valid_youtube_url


def check_rate_limit(ip_address: str) -> bool:
    """Check if the IP has exceeded the rate limit."""
    current_time = time.time()
    
    # Clean old entries
    rate_limit_storage[ip_address] = [
        timestamp for timestamp in rate_limit_storage[ip_address]
        if current_time - timestamp < RATE_LIMIT_WINDOW
    ]
    
    # Check limit
    if len(rate_limit_storage[ip_address]) >= RATE_LIMIT_MAX:
        return False
    
    # Add new request
    rate_limit_storage[ip_address].append(current_time)
    return True


def get_file_age(timestamp: float) -> float:
    """Calculate the age of a file in seconds."""
    return time.time() - timestamp


def cleanup_old_files(jobs, downloads_dir):
    """Clean up old files (older than 10 minutes)"""
    try:
        current_time = time.time()
        for job_id, job in list(jobs.items()):
            if job.get('status') == 'finished':
                filename = job.get('filename')
                if filename:
                    file_path = downloads_dir / filename
                    if file_path.exists() and current_time - file_path.stat().st_mtime > 600:
                        try:
                            file_path.unlink()
                            logger.info(f"🗑️ Deleted old file: {file_path.name}")
                        except Exception as e:
                            logger.warning(f"⚠️ Could not delete file: {e}")
                
                # Clean up expired jobs (older than 1 hour)
                if current_time - job.get('created_at', 0) > 3600:
                    del jobs[job_id]
    except Exception as e:
        logger.error(f"❌ Cleanup error: {e}")


def log_info(message: str):
    """Log info message."""
    logger.info(message)


def log_error(message: str):
    """Log error message."""
    logger.error(message)


def log_warning(message: str):
    """Log warning message."""
    logger.warning(message)
