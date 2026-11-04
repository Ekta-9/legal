import enum

from pydantic import BaseModel


class ClauseContext(BaseModel):
    """Material retrieved from elsewhere in the same document that the model
    needs to interpret a clause correctly — see app/rag/document_context.py.
    """

    parties: list[str] = []
    definitions: dict[str, str] = {}  # defined term -> the sentence that defines it
    referenced_sections: dict[str, str] = {}  # section number -> that section's text


class Clause(BaseModel):
    id: str
    heading: str | None = None
    text: str
    context: ClauseContext | None = None


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
    failed: bool = False  # True => the model never returned this clause; `simplified` is empty
    readability: ReadabilityScore | None = None
    glossary_matches: list[GlossaryMatch] = []


class ClauseOutline(BaseModel):
    """A clause as split from the document, before simplification — lets the
    frontend show every original up front, including ones that later fail.
    """

    id: str
    heading: str | None = None
    text: str


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
    clauses: list[ClauseOutline] = []
    completed: list[SimplifiedClause]
    error: str | None = None


class TranslateRequest(BaseModel):
    text: str
    target_lang: str  # short code, e.g. "hi" or "mr" — see translation.nllb.SUPPORTED_LANGUAGES


class TranslateResponse(BaseModel):
    translated_text: str
