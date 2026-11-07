import json
from pathlib import Path

import pytest

from app.parsing.clause_splitter import is_heading_only, is_signature_block, split_clauses

EVAL_SET = json.loads((Path(__file__).resolve().parent.parent / "eval" / "eval_set.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("document", EVAL_SET["documents"], ids=lambda d: d["name"])
def test_every_clause_in_the_eval_set_has_expectations(document):
    """Keeps tests/eval/eval_set.json in step with the splitter: a heading that
    stops matching would silently drop that clause's concept checks. Titles and
    signature lines are never simplified, so they have none.
    """
    headings = [
        c.heading for c in split_clauses(document["text"]) if not is_heading_only(c.text) and not is_signature_block(c.text)
    ]
    assert headings == list(document["expect"])


@pytest.mark.parametrize("document", EVAL_SET["documents"], ids=lambda d: d["name"])
def test_context_and_ambiguity_expectations_name_real_clauses(document):
    headings = {c.heading for c in split_clauses(document["text"])}
    assert set(document.get("expect_context", {})) <= headings
    assert set(document.get("expect_unsure", [])) <= headings
