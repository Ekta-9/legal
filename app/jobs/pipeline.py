from typing import Protocol

from app.cache.store import CacheStore
from app.jobs.manager import job_manager
from app.llm.groq_client import GroqClient
from app.llm.simplify import ClauseCache, CompletesPrompts, simplify_clauses
from app.llm.verify import make_verifier
from app.models.schemas import GlossaryMatch, JobStatus, SimplifiedClause
from app.parsing.extract import ExtractionError, parse_document


class GlossarySearch(Protocol):
    def search(self, text: str) -> list[dict]: ...


_client: CompletesPrompts | None = None
_cache_store: ClauseCache | None = None
_glossary_store: GlossarySearch | None = None


def get_client() -> CompletesPrompts:
    global _client
    if _client is None:
        _client = GroqClient()
    return _client


def set_client(client: CompletesPrompts | None) -> None:
    """Test/DI hook — swap in a fake client, or pass None to reset to the
    lazily-constructed real GroqClient on next use.
    """
    global _client
    _client = client


def get_cache_store() -> ClauseCache:
    global _cache_store
    if _cache_store is None:
        _cache_store = CacheStore()
    return _cache_store


def set_cache_store(store: ClauseCache | None) -> None:
    """Test/DI hook — swap in an isolated cache store, or pass None to reset
    to the lazily-constructed default (data/cache.sqlite3) on next use.
    """
    global _cache_store
    _cache_store = store


def get_glossary_store() -> GlossarySearch:
    global _glossary_store
    if _glossary_store is None:
        from app.rag.glossary_store import GlossaryStore  # lazy: avoid paying the torch import cost unless glossary is actually used

        _glossary_store = GlossaryStore()
    return _glossary_store


def set_glossary_store(store: GlossarySearch | None) -> None:
    """Test/DI hook — swap in a fake/lightweight glossary store, or pass
    None to reset to the lazily-constructed default on next use.
    """
    global _glossary_store
    _glossary_store = store


async def process_document(job_id: str, filename: str, content: bytes) -> None:
    job_manager.set_status(job_id, JobStatus.PROCESSING)

    try:
        clauses = parse_document(filename, content)
    except ExtractionError as e:
        job_manager.fail(job_id, str(e))
        return

    job_manager.set_total(job_id, len(clauses))
    if not clauses:
        job_manager.set_status(job_id, JobStatus.DONE)
        return

    def on_batch_complete(simplified: list[SimplifiedClause], dropped: list[str]) -> None:
        if not simplified:
            return
        glossary_store = get_glossary_store()
        enriched = [
            s.model_copy(
                update={
                    "glossary_matches": [
                        GlossaryMatch(**match) for match in glossary_store.search(s.original)
                    ]
                }
            )
            for s in simplified
        ]
        job_manager.add_completed(job_id, enriched)

    client = get_client()
    try:
        await simplify_clauses(
            clauses,
            client,
            on_batch_complete=on_batch_complete,
            cache=get_cache_store(),
            verify_fn=make_verifier(client),
        )
    except Exception as e:
        job_manager.fail(job_id, f"simplification failed: {e}")
        return

    job_manager.set_status(job_id, JobStatus.DONE)
