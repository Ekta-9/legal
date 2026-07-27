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
- **Update (live-verified):** with a real `GROQ_API_KEY` added to `.env`, both `pytest -m live` and a real `sample_clean.pdf` upload through the running server round-tripped successfully — real Groq calls, real simplified text, `status: "done"`, all 3 clauses returned correctly. The spine is fully demoable end-to-end, not just against mocks.
- **Quality note (not a bug):** the model occasionally rewrites a clause heading's number (e.g. "1. Definitions" came back as "2. Definitions" inside the simplified text) — a prompt-fidelity nit worth tightening later (e.g. explicitly instruct "preserve the heading number verbatim"), and exactly the kind of thing the Phase 5 eval harness (`eval/golden_set.json` + `run_eval.py`) is meant to catch systematically rather than via one-off manual spot checks.
- The `⚠` badge and "retry-once-then-badge" verification-failure *behavior* (`PLANNING.md` §3) is only partially here: the badge renders if `self_check` is true, but the **one-retry-before-badging rule** is explicitly a Phase 5 task (`verify.py`) and hasn't been built yet — right now a flagged clause is badged immediately, no retry.

**Tests:** `test_job_manager.py` (lifecycle incl. failure path), `integration/test_upload_flow.py` (paste + file upload, 400 on empty, 404 on unknown job, scanned-PDF → failed status), `integration/test_end_to_end.py` (PDF and DOCX fixtures through the full pipeline) — 12 tests. **Suite total: 41 passed, 1 deselected (live).**

---

## Phase 4 — Cache ✅

**Built:**
- `app/cache/store.py` — `CacheStore`, SQLite-backed (`data/cache.sqlite3`, gitignored). `clause_hash(text, prompt_version)` normalizes whitespace (`re.sub(r"\s+", " ", text).strip()`) before hashing, so reflowed/re-wrapped clause text with identical words still hits. Keyed on `(clause_hash, prompt_version)` — `CACHE_PROMPT_VERSION` in `constants.py` is the manual invalidation lever if the prompt or model changes.
- `simplify_clauses()` (Phase 2) grew an optional `cache: ClauseCache | None = None` parameter — fully backward compatible, default `None` preserves every existing Phase 2/3 test unchanged. When given: every clause is checked against the cache *before* batching; hits are turned directly into `SimplifiedClause`s (never touch `client`); misses are batched and sent to the LLM as before, then **write-through** to the cache per-clause as each batch's results parse successfully.
- `app/jobs/pipeline.py` — same `get_cache_store()`/`set_cache_store()` DI pattern as the LLM client, wired into `process_document`.

**Decisions:**
- SQLite over a JSON dict (both were roadmap-acceptable) — chosen to avoid concurrent-write corruption risk from multiple async batch tasks writing the same file, since batches run concurrently under the semaphore.
- Cache reads/writes are synchronous `sqlite3` calls made directly inside async functions (not wrapped in `asyncio.to_thread`) — accepted as a minor, deliberate event-loop-blocking tradeoff since local SQLite I/O is sub-millisecond and this is a portfolio MVP, not a high-throughput service. Worth revisiting only if profiling ever shows it matters.
- The `with_fake_groq` test fixture now also installs a fresh per-test `CacheStore` under pytest's `tmp_path` (and resets to `None` after) — without this, integration tests would either write to the real repo `data/` directory or silently leak cached responses between unrelated tests (both `job_manager` and the pipeline's client/cache are module-level singletons).

**Verified live (not just mocked):** uploaded the same pasted text twice through the running server with a real Groq key. Second run returned **byte-identical** simplified text — meaningful because a real LLM call is not perfectly deterministic, so identical output across two runs is strong evidence the second run hit cache and skipped Groq entirely rather than just coincidentally matching.

