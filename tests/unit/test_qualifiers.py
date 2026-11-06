import pytest

from app.llm.qualifiers import lost_qualifiers

CAP = (
    "Notwithstanding anything to the contrary in this Agreement, neither party's liability shall exceed the fees "
    "paid in the 12 months preceding the claim."
)


@pytest.mark.parametrize(
    "simplified",
    [
        "Regardless of anything else in this Agreement, neither party's liability can exceed the fees paid in the last 12 months.",
        "Even if another clause says otherwise, neither party's liability can exceed the fees paid in the last 12 months.",
        "This cap overrides the rest of the Agreement: neither party is liable for more than the last 12 months' fees.",
    ],
)
def test_override_kept_in_other_words(simplified):
    assert lost_qualifiers(CAP, simplified) == []


@pytest.mark.parametrize(
    "simplified",
    [
        # the 20b reversal seen in tests/eval runs: now the rest of the contract overrides the cap
        "Except as otherwise stated, neither party's liability can exceed the fees paid in the last 12 months.",
        # the override simply dropped
        "Neither party's liability can exceed the fees paid in the last 12 months.",
    ],
)
def test_override_lost_or_reversed(simplified):
    assert lost_qualifiers(CAP, simplified) == ['the override ("notwithstanding")']


def test_prohibition_must_survive():
    original = "The Licensee shall not sub-let the Premises."
    assert lost_qualifiers(original, "Priya Shah may not sublet the flat.") == []
    assert lost_qualifiers(original, "Priya Shah can't sublet the flat.") == []
    assert lost_qualifiers(original, "Priya Shah may sublet the flat.") == ['the prohibition ("shall not")']


def test_exclusivity_must_survive():
    original = "Service Credits shall be the Customer's sole and exclusive remedy for missed service levels."
    assert lost_qualifiers(original, "Service credits are the Customer's only remedy for missed service levels.") == []
    assert lost_qualifiers(original, "The Customer gets service credits for missed service levels.") == [
        'the exclusivity ("sole" / "exclusive")'
    ]


def test_clauses_without_these_qualifiers_are_never_flagged():
    assert lost_qualifiers("The Tenant pays rent monthly.", "Rent is paid every month.") == []


def test_if_capable_of_remedy_must_survive():
    original = (
        "Either party may terminate if the other commits a material breach which, if capable of remedy, "
        "is not remedied within 30 days of notice."
    )
    kept = "Either party can end it if the other seriously breaches it and, if the breach can be fixed, does not fix it within 30 days."
    dropped = "Either party can end it if the other seriously breaches it and does not fix it within 30 days."
    assert lost_qualifiers(original, kept) == []
    assert lost_qualifiers(original, dropped) == ['the condition ("if capable of remedy")']
