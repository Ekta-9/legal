import uuid
from dataclasses import dataclass, field

from app.models.schemas import JobStatus, SimplifiedClause


@dataclass
class Job:
    id: str
    status: JobStatus = JobStatus.PENDING
    total_clauses: int = 0
    completed: list[SimplifiedClause] = field(default_factory=list)
    error: str | None = None


class JobManager:
    """In-memory job store (MVP). Dies on process restart — acceptable for a
    demo; SQLite is the documented persistence upgrade (see PLANNING.md).
    """

    def __init__(self):
        self._jobs: dict[str, Job] = {}

    def create(self) -> Job:
        job = Job(id=str(uuid.uuid4()))
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def set_status(self, job_id: str, status: JobStatus) -> None:
        self._jobs[job_id].status = status

    def set_total(self, job_id: str, total: int) -> None:
        self._jobs[job_id].total_clauses = total

    def add_completed(self, job_id: str, clauses: list[SimplifiedClause]) -> None:
        self._jobs[job_id].completed.extend(clauses)

    def fail(self, job_id: str, error: str) -> None:
        job = self._jobs[job_id]
        job.status = JobStatus.FAILED
        job.error = error


job_manager = JobManager()
