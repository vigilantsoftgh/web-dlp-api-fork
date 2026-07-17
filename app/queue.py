# app/queue.py
import time
import logging

logger = logging.getLogger("web-dlp")

# In-memory job storage
jobs = {}

def create_job(job_id: str, url: str, format: str):
    """Create a new job"""
    jobs[job_id] = {
        "id": job_id,
        "url": url,
        "format": format,
        "status": "queued",
        "progress": 0,
        "error": None,
        "filename": None,
        "result_data": None,
        "created_at": time.time()
    }
    return job_id

def get_job(job_id: str):
    """Get job by ID"""
    return jobs.get(job_id)

def update_job_status(job_id: str, status: str = None, progress: int = None, 
                      error: str = None, filename: str = None, result_data: dict = None):
    """Update job status"""
    if job_id not in jobs:
        logger.warning(f"Job {job_id} not found")
        return
    
    job = jobs[job_id]
    if status is not None:
        job["status"] = status
    if progress is not None:
        job["progress"] = progress
    if error is not None:
        job["error"] = error
    if filename is not None:
        job["filename"] = filename
    if result_data is not None:
        job["result_data"] = result_data
