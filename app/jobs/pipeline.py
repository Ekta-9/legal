import logging
from typing import Protocol

import groq

from app.cache.store import CacheStore
from app.constants import MAX_CLAUSES
from app.jobs.manager import job_manager
from app.llm.groq_client import GroqClient
from app.llm.simplify import ClauseCache, CompletesPrompts, simplify_clauses
from app.llm.verify import make_verifier
from app.models.schemas import ClauseOutline, GlossaryMatch, JobStatus, SimplifiedClause
from app.parsing.clause_splitter import is_heading_only, split_clauses
from app.parsing.extract import ExtractionError, extract
from app.rag.document_context import attach_context
from app.rag.glossary_store import GlossaryStore

logger = logging.getLogger(__name__)

GENERIC_FAILURE = "Something went wrong while processing the document. Please try again."


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
        _glossary_store = GlossaryStore()
    return _glossary_store


def set_glossary_store(store: GlossarySearch | None) -> None:
    """Test/DI hook — swap in a fake/lightweight glossary store, or pass
    None to reset to the lazily-constructed default on next use.
    """
    global _glossary_store
    _glossary_store = store


def user_message(error: Exception) -> str:
    """What the reader is told when the model can't be reached. Raw exception
    text can contain request details, so it only goes to the log.
    """
    if isinstance(error, groq.AuthenticationError) or (
        isinstance(error, groq.GroqError) and not isinstance(error, groq.APIError)
    ):
        # a bare GroqError is what the SDK raises when no API key is set at all
        return "The Groq API key is missing or invalid. Set GROQ_API_KEY in .env and restart the server."
    if isinstance(error, groq.RateLimitError):
        return "Groq's rate limit was reached. Wait a minute and try again."
    if isinstance(error, groq.APIConnectionError):
        return "Could not reach Groq. Check your internet connection and try again."
    if isinstance(error, groq.APIStatusError):
        return "Groq returned an error. Please try again in a few minutes."
    return GENERIC_FAILURE


def _glossary_matches(texts: list[str]) -> list[list[GlossaryMatch]]:
    store = get_glossary_store()
    return [[GlossaryMatch(**match) for match in store.search(text)] for text in texts]


async def process_document(job_id: str, filename: str, content: bytes) -> None:
    try:
        await _process_document(job_id, filename, content)
    except Exception:
        # last line of defence: an unexpected error must end the job, never leave it "processing" forever
        logger.exception("Job %s failed unexpectedly", job_id)
        job_manager.fail(job_id, GENERIC_FAILURE)


async def _process_document(job_id: str, filename: str, content: bytes) -> None:
    job_manager.set_status(job_id, JobStatus.PROCESSING)

    try:
        text = extract(filename, content)
    except ExtractionError as e:
        logger.info("Job %s: could not extract %s: %s", job_id, filename, e)
        job_manager.fail(job_id, str(e))
        return
    clauses = split_clauses(text)
    logger.info("Job %s: %s split into %d clauses", job_id, filename, len(clauses))
    if len(clauses) > MAX_CLAUSES:
        job_manager.fail(
            job_id,
            f"This document has {len(clauses)} clauses; the limit is {MAX_CLAUSES}. "
            "Split it into smaller parts and upload them separately.",
        )
        return

    try:
        # built from the full text, not the clauses, so parties and definitions anywhere in the document are found
        clauses = attach_context(text, clauses)
    except Exception:
        # retrieval only improves the prompt; simplify without it rather than fail the job
        logger.exception("Job %s: context retrieval failed, continuing without it", job_id)

    outline = [
        ClauseOutline(id=c.id, heading=c.heading, text=c.text, context=c.context, heading_only=is_heading_only(c.text))
        for c in clauses
    ]
    job_manager.set_clauses(job_id, outline)
    headings = {c.id for c in outline if c.heading_only}
    clauses = [c for c in clauses if c.id not in headings]  # titles have nothing to simplify
    if not clauses:
        job_manager.set_status(job_id, JobStatus.DONE)
        return
    clauses_by_id = {c.id: c for c in clauses}

    async def on_batch_complete(simplified: list[SimplifiedClause], dropped: list[str]) -> None:
        enriched = simplified
        if simplified:
            try:
                matches = _glossary_matches([s.original for s in simplified])
                enriched = [s.model_copy(update={"glossary_matches": m}) for s, m in zip(simplified, matches)]
            except Exception:
                # glossary terms are a display extra; show the simplified clauses without them
                logger.exception("Job %s: glossary lookup failed", job_id)
        # still missing after the retry: report them instead of letting them silently vanish
        failed = [
            SimplifiedClause(
                id=clause_id,
                heading=clauses_by_id[clause_id].heading,
                original=clauses_by_id[clause_id].text,
                simplified="",
                self_check=True,
                failed=True,
            )
            for clause_id in dropped
        ]
        job_manager.add_completed(job_id, enriched + failed)

    errors: list[Exception] = []
    try:
        client = get_client()
    except Exception as e:
        logger.exception("Job %s: could not create the Groq client", job_id)
        job_manager.fail(job_id, user_message(e))
        return

    simplified, _dropped = await simplify_clauses(
        clauses,
        client,
        on_batch_complete=on_batch_complete,
        cache=get_cache_store(),
        verify_fn=make_verifier(client),
        on_batch_error=errors.append,
    )

    if errors and not simplified:
        # nothing came back at all: say why, rather than a page of "not simplified" rows
        job_manager.fail(job_id, user_message(errors[0]))
        return
    logger.info("Job %s: done, %d of %d clauses simplified", job_id, len(simplified), len(clauses))
    job_manager.set_status(job_id, JobStatus.DONE)
