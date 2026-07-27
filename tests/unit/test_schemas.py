import pytest
from pydantic import ValidationError

from app.models.schemas import Clause


def test_clause_requires_id_and_text():
    clause = Clause(id="clause_1", text="Some clause text.")
    assert clause.id == "clause_1"
    assert clause.text == "Some clause text."
    assert clause.heading is None


def test_clause_accepts_heading():
    clause = Clause(id="clause_1", heading="1. Definitions", text="Some text.")
    assert clause.heading == "1. Definitions"


def test_clause_missing_text_raises():
    with pytest.raises(ValidationError):
        Clause(id="clause_1")
