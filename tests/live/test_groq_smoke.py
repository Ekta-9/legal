import json

import pytest

from app.llm.groq_client import GroqClient
from app.llm.simplify import simplify_clauses
from app.models.schemas import Clause


@pytest.mark.live
@pytest.mark.asyncio
async def test_real_groq_call_simplifies_one_clause():
    """Opt-in smoke test — a single real Groq API call to confirm wiring.
    Run with: pytest -m live
    Requires GROQ_API_KEY in .env.
    """
    client = GroqClient()
    clause = Clause(id="clause_1", text="The party of the first part shall indemnify the party of the second part.")

    simplified, dropped = await simplify_clauses([clause], client)

    assert dropped == []
    assert len(simplified) == 1
    assert simplified[0].simplified.strip() != ""
    print(json.dumps(simplified[0].model_dump(), indent=2))
