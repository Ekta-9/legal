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


@pytest.mark.asyncio
async def test_retrieved_document_context_reaches_the_llm_prompt(async_client, with_fake_groq):
    import json

    text = (
        'This Agreement is between Acme Ltd (the "Provider") and John Doe (the "Client").\n\n'
        '1. Definitions\n"Fee" means INR 50,000 per month.\n\n'
        "2. Payment\nThe Client shall pay the Fee, subject to Section 3.\n\n"
        "3. Disputes\nDisputed invoices are not payable until resolved."
    )
    upload = await async_client.post("/api/documents", data={"text": text})
    result = await _poll_until_done(async_client, upload.json()["job_id"])

    assert result["status"] == JobStatus.DONE.value
    items = json.loads(with_fake_groq.prompts[0].split("Clauses:\n", 1)[1].split("\n\nRespond", 1)[0])
    payment = next(i for i in items if i["clause_id"] == "clause_3")
    assert payment["context"]["parties"] == ["Provider: Acme Ltd", "Client: John Doe"]
    assert payment["context"]["definitions"] == {"Fee": '"Fee" means INR 50,000 per month'}
    assert "Disputed invoices" in payment["context"]["referenced_sections"]["3"]


@pytest.mark.asyncio
async def test_clause_the_model_never_returns_is_reported_as_failed_with_its_original(async_client, with_fake_groq):
    import json

    from app.jobs import pipeline as pipeline_module

    class NeverReturnsClauseTwo:
        def __init__(self):
            self.prompts = []

        async def complete(self, prompt):
            self.prompts.append(prompt)
            items = json.loads(prompt.split("Clauses:\n", 1)[1].split("\n\nRespond", 1)[0])
            return json.dumps(
                {"results": [{"clause_id": c["clause_id"], "simplified": "ok", "self_check": False} for c in items if c["clause_id"] != "clause_2"]}
            )

    pipeline_module.set_client(NeverReturnsClauseTwo())
    upload = await async_client.post("/api/documents", data={"text": "1. Rent\nPay monthly.\n\n2. Term\nOne year.\n\n3. Notice\nIn writing."})
    result = await _poll_until_done(async_client, upload.json()["job_id"])

    assert result["status"] == JobStatus.DONE.value
    assert [c["id"] for c in result["clauses"]] == ["clause_1", "clause_2", "clause_3"]
    completed = {c["id"]: c for c in result["completed"]}
    assert set(completed) == {"clause_1", "clause_2", "clause_3"}  # nothing silently vanishes
    assert completed["clause_2"]["failed"] is True
    assert completed["clause_2"]["original"] == "2. Term\nOne year."
    assert completed["clause_1"]["failed"] is False


@pytest.mark.asyncio
async def test_unexpected_error_fails_the_job_instead_of_leaving_it_processing(async_client, with_fake_groq, monkeypatch):
    from app.jobs import pipeline as pipeline_module

    def boom(text):
        raise RuntimeError("splitter bug")

    monkeypatch.setattr(pipeline_module, "split_clauses", boom)
    upload = await async_client.post("/api/documents", data={"text": "1. Rent\nPay monthly."})
    result = await _poll_until_done(async_client, upload.json()["job_id"])

    assert result["status"] == JobStatus.FAILED.value
    assert "splitter bug" not in result["error"]  # internals aren't shown to the user


class _RaisesForEveryBatch:
    def __init__(self, error):
        self.error = error

    async def complete(self, prompt):
        raise self.error


def _groq_error(error_cls, status):
    import httpx

    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return error_cls("secret request details", response=httpx.Response(status, request=request), body=None)


@pytest.mark.asyncio
async def test_invalid_api_key_fails_the_job_with_a_plain_explanation(async_client, with_fake_groq):
    import groq

    from app.jobs import pipeline as pipeline_module

    pipeline_module.set_client(_RaisesForEveryBatch(_groq_error(groq.AuthenticationError, 401)))
    upload = await async_client.post("/api/documents", data={"text": "1. Rent\nPay monthly.\n\n2. Term\nOne year."})
    result = await _poll_until_done(async_client, upload.json()["job_id"])

    assert result["status"] == JobStatus.FAILED.value
    assert "GROQ_API_KEY" in result["error"]
    assert "secret request details" not in result["error"]


@pytest.mark.asyncio
async def test_one_failing_batch_does_not_fail_the_whole_document(async_client, with_fake_groq):
    import json

    from app.jobs import pipeline as pipeline_module

    class FailsWhenClauseThreeIsAsked:
        async def complete(self, prompt):
            items = json.loads(prompt.split("Clauses:\n", 1)[1].split("\n\nRespond", 1)[0])
            if any(c["clause_id"] == "clause_7" for c in items):
                raise RuntimeError("connection reset")
            return json.dumps({"results": [{"clause_id": c["clause_id"], "simplified": "ok", "self_check": False} for c in items]})

    pipeline_module.set_client(FailsWhenClauseThreeIsAsked())
    # 8 clauses = two batches of 6 and 2; the second batch fails
    text = "\n\n".join(f"{n}. Heading {n}\nBody text {n}." for n in range(1, 9))
    upload = await async_client.post("/api/documents", data={"text": text})
    result = await _poll_until_done(async_client, upload.json()["job_id"])

    assert result["status"] == JobStatus.DONE.value
    failed = {c["id"]: c["failed"] for c in result["completed"]}
    assert failed == {f"clause_{n}": n >= 7 for n in range(1, 9)}


@pytest.mark.asyncio
async def test_glossary_failure_does_not_fail_the_job(async_client, with_fake_groq):
    from app.jobs import pipeline as pipeline_module

    class BrokenGlossary:
        def search(self, text):
            raise OSError("model download failed")

    pipeline_module.set_glossary_store(BrokenGlossary())
    try:
        upload = await async_client.post("/api/documents", data={"text": "1. Rent\nPay monthly."})
        result = await _poll_until_done(async_client, upload.json()["job_id"])
    finally:
        pipeline_module.set_glossary_store(None)

    assert result["status"] == JobStatus.DONE.value
    assert result["completed"][0]["simplified"].startswith("SIMPLIFIED:")
    assert result["completed"][0]["glossary_matches"] == []


@pytest.mark.asyncio
async def test_documents_over_the_clause_limit_are_rejected_before_any_llm_call(async_client, with_fake_groq, monkeypatch):
    from app.jobs import pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, "MAX_CLAUSES", 2)
    upload = await async_client.post("/api/documents", data={"text": "1. A\nOne.\n\n2. B\nTwo.\n\n3. C\nThree."})
    result = await _poll_until_done(async_client, upload.json()["job_id"])

    assert result["status"] == JobStatus.FAILED.value
    assert "limit is 2" in result["error"]
    assert with_fake_groq.prompts == []
