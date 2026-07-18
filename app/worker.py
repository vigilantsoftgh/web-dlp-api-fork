# app/worker.py - Updated to prioritize audio-only formats
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
    Extract audio URL from YouTube - prioritize audio-only formats.
    """
    try:
        log_info(f"🎵 Extracting audio URL for job {job_id}: {url}")
        update_job_status(job_id, status='processing', progress=10)
        
        # ============ FIX: Prioritize audio-only formats ============
        format_selectors = [
            # Audio-only formats (best to worst)
            "bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]/bestaudio",
            "bestaudio[ext=webm]/bestaudio[acodec^=opus]/bestaudio",
            "bestaudio[ext=aac]/bestaudio",
            "bestaudio",
            # Fallback to formats with audio (if no audio-only available)
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        ]
        
        audio_url = None
        audio_format = None
        info = None
        last_error = None
        is_audio_only = False
        
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
                    '--sleep-interval', '2',
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
                
                # Parse JSON
                try:
                    info = json.loads(result.stdout)
                except json.JSONDecodeError:
                    last_error = "Invalid JSON response"
                    continue
                
                # Extract URL - prioritize audio-only
                audio_url = None
                audio_format = None
                is_audio_only = False
                
                # Check if we got a direct URL
                if info.get('url'):
                    audio_url = info['url']
                    audio_format = info.get('ext', 'mp4')
                    # Check if it's audio-only
                    if info.get('acodec') != 'none' and info.get('vcodec') == 'none':
                        is_audio_only = True
                    break
                
                # Check requested_downloads
                if not audio_url and info.get('requested_downloads'):
                    for download in info['requested_downloads']:
                        if download.get('url'):
                            # Check if this is audio-only
                            if download.get('acodec') != 'none' and download.get('vcodec') == 'none':
                                audio_url = download.get('url')
                                audio_format = download.get('ext', 'm4a')
                                is_audio_only = True
                                break
                            # If not audio-only, store as fallback
                            if not audio_url:
                                audio_url = download.get('url')
                                audio_format = download.get('ext', 'mp4')
                                is_audio_only = False
                    
                    if audio_url:
                        break
                
                # Check formats
                if not audio_url and info.get('formats'):
                    # First try to find audio-only
                    for f in info['formats']:
                        if f.get('url') and f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                            audio_url = f.get('url')
                            audio_format = f.get('ext', 'm4a')
                            is_audio_only = True
                            break
                    
                    # If no audio-only, get any format with audio
                    if not audio_url:
                        for f in info['formats']:
                            if f.get('url') and f.get('acodec') != 'none':
                                audio_url = f.get('url')
                                audio_format = f.get('ext', 'mp4')
                                is_audio_only = False
                                break
                    
                    if audio_url:
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
            'isStream': True,
            'isAudioOnly': is_audio_only
        }
        
        update_job_status(
            job_id,
            status='finished',
            progress=100,
            result_data=result_data
        )
        log_info(f"✅ Job {job_id} completed: {'Audio-only' if is_audio_only else 'Audio+Video'} URL extracted")
        
    except subprocess.TimeoutExpired:
        log_error(f"⏰ Job {job_id} timed out")
        update_job_status(job_id, status='error', error='Timeout getting audio URL', progress=0)
    except Exception as e:
        log_error(f"❌ Job {job_id} error: {str(e)}")
        update_job_status(job_id, status='error', error=str(e), progress=0)
