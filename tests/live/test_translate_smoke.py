import pytest

from app.translation.nllb import translate


@pytest.mark.slow
def test_real_nllb_translation_to_hindi_and_marathi():
    """Opt-in — loads the real ~2.4GB NLLB-200-distilled-600M model.
    Run with: pytest -m slow
    No quality gate (PLANNING.md explicitly defers automated MT quality
    assertions) — this only confirms the wiring produces non-empty output.
    """
    text = "Either party may terminate this agreement with 30 days written notice."

    hindi = translate(text, "hi")
    marathi = translate(text, "mr")

    assert hindi.strip() != ""
    assert marathi.strip() != ""
    assert hindi != marathi
    print("HINDI:", hindi)
    print("MARATHI:", marathi)
