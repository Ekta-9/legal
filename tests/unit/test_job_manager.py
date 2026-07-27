from app.jobs.manager import JobManager
from app.models.schemas import JobStatus, SimplifiedClause


def test_create_job_starts_pending():
    manager = JobManager()
    job = manager.create()
    assert job.status == JobStatus.PENDING
    assert job.total_clauses == 0
    assert job.completed == []
    assert manager.get(job.id) is job


def test_job_lifecycle_pending_to_processing_to_done():
    manager = JobManager()
    job = manager.create()

    manager.set_status(job.id, JobStatus.PROCESSING)
    manager.set_total(job.id, 2)
    assert manager.get(job.id).status == JobStatus.PROCESSING
    assert manager.get(job.id).total_clauses == 2

    clause = SimplifiedClause(id="clause_1", original="orig", simplified="simple", self_check=False)
    manager.add_completed(job.id, [clause])
    assert manager.get(job.id).completed == [clause]

    manager.set_status(job.id, JobStatus.DONE)
    assert manager.get(job.id).status == JobStatus.DONE


def test_job_failure_path_sets_status_and_error():
    manager = JobManager()
    job = manager.create()
    manager.set_status(job.id, JobStatus.PROCESSING)

    manager.fail(job.id, "extraction failed: no text layer")

    failed_job = manager.get(job.id)
    assert failed_job.status == JobStatus.FAILED
    assert failed_job.error == "extraction failed: no text layer"


def test_get_unknown_job_returns_none():
    manager = JobManager()
    assert manager.get("does-not-exist") is None


def test_jobs_are_isolated_by_id():
    manager = JobManager()
    job_a = manager.create()
    job_b = manager.create()
    manager.set_status(job_a.id, JobStatus.DONE)
    assert manager.get(job_b.id).status == JobStatus.PENDING
