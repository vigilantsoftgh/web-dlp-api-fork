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
    Extract audio URL from YouTube using Innertube API.
    """
    try:
        log_info(f"🎵 Extracting audio URL for job {job_id}: {url}")
        update_job_status(job_id, status='processing', progress=10)
        
        # ============ FIX: Use Innertube API with multiple clients ============
        cmd = [
            'yt-dlp',
            '--no-playlist',
            '--no-warnings',
            '--quiet',
            '--dump-json',
            '--format', 'bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]/bestaudio[protocol^=http]/bestaudio',
            '--extractor-args', 'youtube:player_client=android,web;skip=hls,dash,livestream;player_skip=webpage,configs',
            '--sleep-interval', '5',
            '--max-sleep-interval', '10',
            '--retries', '10',
            '--fragment-retries', '10',
            '--extractor-retries', '10',
            '--user-agent', 'Mozilla/5.0 (Linux; Android 13; SM-S908B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36',
            '--add-header', 'Accept: application/json, text/plain, */*',
            '--add-header', 'Accept-Language: en-US,en;q=0.9',
            '--add-header', 'Origin: https://www.youtube.com',
            '--add-header', 'Referer: https://www.youtube.com',
            url
        ]
        
        update_job_status(job_id, status='processing', progress=30)
        log_info(f"📋 Running: {' '.join(cmd)}")
        
        # Execute yt-dlp
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        
        if result.returncode != 0:
            # Try alternative approach without format selector
            log_info("🔄 Retrying with alternative format...")
            alt_cmd = [
                'yt-dlp',
                '--no-playlist',
                '--no-warnings',
                '--quiet',
                '--dump-json',
                '--extractor-args', 'youtube:player_client=web;skip=hls,dash,livestream',
                '--sleep-interval', '3',
                '--retries', '5',
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                url
            ]
            result = subprocess.run(alt_cmd, capture_output=True, text=True, timeout=120)
            
            if result.returncode != 0:
                error_msg = result.stderr or "Failed to get audio URL"
                log_error(f"❌ Job {job_id} failed: {error_msg}")
                update_job_status(job_id, status='error', error=error_msg, progress=0)
                return
        
        # Parse JSON output
        try:
            info = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            log_error(f"❌ Failed to parse JSON: {e}")
            update_job_status(job_id, status='error', error='Invalid response from YouTube', progress=0)
            return
        
        # Extract audio URL - try different methods
        audio_url = None
        audio_format = None
        
        # Method 1: Check direct URL
        if info.get('url'):
            audio_url = info['url']
            audio_format = info.get('ext', 'm4a')
        
        # Method 2: Check requested_downloads
        if not audio_url and info.get('requested_downloads'):
            for download in info['requested_downloads']:
                if download.get('ext') in ['m4a', 'aac', 'mp3', 'opus']:
                    audio_url = download.get('url')
                    audio_format = download.get('ext', 'm4a')
                    break
        
        # Method 3: Check formats
        if not audio_url and info.get('formats'):
            for f in info['formats']:
                if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                    audio_url = f.get('url')
                    audio_format = f.get('ext', 'm4a')
                    break
        
        # Method 4: Try to get any URL
        if not audio_url and info.get('formats'):
            for f in info['formats']:
                if f.get('url'):
                    audio_url = f.get('url')
                    audio_format = f.get('ext', 'm4a')
                    break
        
        if not audio_url:
            log_error(f"❌ No audio URL found")
            log_error(f"Response keys: {list(info.keys())}")
            update_job_status(job_id, status='error', error='No audio URL found', progress=0)
            return
        
        update_job_status(job_id, status='processing', progress=80)
        
        # Create result data
        result_data = {
            'url': audio_url,
            'format': audio_format,
            'title': info.get('title', 'YouTube Audio'),
            'author': info.get('channel', info.get('uploader', 'YouTube')),
            'duration': int(info.get('duration', 0)),
            'thumbnail': info.get('thumbnail', ''),
            'videoId': info.get('id', ''),
            'isStream': True
        }
        
        update_job_status(
            job_id,
            status='finished',
            progress=100,
            result_data=result_data
        )
        log_info(f"✅ Job {job_id} completed: Audio URL extracted")
        
    except subprocess.TimeoutExpired:
        log_error(f"⏰ Job {job_id} timed out")
        update_job_status(job_id, status='error', error='Timeout getting audio URL', progress=0)
    except Exception as e:
        log_error(f"❌ Job {job_id} error: {str(e)}")
        update_job_status(job_id, status='error', error=str(e), progress=0)
