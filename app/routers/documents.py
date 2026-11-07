from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from app.constants import MAX_PASTE_CHARS, MAX_READER_FIELD_CHARS, MAX_UPLOAD_BYTES, SUPPORTED_EXTENSIONS
from app.jobs.manager import job_manager
from app.jobs.pipeline import process_document
from app.models.schemas import Reader, UploadResponse

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


def _reader_field(value: str | None) -> str | None:
    """A document type or role from the form, typed or chosen: one short line of text."""
    if value is None:
        return None
    value = " ".join("".join(ch if ch.isprintable() else " " for ch in value).split())
    if len(value) > MAX_READER_FIELD_CHARS:
        raise HTTPException(status_code=400, detail=f"document type and role are limited to {MAX_READER_FIELD_CHARS} characters")
    return value or None


@router.post("", response_model=UploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile | None = File(None),
    text: str | None = Form(None),
    document_type: str | None = Form(None),
    role: str | None = Form(None),
) -> UploadResponse:
    reader = Reader(document_type=_reader_field(document_type), role=_reader_field(role))
    if reader.document_type is None and reader.role is None:
        reader = None

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

    job = job_manager.create(reader)
    background_tasks.add_task(process_document, job.id, filename, content, reader)
    return UploadResponse(job_id=job.id)
