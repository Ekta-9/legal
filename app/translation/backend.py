import importlib.util

from app.config import settings

# Which translator the server uses (TRANSLATION_BACKEND):
#   "groq"  (default) the Groq model that simplifies; needs only GROQ_API_KEY, so it runs on small hosts
#   "local" the NLLB model on this machine; needs requirements-translation.txt and ~3 GB of RAM in use
BACKENDS = ("groq", "local")


def _local_packages_installed() -> bool:
    return all(importlib.util.find_spec(package) is not None for package in ("torch", "transformers", "sentencepiece"))


def translation_available() -> bool:
    """Whether this server can translate; the page hides Hindi/Marathi when it can't."""
    if not settings.translation_enabled or settings.translation_backend not in BACKENDS:
        return False
    if settings.translation_backend == "local":
        return _local_packages_installed()
    return bool(settings.groq_api_key)
