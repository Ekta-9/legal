from app.jobs.manager import job_manager
from app.llm.groq_client import GroqClient
from app.llm.simplify import CompletesPrompts, simplify_clauses
from app.models.schemas import JobStatus, SimplifiedClause
from app.parsing.extract import ExtractionError, parse_document

_client: CompletesPrompts | None = None


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
        if simplified:
            job_manager.add_completed(job_id, simplified)

    try:
        await simplify_clauses(clauses, get_client(), on_batch_complete=on_batch_complete)
    except Exception as e:
        job_manager.fail(job_id, f"simplification failed: {e}")
        return

    job_manager.set_status(job_id, JobStatus.DONE)
