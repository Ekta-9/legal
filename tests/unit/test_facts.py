import pytest

from app.llm.facts import missing_numbers


@pytest.mark.parametrize(
    "original, simplified",
    [
        ("The Tenant shall pay Rs. 15,000/- on or before the 5th day of each month.", "Pay Rs 15000 by the fifth of every month."),
        ("within thirty (30) days of 05/03/2026", "within 30 days of 5 March 2026"),
        ("Pay 1,50,000 with interest at 1.5% per annum.", "Pay one lakh fifty thousand plus 1.50% a year."),
        ("A notice period of 2 months applies.", "You must give two months' notice."),
        ("4.2 The term is 11 months.", "The term is eleven months."),  # the clause's own number isn't a fact
        ("The deposit is refundable.", "You get the deposit back."),
    ],
)
def test_reworded_numbers_count_as_kept(original, simplified):
    assert missing_numbers(original, simplified) == []


def test_changed_and_dropped_numbers_are_reported_as_written_in_the_original():
    original = "Pay INR 50,000 by 31 March 2026, subject to Section 7."
    simplified = "Pay INR 5,000 by March 2026."

    assert missing_numbers(original, simplified) == ["50,000", "31", "7"]


def test_each_missing_number_is_reported_once():
    assert missing_numbers("Pay 10 now and 10 later.", "Pay now and later.") == ["10"]
