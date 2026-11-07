import pytest

from app.translation.nllb import SUPPORTED_LANGUAGES, UnsupportedLanguageError, split_sentences, translate


def test_supported_languages_are_hindi_and_marathi():
    assert SUPPORTED_LANGUAGES == {"hi": "hin_Deva", "mr": "mar_Deva"}


def test_unsupported_target_lang_raises_without_touching_the_model():
    # if this test hangs or tries to download a model, translate() is
    # checking target_lang AFTER loading the model instead of before
    with pytest.raises(UnsupportedLanguageError):
        translate("Some text.", "xx")


def test_empty_text_returns_empty_string_without_touching_the_model():
    assert translate("", "hi") == ""
    assert translate("   ", "mr") == ""


def test_split_sentences_keeps_every_sentence():
    text = "The Tenant pays rent monthly. Late payment costs 2%; disputes go to arbitration.\nNotice must be written!"
    assert split_sentences(text) == [
        "The Tenant pays rent monthly.",
        "Late payment costs 2%;",
        "disputes go to arbitration.",
        "Notice must be written!",
    ]


def test_split_sentences_does_not_break_after_abbreviations():
    text = "Pay Rs. 15,000 to Acme Pvt. Ltd. by the 7th. See e.g. clause 4."
    assert split_sentences(text) == ["Pay Rs. 15,000 to Acme Pvt. Ltd. by the 7th.", "See e.g. clause 4."]


def test_concurrent_first_requests_load_the_model_once_and_never_generate_in_parallel(monkeypatch):
    """Regression: 23 clauses translating at once each loaded their own ~2.4GB
    model copy and crashed the server ("Failed to fetch" in the browser).
    """
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    from app.translation import nllb

    loads = []
    active = 0
    max_active = 0
    counter_lock = threading.Lock()

    class FakeTokenizer:
        src_lang = None

        def __call__(self, sentences, **kwargs):
            return {"sentences": sentences}

        def convert_tokens_to_ids(self, token):
            return 1

        def batch_decode(self, generated, skip_special_tokens):
            return [f"T({s})" for s in generated]

    class FakeModel:
        def generate(self, sentences, **kwargs):
            nonlocal active, max_active
            with counter_lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.01)
            with counter_lock:
                active -= 1
            return sentences

    def fake_load():
        loads.append(1)
        time.sleep(0.05)
        return FakeTokenizer(), FakeModel()

    monkeypatch.setattr(nllb, "_load", fake_load)
    monkeypatch.setattr(nllb, "_loaded", None)

    with ThreadPoolExecutor(max_workers=23) as pool:
        results = list(pool.map(lambda i: translate(f"Clause {i}. Second sentence.", "mr"), range(23)))

    assert len(loads) == 1
    assert max_active == 1
    assert results[5] == "T(Clause 5.) T(Second sentence.)"
