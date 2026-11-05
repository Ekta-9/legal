import pytest

from tests.eval.rag_eval import score_split


@pytest.mark.parametrize("split", ["eval", "dev", "heldout", "cuad", "cuad_fresh"])
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

