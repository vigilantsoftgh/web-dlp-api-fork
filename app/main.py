# app/main.py
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os
import time
import uuid
from pathlib import Path
import logging

from app.worker import download_video
from app.queue import create_job, get_job, update_job_status, jobs
from app.utils import validate_url, rate_limit, cleanup_old_files

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("web-dlp")

app = FastAPI(title="web-dlp API")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Schedule cleanup thread
import threading
def cleanup_thread():
    while True:
        time.sleep(300)  # Every 5 minutes
        cleanup_old_files(jobs, Path(__file__).parent / "downloads")

threading.Thread(target=cleanup_thread, daemon=True).start()

class DownloadRequest(BaseModel):
    url: str
    format: Optional[str] = "mp3"  # Keep for compatibility

@app.get("/")
async def health_check():
    return {"status": "YT-API running"}

@app.post("/request")
async def create_download(request: DownloadRequest, background_tasks: BackgroundTasks):
    """Create a new download job"""
    # Validate URL
    if not validate_url(request.url):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    
    # Create job (always use m4a for iOS)
    job_id = str(uuid.uuid4())
    create_job(job_id, request.url, "m4a")  # Force m4a
    
    # Start download in background
    background_tasks.add_task(download_video, job_id, request.url, "m4a")
    
    return {"job_id": job_id, "status": "queued"}

@app.get("/status")
async def get_status(id: str):
    """Get job status"""
    job = get_job(id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return {
        "status": job.get("status"),
        "progress": job.get("progress", 0),
        "error": job.get("error"),
        "filename": job.get("filename")
    }

@app.get("/result")
async def download_result(id: str):
    """Download the result file"""
    job = get_job(id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.get("status") != "finished":
        return JSONResponse(
            status_code=400,
            content={"error": "not_ready", "status": job.get("status")}
        )
    
    filename = job.get("filename")
    if not filename:
        raise HTTPException(status_code=404, detail="File not found")
    
    file_path = Path(__file__).parent / "downloads" / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    # ============ FIX: Set correct MIME type for M4A ============
    if filename.endswith(".m4a") or filename.endswith(".aac"):
        media_type = "audio/mp4"
    elif filename.endswith(".mp3"):
        media_type = "audio/mpeg"
    else:
        media_type = "application/octet-stream"
    
    # ============ FIX: Add proper headers for iOS ============
    return FileResponse(
        file_path,
        media_type=media_type,
        filename=filename,
        headers={
            "Content-Type": media_type,
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-cache",
            "Content-Disposition": f'inline; filename="{filename}"',
        }
    )
