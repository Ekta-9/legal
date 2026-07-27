import enum

from pydantic import BaseModel


class Clause(BaseModel):
    id: str
    heading: str | None = None
    text: str


class ReadabilityScore(BaseModel):
    original_grade: float
    simplified_grade: float
    delta: float  # positive = simplification reads at an easier grade level


class GlossaryMatch(BaseModel):
    term: str
    definition: str
    score: float


class SimplifiedClause(BaseModel):
    id: str
    heading: str | None = None
    original: str
    simplified: str
    self_check: bool  # True => model flagged this simplification as low-confidence/risky
    readability: ReadabilityScore | None = None
    glossary_matches: list[GlossaryMatch] = []


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class UploadResponse(BaseModel):
    job_id: str


class JobResultResponse(BaseModel):
    job_id: str
    status: JobStatus
    total_clauses: int
    completed: list[SimplifiedClause]
    error: str | None = None
