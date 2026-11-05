import pytest

from tests.eval.rag_eval import score_split


@pytest.mark.parametrize("split", ["eval", "dev", "heldout", "cuad"])
def test_retrieval_scores_do_not_regress(split):
    """Runs tests/eval/rag_eval.py's hand-labelled retrieval evaluation. All
    three splits currently score 100%; a change that lowers any of them
    should be a deliberate decision, with rag_gold.json updated to match.
    """
    score = score_split(split)

    assert score.problems == []
    assert score.definitions.precision == score.definitions.recall == 1.0
    assert score.sections.precision == score.sections.recall == 1.0
    assert score.parties_correct == score.parties_total


def test_fresh_cuad_contracts_keep_definitions_and_parties():
    """cuad_fresh's two section misses come from the splitter merging
    sub-clauses 1.2 and 3.9 into their neighbours, not from retrieval, so
    only definitions and parties are held exact here."""
    score = score_split("cuad_fresh")

    assert score.definitions.precision == score.definitions.recall == 1.0
    assert score.parties_correct == score.parties_total and score.parties_wrong == 0
