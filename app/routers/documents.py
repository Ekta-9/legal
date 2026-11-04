from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from app.constants import MAX_PASTE_CHARS, MAX_UPLOAD_BYTES, SUPPORTED_EXTENSIONS
from app.jobs.manager import job_manager
from app.jobs.pipeline import process_document
from app.models.schemas import UploadResponse

router = APIRouter(prefix="/api/documents", tags=["documents"])

READ_CHUNK_BYTES = 1024 * 1024


async def _read_capped(file: UploadFile) -> bytes:
    """Reads in chunks so an oversized upload is rejected without holding all of it in memory."""
    chunks = []
    size = 0
    while chunk := await file.read(READ_CHUNK_BYTES):
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"file is too large (limit {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("", response_model=UploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile | None = File(None),
    text: str | None = Form(None),
) -> UploadResponse:
    if file is not None:
        filename = file.filename or "upload.txt"
        if not filename.lower().endswith(SUPPORTED_EXTENSIONS):
            raise HTTPException(status_code=400, detail="unsupported file type: use PDF, DOCX or TXT")
        content = await _read_capped(file)
    elif text is not None and text.strip():
        if len(text) > MAX_PASTE_CHARS:
            raise HTTPException(
                status_code=413, detail=f"pasted text is too long (limit {MAX_PASTE_CHARS:,} characters)"
            )
        content = text.strip().encode("utf-8")
        filename = "pasted.txt"
    else:
        raise HTTPException(status_code=400, detail="provide a file or paste text")

    if not content:
        raise HTTPException(status_code=400, detail="uploaded content is empty")

    job = job_manager.create()
    background_tasks.add_task(process_document, job.id, filename, content)
    return UploadResponse(job_id=job.id)
