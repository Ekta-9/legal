# Implementation Log

Running record of what was actually built per phase, decisions/deviations from `PLANNING.md`/`ROADMAP.md`, and test coverage. Updated as each phase lands. This is the "what and why" companion to the git history — read this before `git log` if you want the reasoning, not just the diff.

---

## Phase 0 — Setup & Skeleton ✅

**Built:** folder structure per spec, `.gitignore`, `.env.example`, `app/config.py` (pydantic-settings), `app/constants.py` (disclaimer text, batch size, retry limits), FastAPI app with `/health`, static frontend mount, `pytest.ini` (excludes `@pytest.mark.live` by default), `conftest.py` with an `async_client` fixture (httpx `ASGITransport`, no real server needed).

**Decisions:**
- `pytest.ini` bakes `addopts = -m "not live"` in directly, so the bare `pytest` command matches the roadmap's stated default without anyone needing to remember the flag.
- Git repo initialized at this point (was previously untracked).

**Tests:** `test_health.py` — 1 test.

---

## Phase 1 — Parsing & Clause Splitting ✅

**Built:**
- `app/parsing/clause_splitter.py` — rule-based: numbered clauses (`1.`, `1.1`, `2)`) and `SECTION`/`ARTICLE` headings are boundaries; blank-line paragraph split is the fallback when no numbering exists.
- `app/parsing/extract.py` — PyMuPDF for PDF, python-docx for DOCX, UTF-8 passthrough for `.txt`. `parse_document(filename, content) -> list[Clause]` is the Phase 1 deliverable end-to-end.
- Multi-column PDF handling: `get_text("blocks")`, cluster by `x0` against page-midpoint, sort `(column, y0)` — reads each column top-to-bottom in full before moving to the next, rather than interleaving by row.
- Scanned/no-text-layer PDFs raise `NoTextLayerError` (subclass of `ExtractionError`) — a clean, caught error, not a crash. OCR is explicitly out of scope.
- `app/models/schemas.py` — `Clause` (later grew to hold all shared Pydantic models, see Phase 3 note).
- `tests/fixtures/generate_fixtures.py` — generates the binary PDF/DOCX fixtures programmatically (PyMuPDF `insert_text`/`insert_image`, python-docx) so fixtures are reproducible from source rather than hand-crafted binaries. Fixture content was designed together with the splitter rules, then golden values (`golden_clauses.json`) were derived by running the real extractor and eyeballing the output — matches the roadmap's own stated verification method for this phase.

**Deviation from ROADMAP wording:** the fixture/golden-value generation was necessarily "design content + rules together, then lock golden values by running the code," not strictly test-first, since no fixtures existed yet to write goldens against blind.

**Tests:** `test_clause_splitter.py`, `test_extract.py` (incl. multi-column non-interleave assertion, scanned-PDF clean-error assertion), `test_schemas.py` — 16 tests.

---

## Phase 2 — Groq Client & Simplification ✅

