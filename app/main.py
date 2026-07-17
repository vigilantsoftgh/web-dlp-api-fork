# app/main.py
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os
import time
import uuid
import json
from pathlib import Path
import logging

from app.worker import download_video
from app.queue import create_job, get_job, jobs
from app.utils import is_valid_youtube_url, cleanup_old_files

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
    format: Optional[str] = "mp3"

@app.get("/")
async def health_check():
    return {"status": "YT-API running"}

@app.post("/request")
async def create_download(request: DownloadRequest, background_tasks: BackgroundTasks):
    """Create a new download job"""
    if not is_valid_youtube_url(request.url):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
    
    job_id = str(uuid.uuid4())
    create_job(job_id, request.url, request.format)
    background_tasks.add_task(download_video, job_id, request.url, request.format)
    
    return {"job_id": job_id, "status": "queued"}

@app.get("/status")
async def get_status(id: str):
    """Get job status"""
    job = get_job(id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    response = {
        "status": job.get("status"),
        "progress": job.get("progress", 0),
        "error": job.get("error"),
        "filename": job.get("filename")
    }
    
    if job.get("result_data"):
        response["result"] = job.get("result_data")
    
    return response

@app.get("/result")
async def get_result(id: str):
    """Get the result (audio URL)"""
    job = get_job(id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.get("status") != "finished":
        return JSONResponse(
            status_code=400,
            content={"error": "not_ready", "status": job.get("status")}
        )
    
    if job.get("result_data"):
        return JSONResponse(
            status_code=200,
            content=job.get("result_data")
        )
    
    raise HTTPException(status_code=404, detail="Result not found")
