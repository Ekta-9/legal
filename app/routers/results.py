from fastapi import APIRouter, HTTPException

from app.jobs.manager import job_manager
from app.models.schemas import JobResultResponse

router = APIRouter(prefix="/api/documents", tags=["results"])


@router.get("/{job_id}", response_model=JobResultResponse)
async def get_result(job_id: str) -> JobResultResponse:
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    return JobResultResponse(
        job_id=job.id,
        status=job.status,
        total_clauses=job.total_clauses,
        completed=job.completed,
        error=job.error,
    )
