import asyncio
from pathlib import Path

import pytest

from app.models.schemas import JobStatus

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


async def _poll_until_done(async_client, job_id: str, timeout: float = 5.0) -> dict:
    elapsed = 0.0
    interval = 0.05
    while elapsed < timeout:
        response = await async_client.get(f"/api/documents/{job_id}")
        data = response.json()
        if data["status"] in (JobStatus.DONE.value, JobStatus.FAILED.value):
            return data
        await asyncio.sleep(interval)
        elapsed += interval
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


@pytest.mark.asyncio
async def test_pdf_fixture_flows_through_full_pipeline(async_client, with_fake_groq):
    content = (FIXTURES_DIR / "sample_clean.pdf").read_bytes()

    upload = await async_client.post(
        "/api/documents",
        files={"file": ("sample_clean.pdf", content, "application/pdf")},
    )
    assert upload.status_code == 200
    job_id = upload.json()["job_id"]

    result = await _poll_until_done(async_client, job_id)

    assert result["status"] == JobStatus.DONE.value
    assert result["total_clauses"] == 3
    completed = {c["id"]: c for c in result["completed"]}
    assert set(completed) == {"clause_1", "clause_2", "clause_3"}
    assert completed["clause_1"]["heading"] == "1. Definitions"
    # original clause text is preserved verbatim alongside the simplification
    assert "signatory" in completed["clause_1"]["original"]
    assert completed["clause_1"]["simplified"].startswith("SIMPLIFIED:")
    # readability score rides along in the API response
    readability = completed["clause_1"]["readability"]
    assert readability is not None
    assert set(readability) == {"original_grade", "simplified_grade", "delta"}
    # glossary_matches is always present (possibly empty), never missing from the response
    assert isinstance(completed["clause_1"]["glossary_matches"], list)


@pytest.mark.asyncio
async def test_glossary_matches_ride_through_the_api_response(async_client, with_fake_groq):
    from app.jobs import pipeline as pipeline_module

    class FakeGlossaryStore:
        def search(self, text: str) -> list[dict]:
            return [{"term": "Definitions", "definition": "Terms defined for use in this contract.", "score": 0.9}]

    pipeline_module.set_glossary_store(FakeGlossaryStore())
    try:
        content = (FIXTURES_DIR / "sample_clean.pdf").read_bytes()
        upload = await async_client.post(
            "/api/documents",
            files={"file": ("sample_clean.pdf", content, "application/pdf")},
        )
        job_id = upload.json()["job_id"]

        result = await _poll_until_done(async_client, job_id)

        completed = {c["id"]: c for c in result["completed"]}
        matches = completed["clause_1"]["glossary_matches"]
        assert matches == [
            {"term": "Definitions", "definition": "Terms defined for use in this contract.", "score": 0.9}
        ]
    finally:
        pipeline_module.set_glossary_store(None)


@pytest.mark.asyncio
async def test_docx_fixture_flows_through_full_pipeline(async_client, with_fake_groq):
    content = (FIXTURES_DIR / "sample.docx").read_bytes()

    upload = await async_client.post(
        "/api/documents",
        files={
            "file": (
                "sample.docx",
                content,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    job_id = upload.json()["job_id"]

    result = await _poll_until_done(async_client, job_id)

    assert result["status"] == JobStatus.DONE.value
    assert result["total_clauses"] == 3
