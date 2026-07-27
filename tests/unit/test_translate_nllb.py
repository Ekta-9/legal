import pytest

from app.translation.nllb import SUPPORTED_LANGUAGES, UnsupportedLanguageError, translate


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
