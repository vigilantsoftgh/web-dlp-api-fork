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
    Extract audio URL from YouTube with fallback formats.
    """
    try:
        log_info(f"🎵 Extracting audio URL for job {job_id}: {url}")
        update_job_status(job_id, status='processing', progress=10)
        
        # ============ FIX: Try multiple format selectors ============
        format_selectors = [
            # Try M4A first (best for iOS)
            "bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]/bestaudio",
            # Try any audio format
            "bestaudio",
            # Fallback to any format (might be video with audio)
            "best[acodec^=mp4a]/best",
            # Last resort: any format
            "best"
        ]
        
        audio_url = None
        audio_format = None
        info = None
        last_error = None
        
        for fmt_selector in format_selectors:
            try:
                log_info(f"🔄 Trying format: {fmt_selector}")
                
                cmd = [
                    'yt-dlp',
                    '--no-playlist',
                    '--no-warnings',
                    '--quiet',
                    '--dump-json',
                    '--format', fmt_selector,
                    '--extractor-args', 'youtube:player_client=web,android;skip=hls,dash,livestream;player_skip=webpage,configs',
                    '--sleep-interval', '3',
                    '--retries', '5',
                    '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                    '--add-header', 'Accept: audio/mp4,audio/*;q=0.9,*/*;q=0.8',
                    '--add-header', 'Accept-Language: en-US,en;q=0.9',
                    '--add-header', 'Origin: https://www.youtube.com',
                    '--add-header', 'Referer: https://www.youtube.com',
                    url
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                
                if result.returncode != 0:
                    last_error = result.stderr
                    log_info(f"⚠️ Format {fmt_selector} failed, trying next...")
                    continue
                
                # Try to parse JSON
                try:
                    info = json.loads(result.stdout)
                except json.JSONDecodeError:
                    last_error = "Invalid JSON response"
                    continue
                
                # Extract URL from response
                audio_url = None
                
                # Check direct URL
                if info.get('url'):
                    audio_url = info['url']
                    audio_format = info.get('ext', 'm4a')
                    break
                
                # Check requested_downloads
                if not audio_url and info.get('requested_downloads'):
                    for download in info['requested_downloads']:
                        if download.get('url'):
                            audio_url = download.get('url')
                            audio_format = download.get('ext', 'm4a')
                            break
                
                # Check formats
                if not audio_url and info.get('formats'):
                    for f in info['formats']:
                        if f.get('url') and (f.get('acodec') != 'none' or f.get('vcodec') == 'none'):
                            audio_url = f.get('url')
                            audio_format = f.get('ext', 'm4a')
                            break
                
                if audio_url:
                    log_info(f"✅ Found audio URL with format: {fmt_selector}")
                    break
                    
            except subprocess.TimeoutExpired:
                last_error = "Timeout"
                continue
            except Exception as e:
                last_error = str(e)
                continue
        
        if not audio_url:
            log_error(f"❌ No audio URL found after trying all formats")
            update_job_status(job_id, status='error', error=f'No audio URL found: {last_error}', progress=0)
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
