# app/worker.py
import os
import sys
import time
import subprocess
import json
from pathlib import Path
from app.queue import update_job_status
from app.utils import log_info, log_error
import logging

logger = logging.getLogger("web-dlp")


def download_video(job_id: str, url: str, format: str):
    """
    Extract audio URL from YouTube with simplified format selection.
    """
    try:
        log_info(f"🎵 Extracting audio URL for job {job_id}: {url}")
        update_job_status(job_id, status='processing', progress=10)
        
        # ============ SIMPLIFIED: Just get the best audio available ============
        cmd = [
            'yt-dlp',
            '--no-playlist',
            '--no-warnings',
            '--quiet',
            '--dump-json',
            '--format', 'bestaudio/best',  # Simple: best audio, or best overall
            '--extractor-args', 'youtube:player_client=web,android;skip=hls,dash,livestream',
            '--sleep-interval', '2',
            '--retries', '5',
            '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            '--add-header', 'Accept: audio/mp4,audio/*;q=0.9,*/*;q=0.8',
            '--add-header', 'Accept-Language: en-US,en;q=0.9',
            '--add-header', 'Origin: https://www.youtube.com',
            '--add-header', 'Referer: https://www.youtube.com',
            url
        ]
        
        update_job_status(job_id, status='processing', progress=30)
        log_info(f"📋 Running: {' '.join(cmd)}")
        
        # Execute yt-dlp
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        
        if result.returncode != 0:
            # Fallback: try without format selector
            log_info("🔄 Retrying without format selector...")
            fallback_cmd = [
                'yt-dlp',
                '--no-playlist',
                '--no-warnings',
                '--quiet',
                '--dump-json',
                '--extractor-args', 'youtube:player_client=web,android;skip=hls,dash,livestream',
                '--sleep-interval', '2',
                '--retries', '3',
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                url
            ]
            result = subprocess.run(fallback_cmd, capture_output=True, text=True, timeout=120)
            
            if result.returncode != 0:
                error_msg = result.stderr or "Failed to get audio URL"
                log_error(f"❌ Job {job_id} failed: {error_msg}")
                update_job_status(job_id, status='error', error=error_msg, progress=0)
                return
        
        # Parse JSON
        try:
            info = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            log_error(f"❌ Failed to parse JSON: {e}")
            update_job_status(job_id, status='error', error='Invalid response from YouTube', progress=0)
            return
        
        # Extract audio URL
        audio_url = None
        audio_format = None
        
        # Method 1: Direct URL
        if info.get('url'):
            audio_url = info['url']
            audio_format = info.get('ext', 'mp4')
        
        # Method 2: Check requested_downloads
        if not audio_url and info.get('requested_downloads'):
            for download in info['requested_downloads']:
                if download.get('url'):
                    audio_url = download.get('url')
                    audio_format = download.get('ext', 'mp4')
                    break
        
        # Method 3: Check formats
        if not audio_url and info.get('formats'):
            # Try to find audio-only first
            for f in info['formats']:
                if f.get('url') and f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                    audio_url = f.get('url')
                    audio_format = f.get('ext', 'm4a')
                    break
            
            # If no audio-only, get any format with audio
            if not audio_url:
                for f in info['formats']:
                    if f.get('url') and f.get('acodec') != 'none':
                        audio_url = f.get('url')
                        audio_format = f.get('ext', 'mp4')
                        break
        
        # Method 4: Last resort - get any URL from any format
        if not audio_url and info.get('formats'):
            for f in info['formats']:
                if f.get('url'):
                    audio_url = f.get('url')
                    audio_format = f.get('ext', 'mp4')
                    break
        
        if not audio_url:
            log_error(f"❌ No audio URL found")
            update_job_status(job_id, status='error', error='No audio URL found', progress=0)
            return
        
        update_job_status(job_id, status='processing', progress=80)
        
        # Create result data
        is_audio_only = audio_format in ['m4a', 'aac', 'mp3', 'opus', 'webm'] and 'video' not in info.get('format', '')
        
        result_data = {
            'url': audio_url,
            'format': audio_format,
            'title': info.get('title', 'YouTube Audio'),
            'author': info.get('channel', info.get('uploader', 'YouTube')),
            'duration': int(info.get('duration', 0)),
            'thumbnail': info.get('thumbnail', ''),
            'videoId': info.get('id', ''),
            'isStream': True,
            'isAudioOnly': is_audio_only
        }
        
        update_job_status(
            job_id,
            status='finished',
            progress=100,
            result_data=result_data
        )
        log_info(f"✅ Job {job_id} completed: Audio URL extracted ({audio_format})")
        
    except subprocess.TimeoutExpired:
        log_error(f"⏰ Job {job_id} timed out")
        update_job_status(job_id, status='error', error='Timeout getting audio URL', progress=0)
    except Exception as e:
        log_error(f"❌ Job {job_id} error: {str(e)}")
        update_job_status(job_id, status='error', error=str(e), progress=0)
