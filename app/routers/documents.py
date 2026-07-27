from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from app.jobs.manager import job_manager
from app.jobs.pipeline import process_document
from app.models.schemas import UploadResponse

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("", response_model=UploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile | None = File(None),
    text: str | None = Form(None),
) -> UploadResponse:
    if file is not None:
        content = await file.read()
        filename = file.filename or "upload.txt"
    elif text is not None and text.strip():
        content = text.strip().encode("utf-8")
        filename = "pasted.txt"
    else:
        raise HTTPException(status_code=400, detail="provide a file or paste text")

    if not content:
        raise HTTPException(status_code=400, detail="uploaded content is empty")

    job = job_manager.create()
    background_tasks.add_task(process_document, job.id, filename, content)
    return UploadResponse(job_id=job.id)