**Built:**
- `app/llm/groq_client.py` — `GroqClient` wraps the Groq SDK behind an **injectable `call_fn`** (`async (prompt: str) -> str`), so every test supplies a fake and never touches the network or needs an API key. `asyncio.Semaphore` caps concurrency; exponential backoff (`base * 2^(attempt-1)`) retries on `groq.RateLimitError` up to `GROQ_MAX_RETRIES`, then re-raises. `batch_items()` is a small generic list-chunking helper, reused by `simplify.py`.
- `app/llm/simplify.py` — `build_prompt()` batches 5–8 clauses into one structured-JSON request; `parse_batch_response()` **never raises** — malformed JSON, a missing `results` key, an unknown/hallucinated `clause_id`, or blank `simplified` text all degrade to "drop that clause id," never crash the batch or the document. `simplify_clauses()` runs all batches concurrently (bounded by the client's semaphore) and exposes an optional `on_batch_complete` callback so callers can stream partial progress instead of waiting for the whole document (used by the Phase 3 job pipeline).

**Decisions:**
- Self-check (faithfulness flag) is produced **in the same call** as the simplification, per `PLANNING.md` — no separate judge call yet. `verify.py` / independent judge is deferred to Phase 5, and only gets built if the eval harness actually shows hallucination.
- Dependency-inversion on `call_fn` was chosen specifically so `test_groq_client.py` could construct real `groq.RateLimitError` instances (which require an `httpx.Response`) without needing a live Groq account — the fake raises the real exception type, so the retry logic is tested against the real contract, not a stand-in.

**Tests:** `test_groq_client.py` (batching, semaphore ceiling respected under concurrent load, 429→backoff→retry with **patched `sleep_fn`** so the test is instant, exhausted-retries re-raises), `test_simplify_parsing.py` (valid / malformed / partial / hallucinated-id / blank-text — 9 tests), `live/test_groq_smoke.py` (`@pytest.mark.live`, opt-in, not run by default) — 13 default tests + 1 live.

---

## Phase 3 — Async Job Model + Frontend Polling ✅ — DEMOABLE MILESTONE

**Built:**
- `app/models/schemas.py` grew to hold **all** shared Pydantic/enum models (`Clause`, `SimplifiedClause`, `JobStatus`, `UploadResponse`, `JobResultResponse`) — moved `SimplifiedClause` here from `simplify.py` specifically to avoid a circular import between `schemas.py` and `simplify.py` once job-result responses needed to reference it.
- `app/jobs/manager.py` — `JobManager`, in-memory `dict[str, Job]` (module-level singleton `job_manager`), per PLANNING.md's stated MVP tradeoff. Lifecycle: `PENDING → PROCESSING → DONE` or `→ FAILED` with an error message.
- `app/jobs/pipeline.py` — glues extract → split → simplify into the background task (`process_document`). Uses `simplify_clauses(..., on_batch_complete=...)` so completed clauses land in the job **as each batch finishes**, not all at once — this is what makes the frontend's progressive rendering real rather than cosmetic. The LLM client is swappable via `get_client()`/`set_client()` (module-level, test/DI hook) rather than constructed inline, so integration tests can inject the fake client without any network access or API key.
- `app/routers/documents.py` — `POST /api/documents` accepts **either** a multipart file upload or a pasted-text form field (`PLANNING.md`'s "upload or paste"), returns `{job_id}` immediately, kicks off `BackgroundTasks`.
- `app/routers/results.py` — `GET /api/documents/{job_id}` returns status + clauses completed so far; 404 on unknown job id.
- `frontend/`: real upload form (file or paste), `script.js` polls every 1.5s and renders each clause as a card (original | simplified side-by-side columns) the moment it arrives, with a `⚠` badge when `self_check` is true. Disclaimer is a persistent static header element, not tied to job state.

**Decisions/notes:**
- Verified manually against the **actual running server** (not just mocked tests): static assets serve, upload → poll → result round-trips, and — importantly — with no `GROQ_API_KEY` configured, a real upload reaches `status: "failed"` with a readable error (`"simplification failed: Connection error."`) instead of crashing the server or hanging. This confirms `pipeline.py`'s exception handling works against a real network failure, not just the mocked-failure path in tests.
- Full **live** simplification (actually calling Groq and seeing real simplified text in the browser) is still unverified — pending a `GROQ_API_KEY`. Everything else about the spine is demoable today with the fake/mocked client.
- The `⚠` badge and "retry-once-then-badge" verification-failure *behavior* (`PLANNING.md` §3) is only partially here: the badge renders if `self_check` is true, but the **one-retry-before-badging rule** is explicitly a Phase 5 task (`verify.py`) and hasn't been built yet — right now a flagged clause is badged immediately, no retry.

**Tests:** `test_job_manager.py` (lifecycle incl. failure path), `integration/test_upload_flow.py` (paste + file upload, 400 on empty, 404 on unknown job, scanned-PDF → failed status), `integration/test_end_to_end.py` (PDF and DOCX fixtures through the full pipeline) — 12 tests. **Suite total: 41 passed, 1 deselected (live).**

---

## Known gaps carried forward (not bugs, just not-yet-built)

- No cache (Phase 4) — every clause hits the LLM every run, even on identical re-uploads.
- No retry-then-badge verification UX (Phase 5) — badge shows immediately on `self_check=true`, no single retry first.
- No readability scoring (Phase 5).
- In-memory job store — restarting the server loses all job history (documented MVP tradeoff, SQLite is the noted upgrade path).
- No real live Groq call has been verified yet — pending API key.
