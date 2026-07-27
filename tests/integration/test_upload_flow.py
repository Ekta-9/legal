import asyncio

import pytest

from app.models.schemas import JobStatus


async def _poll_until_done(async_client, job_id: str, timeout: float = 5.0) -> dict:
    elapsed = 0.0
    interval = 0.05
    while elapsed < timeout:
        response = await async_client.get(f"/api/documents/{job_id}")
        assert response.status_code == 200
        data = response.json()
        if data["status"] in (JobStatus.DONE.value, JobStatus.FAILED.value):
            return data
        await asyncio.sleep(interval)
        elapsed += interval
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


@pytest.mark.asyncio
async def test_paste_text_upload_returns_job_id(async_client, with_fake_groq):
    response = await async_client.post(
        "/api/documents", data={"text": "1. First clause.\n\n2. Second clause."}
    )
    assert response.status_code == 200
    body = response.json()
    assert "job_id" in body and body["job_id"]


@pytest.mark.asyncio
async def test_upload_then_poll_reaches_done_with_simplified_clauses(async_client, with_fake_groq):
    upload = await async_client.post(
        "/api/documents", data={"text": "1. First clause.\n\n2. Second clause."}
    )
    job_id = upload.json()["job_id"]

    result = await _poll_until_done(async_client, job_id)

    assert result["status"] == JobStatus.DONE.value
    assert result["total_clauses"] == 2
    assert len(result["completed"]) == 2
    assert all(c["simplified"].startswith("SIMPLIFIED:") for c in result["completed"])


@pytest.mark.asyncio
async def test_empty_upload_returns_400(async_client, with_fake_groq):
    response = await async_client.post("/api/documents", data={"text": "   "})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_unknown_job_id_returns_404(async_client):
    response = await async_client.get("/api/documents/does-not-exist")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_scanned_pdf_upload_reaches_failed_status(async_client, with_fake_groq):
    from pathlib import Path

    fixture_path = Path(__file__).resolve().parent.parent / "fixtures" / "sample_scanned.pdf"
    content = fixture_path.read_bytes()

    upload = await async_client.post(
        "/api/documents",
        files={"file": ("sample_scanned.pdf", content, "application/pdf")},
    )
    job_id = upload.json()["job_id"]

    result = await _poll_until_done(async_client, job_id)

    assert result["status"] == JobStatus.FAILED.value
    assert result["error"]