**Tests:** `test_cache_store.py` (hit/miss, whitespace-stable hashing, prompt-version invalidation, overwrite-on-put, cross-instance persistence — 9 tests), plus 3 new cache-integration tests added to `test_simplify_parsing.py` (cache hit skips the client entirely, cache miss writes through, a second identical run makes zero additional LLM calls). **Suite total: 53 passed, 1 deselected (live).**

---

## Phase 5 — Readability + Verification-failure UX ✅

**Built:**
- `app/scoring/readability.py` — `flesch_kincaid_grade()` wraps `textstat`, special-casing empty/whitespace text to `0.0` (the raw library returns nonsense large-negative numbers on empty input instead of raising — discovered by direct probing, not documented). `readability_delta(original, simplified)` returns `{original_grade, simplified_grade, delta}`; positive `delta` means the simplification reads at an *easier* (lower) grade level.
- `app/models/schemas.py` — new `ReadabilityScore` model; `SimplifiedClause` grew an optional `readability` field, computed once wherever a `SimplifiedClause` is actually constructed (both in `parse_batch_response` and in `simplify_clauses`'s cache-hit branch) — every clause the API returns carries a score, including ones served entirely from cache.
- `app/llm/verify.py` (new) — implements `PLANNING.md` §3's verification-failure rule exactly: `retry_flagged_clauses()` takes only the `self_check=True` subset of a batch, sends **one** retry call for just those clause ids, and replaces each with its retry result — including a retry that comes back still flagged (badge stays). If the retry response itself is malformed and drops a clause, the original flagged result is kept rather than lost — "never suppress" holds even when the retry call itself fails to parse.
- `app/llm/simplify.py` — `simplify_clauses()` grew an optional `verify_fn` hook (`Callable[[list[SimplifiedClause], list[Clause]], Awaitable[list[SimplifiedClause]]]`), invoked per-batch after parsing and before cache write-through/callback. `verify.py` is *not* imported by `simplify.py` — `pipeline.py` composes them via `verify.make_verifier(client)`, keeping the same one-directional DI pattern already used for `client` and `cache`. This means a flagged-then-retried-and-cleared clause gets cached in its final, corrected state, not its initial flagged one.
- `frontend/`: clause cards now show a readability pill (`Grade 8.6 ↓ 6.0`, green when improved / red when worsened) next to the existing ⚠ badge.

**Decisions:**
- Deliberately did **not** promote to an independent-judge `verify.py` (a second LLM call purely to check the first) — `PLANNING.md` explicitly gates that behind eval evidence of hallucination, and no eval harness (Phase 5's own optional deliverable) has been built or run yet to produce that evidence. What's built is exactly the documented default: self-check flag in the same call, one retry on failure, badge if still flagged.
- Readability computation was wired directly into `simplify.py` (importing `scoring/readability.py`) rather than kept fully decoupled via DI like `cache`/`verify` — justified because it's a pure function of two strings with zero external dependencies (no client, no I/O), unlike verify (needs an LLM call) or cache (needs a store). Coupling a zero-dependency utility costs nothing; DI is reserved for things that actually need swapping out in tests.
- The eval harness (`eval/golden_set.json` + `run_eval.py`, roadmap's non-pytest quality dashboard) was **not** built — it's an explicit "run occasionally" tool, not a spine requirement, and there's no hallucination signal yet to calibrate a rubric against. Flagged as a candidate for later if quality regressions need systematic tracking (see the Phase 3 heading-renumbering note below).

**Verified live (not just mocked):** re-uploaded `sample_clean.pdf` with the real Groq key. All 3 clauses came back `self_check: false` with real, positive readability deltas (2.4–3.6 grade levels easier) — confirms the full construction path (including the new `readability` field) works against real model output, not just the fake client's canned responses. The retry-on-flag path itself was *not* forced live (would require deliberately engineering a low-confidence clause and burning quota on a flaky, hard-to-reproduce case) — it's covered instead by 6 dedicated unit tests in `test_verify_logic.py` against a scripted fake client, which is the more reliable way to pin down exact-once-retry behavior anyway.

**Tests:** `test_readability.py` (empty input, comparative grade direction, delta sign, identical-text zero-delta — 6 tests), `test_verify_logic.py` (no-flag passthrough, flag→retry→cleared, flag→retry→still-flagged-never-suppressed, exactly-one-retry-call, malformed-retry-response keeps original, `make_verifier` binding — 6 tests), plus 2 new `simplify_clauses`-level tests confirming `verify_fn` actually runs per-batch and that its *output* (not the pre-verify text) is what gets cached. **Suite total: 67 passed, 1 deselected (live).**

---

## Phase 6 — Glossary RAG (satellite) ✅

**Built:**
- `app/rag/glossary_data/glossary.json` — 60 curated legal term/plain-definition pairs (indemnification, force majeure, arbitration, termination for cause vs. convenience, liquidated damages, etc.) — a deliberately hand-picked set rather than the roadmap's aspirational "few hundred," matching the project's own "don't gold-plate" principle. Easy to extend later; nothing in the code assumes a fixed count.
- `app/rag/embeddings.py` — thin wrapper around `sentence-transformers` (`all-MiniLM-L6-v2`, ~90MB, CPU). `get_model()` is `lru_cache`d so the model loads once per process. `embed_texts()` returns unit-normalized vectors so cosine similarity reduces to a plain dot product.
- `app/rag/glossary_store.py` — `GlossaryStore`: embeds the full glossary once at construction (`"{term}: {definition}"` per entry, so both signal sources contribute), then `search(text, top_k=3, threshold=0.35)` embeds the query and does `numpy` matrix-vector dot product against all entries — no Chroma/FAISS, exactly as specified.
- `app/models/schemas.py` — new `GlossaryMatch` model; `SimplifiedClause` grew a `glossary_matches: list[GlossaryMatch] = []` field.
- `app/jobs/pipeline.py` — `get_glossary_store()`/`set_glossary_store()` follow the same lazy-singleton DI pattern as the client/cache, **except the import of `GlossaryStore` itself is deferred inside the getter function** (not a top-level import) — this was a deliberate call to stop every test that merely imports `pipeline.py` from paying `torch`'s import cost, even when that test has nothing to do with glossary matching. `on_batch_complete` now enriches every completed clause with `glossary_store.search(clause.original)` before storing it on the job — matching against the *original* legal text, not the simplified one, since that's where the jargon actually lives.
- `frontend/`: each clause card gets a "Related terms:" row of pill-shaped tags (only rendered when matches exist) with the definition as a native `title` tooltip on hover — no JS tooltip library needed.

**Decisions:**
- Retrieval is over the **original** clause text, not the simplified text — the whole point is explaining jargon that the simplification already stripped out; searching the simplified text would often find nothing.
- `threshold=0.35` was picked empirically by probing real queries against the real glossary (see verification below) — high enough to filter out an unrelated sentence ("The cat sat on the mat...") entirely, low enough that genuinely relevant matches (0.4–0.65 range observed) survive. Not tuned against a formal eval set; a candidate for the (still-unbuilt) eval harness if false positives/negatives become a visible problem.
- Semantic search is not perfect: probing showed a force-majeure clause's top match was "Limitation of Liability" (0.423) narrowly ahead of "Force Majeure" itself (0.408) — both plausible, but not the ideal #1. Accepted as an inherent property of embedding-based fuzzy retrieval rather than something to special-case; noted here instead of silently ignored.
- The `with_fake_groq` test fixture was **not** extended to isolate the glossary store, unlike the cache — the glossary store is read-only over a static file with no per-run mutation, so sharing the real (or a test-supplied fake) instance across tests carries no cross-test pollution risk.

**Verified live (not just mocked):** re-uploaded `sample_clean.pdf` with the real Groq key and the real glossary/embedding model together. Results were qualitatively strong: the "Definitions" clause matched "Effective Date" (0.782) and "Consideration" (0.353); the "Term" clause matched "Effective Date" (0.63) and both "Termination for Cause"/"Termination for Convenience" (~0.47); the "Termination" clause matched "Termination for Cause" (0.552), "Termination for Convenience" (0.542), and "Breach of Contract" (0.452) — all semantically on-target. Also confirmed the model download (first run: ~74s) is cached afterward (subsequent load: ~4s), and that the `pkg_resources` UserWarning is not from this module (it's `textstat`, pre-existing from Phase 5) and is otherwise harmless.
- **Encoding false alarm, logged for the record:** a `curl | python -m json.tool` smoke test displayed the "Consideration" definition's em dash as mojibake (`â€”`-style garbage). Verified directly against the raw file bytes and the decoded Python string's codepoint (`0x2014`, the correct em dash) — the JSON data itself is correct UTF-8; the corruption was purely a Git Bash console-encoding rendering artifact in that one manual smoke test, not a real bug. No code change was needed.

**Tests:** `test_glossary_search.py` — top-1 correctness against a small controlled 5-term glossary for two distinct clear queries, `top_k` limiting, threshold filtering (both an impossibly-high threshold and a genuinely unrelated sentence), empty-query handling, empty-glossary-file handling, and score-descending ordering (8 tests, run against the real embedding model since it's deterministic — no LLM nondeterminism here, so no mocking needed per the roadmap's own test-bucket philosophy). Plus one new integration test asserting `glossary_matches` rides through the full API response end-to-end (using an injected fake glossary store for a deterministic assertion) and an added assertion in the existing PDF end-to-end test that the field is always present (possibly empty) on every clause. **Suite total: 76 passed, 1 deselected (live).** Full suite runtime rose from ~0.5s to ~10s — entirely the one-time embedding-model load, paid once per test process via the `lru_cache`d singleton, not per test.

---

## Phase 7 — Translation (optional satellite) ✅

**Built:**
- `app/translation/nllb.py` — thin wrapper around `facebook/nllb-200-distilled-600M` via `transformers`. `SUPPORTED_LANGUAGES` maps short codes (`hi`, `mr`) to FLORES-200 codes (`hin_Deva`, `mar_Deva`). `translate(text, target_lang, source_lang="eng_Latn")` validates `target_lang` and handles empty text **before** touching the tokenizer/model — both checks are pure and instant, so they're safe to unit-test in the default suite without loading anything heavy. The actual `transformers` import happens *inside* the `lru_cache`d `_get_tokenizer()`/`_get_model()` functions, not at module top-level, so merely importing `nllb.py` (e.g. to reference `SUPPORTED_LANGUAGES` or catch `UnsupportedLanguageError`) never pulls in the 2.4GB model.
- `app/routers/translate.py` — `POST /api/translate` ({`text`, `target_lang`} → {`translated_text`}), same lazy-singleton DI pattern as the client/cache/glossary store (`get_translate_fn()`/`set_translate_fn()`). Generation is CPU-bound and synchronous, so the handler runs it via `asyncio.to_thread` to avoid blocking the event loop for the seconds a translation takes.
- `app/models/schemas.py` — `TranslateRequest`/`TranslateResponse`.
- Deliberately **not** wired into the main job pipeline — translation happens strictly on-demand per the frontend's per-clause "Translate" button, exactly matching `PLANNING.md`'s "simplified clauses translated on demand" and "keep off the critical path." The main upload→simplify flow is completely unaffected; nothing about it got slower or more failure-prone.
- `frontend/`: each clause card gets a language `<select>` (Hindi/Marathi) + "Translate (experimental)" button. Output renders below the card with a persistent "Experimental machine translation — not reviewed for accuracy" label baked into the CSS (`::before` on `.translate-output`), so the caveat can't be forgotten or removed by accident when editing the JS.
- `pytest.ini` — added a new `slow` marker (distinct from `live`) for tests that load a heavy local model rather than make a network call; default `addopts` now excludes both. This class of test didn't exist before Phase 6/7 (the glossary embedding model was small enough to just eat the cost by default; NLLB-600M is not).

**Decisions:**
- No automated translation-quality gate — `PLANNING.md` explicitly says MT quality "is hard to QA" and calls for manual spot-check by a fluent reader only. The `slow`-marked opt-in test (`tests/live/test_translate_smoke.py`) only asserts non-empty, distinct-per-language output — a wiring check, not a quality check.
- Chose to expose translation as a **separate on-demand endpoint** rather than an extra field computed during the main job, unlike readability/glossary (which are cheap/local and always computed). Translation is neither cheap (multi-second CPU inference per call) nor something every user wants for every clause — forcing it into the critical path would violate the phase's own stated constraint.

**Verified live (not just mocked), in stages:**
1. Confirmed the NLLB tokenizer's FLORES-200 code API (`convert_tokens_to_ids("hin_Deva")` → a real, distinct token id, not the unknown-token id) before writing any code against it — same "probe the real API before locking in tests" discipline used for the Groq SDK's `RateLimitError` shape in Phase 2 and the glossary retrieval scores in Phase 6.
2. Called `translate()` directly (bypassing the API) for both Hindi and Marathi on a real clause: both came back fluent, non-empty, and different from each other. Hindi back-reads as accurate; the Marathi result used a slightly different verb ("reach a settlement" rather than literally "terminate") — flagged here as exactly the kind of quality nuance the spec anticipated and explicitly chose not to auto-gate.
3. Hit the real running server's `POST /api/translate` end-to-end over HTTP (not just the Python function) — 200 status, correct fluent Hindi translation of a full clause, and confirmed the 400 path for an unsupported language code (`fr`) returns the expected error detail.
4. **Encoding note:** an ad-hoc `print()` of Hindi/Marathi text crashed with `UnicodeEncodeError` against this Windows terminal's `cp1252` console — the translation itself had already succeeded; only the console print failed. Same root cause class as the Phase 6 em-dash mojibake (Windows console encoding, not a data/logic bug) — worked around by writing output to a UTF-8 file instead of printing directly. No code change needed; noted here so the same false alarm isn't re-investigated as a bug later.

**Tests:** `test_translate_nllb.py` (language-code validation and empty-text short-circuit, both proven not to touch the model — 3 tests), `test_translate_flow.py` (injected-fake-function router tests: success, unsupported-language 400, empty-text 400 without invoking the translator, missing-field 422 — 4 tests), `test_translate_smoke.py` (`@pytest.mark.slow`, opt-in, loads the real model). **Suite total: 83 passed, 2 deselected (1 live, 1 slow).**

---

## Known gaps carried forward (not bugs, just not-yet-built)

- In-memory job store — restarting the server loses all job history (documented MVP tradeoff, SQLite is the noted upgrade path).
- No eval harness (`eval/golden_set.json` + `run_eval.py`) — quality is being spot-checked manually, not tracked systematically yet.
- Occasional heading renumbering by the model (see Phase 3 quality note) — a candidate for the eval harness above, once built.
- The independent-judge upgrade to `verify.py` remains un-built by design — only build it if the (not-yet-built) eval harness actually shows hallucination.
- Glossary retrieval threshold (0.35) is empirically chosen, not formally tuned — occasional near-miss top-1 ranking observed (see Phase 6 decisions).
- Translation quality is unaudited by a fluent reader beyond the author's own spot-check (see Phase 7 verification note on the Marathi nuance) — by design, per spec, not a gap to close casually.
- Phase 8 (LoRA fine-tune) remains un-built — explicitly requires external Colab/Kaggle infrastructure not available in this environment; it's a resume-line stretch goal, not a product requirement.
