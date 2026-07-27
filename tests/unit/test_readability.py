from app.scoring.readability import flesch_kincaid_grade, readability_delta

COMPLEX_CLAUSE = (
    "The aforementioned party shall, notwithstanding any provision herein "
    "to the contrary, indemnify and hold harmless the counterparty from and "
    "against any and all claims, liabilities, and causes of action arising "
    "hereunder."
)
SIMPLE_CLAUSE = "You agree to cover any losses the other side has because of this deal."


def test_empty_text_scores_zero():
    assert flesch_kincaid_grade("") == 0.0
    assert flesch_kincaid_grade("   \n  ") == 0.0


def test_complex_text_scores_higher_grade_than_simple_text():
    assert flesch_kincaid_grade(COMPLEX_CLAUSE) > flesch_kincaid_grade(SIMPLE_CLAUSE)


def test_readability_delta_is_positive_when_simplification_is_easier():
    result = readability_delta(COMPLEX_CLAUSE, SIMPLE_CLAUSE)
    assert result["delta"] > 0
    assert result["original_grade"] > result["simplified_grade"]


def test_readability_delta_is_negative_when_simplification_is_harder():
    result = readability_delta(SIMPLE_CLAUSE, COMPLEX_CLAUSE)
    assert result["delta"] < 0


def test_readability_delta_handles_empty_original():
    result = readability_delta("", SIMPLE_CLAUSE)
    assert result["original_grade"] == 0.0
    assert result["delta"] == -result["simplified_grade"]


def test_readability_delta_zero_when_identical_text():
    result = readability_delta(SIMPLE_CLAUSE, SIMPLE_CLAUSE)
    assert result["delta"] == 0.0
