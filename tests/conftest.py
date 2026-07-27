import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.jobs import pipeline as pipeline_module
from app.main import app


@pytest.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class FakeGroqClient:
    """Canned-response fake for `GroqClient.complete`. Echoes every clause in
    the batch back as a trivially "simplified" (uppercased) string unless the
    batch was seeded with a custom response via `responses_by_prompt`.
    """

    def __init__(self):
        self.prompts: list[str] = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        clauses = json.loads(prompt.split("Clauses:\n", 1)[1].split("\n\nRespond", 1)[0])
        results = [
            {
                "clause_id": c["clause_id"],
                "simplified": f"SIMPLIFIED: {c['text']}",
                "self_check": False,
            }
            for c in clauses
        ]
        return json.dumps({"results": results})


@pytest.fixture
def fake_groq():
    return FakeGroqClient()


@pytest.fixture
def with_fake_groq(fake_groq):
    """Points the background job pipeline at the fake client so integration
    tests never touch the network or need a real API key.
    """
    pipeline_module.set_client(fake_groq)
    yield fake_groq
    pipeline_module.set_client(None)
