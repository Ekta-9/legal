# Legal Document Simplifier — Execution Roadmap & Test Plan

Companion to `PLANNING.md` (the spec). This is the design document: phased build order, per-phase verification, and a testing strategy for every service.

---

## Testing philosophy (read this first)

Every service falls into one of two buckets. They are tested differently, and mixing them up is the classic LLM-app testing mistake.

**Deterministic services** — same input always gives same output:
`extract` · `clause_splitter` · `cache/store` · `glossary_store` (numpy cosine) · `readability` · `jobs/manager` · `schemas`
→ Normal unit tests. **Written test-first.** Fast, exact assertions.

**Nondeterministic boundary** — the LLM:
`groq_client` · `simplify` · `verify`
→ **Mock the Groq client** in all default tests. Never call the real API in the normal test run — it's slow, costs quota, needs network, and is flaky. You test *logic and contract*, not wording:
- batching, concurrency ceiling, 429 → backoff → retry
- JSON parsing: valid / malformed / partial batch / a clause the model silently dropped
- verify decision: flag → one retry → ⚠ badge, never suppress

**Quality** (does the simplification actually preserve meaning?) is **not** a pytest pass/fail gate — it's a separate **eval harness**: a small hand-labeled golden set + a rubric, run occasionally to catch hallucination/quality regressions. Treat it as a dashboard.

**One real live test**, opt-in, marked `@pytest.mark.live`, excluded from the default run — a single real Groq call to confirm the wiring works.

### Test tree

```
tests/
├── conftest.py                     # fixtures: sample docs, FAKE groq client, async test app
├── fixtures/
│   ├── sample_clean.pdf
│   ├── sample_multicolumn.pdf      # the layout that breaks naive parsers
│   ├── sample.docx
│   ├── sample_scanned.pdf          # edge case: no text layer (expect graceful failure)
│   ├── golden_clauses.json         # expected clause counts / ids per fixture
├── unit/                           # deterministic, test-first, fast
│   ├── test_extract.py
│   ├── test_clause_splitter.py
│   ├── test_cache_store.py
│   ├── test_glossary_search.py
│   ├── test_readability.py
│   ├── test_schemas.py
│   ├── test_job_manager.py
├── llm/                            # nondeterministic boundary, MOCKED client
│   ├── test_groq_client.py         # batching, semaphore, 429 backoff (patch sleep)
│   ├── test_simplify_parsing.py    # JSON: valid / malformed / partial / dropped clause
│   ├── test_verify_logic.py        # flag → retry → badge; never suppress
├── integration/                    # full wiring, LLM mocked
│   ├── test_upload_flow.py         # httpx async: upload → job_id → poll → results
│   ├── test_end_to_end.py          # fixture doc → full pipeline → structured result
├── live/                           # opt-in only
│   ├── test_groq_smoke.py          # @pytest.mark.live — 1 real call
├── eval/                           # NOT pass/fail — quality dashboard
    ├── golden_set.json             # clause + acceptable simplification + rubric
    ├── run_eval.py                 # prints faithfulness / hallucination metrics
```

Key fixtures in `conftest.py`:
- `fake_groq` — returns canned structured responses; the backbone of every fast test.
- `async_client` — `httpx.AsyncClient` against the app for endpoint tests (`pytest-asyncio`).
- Sample docs + `golden_clauses.json` so parsing/splitting assertions are exact.

Test deps: `pytest`, `pytest-asyncio`, `httpx`. That's it — no live network, no Groq key needed to run the suite.

---

## Phases

Progress markers: `[ ]` pending · `[x]` done. The demoable milestone is **Phase 3**.

---

### Phase 0 — Setup & Skeleton
**Goal:** a running FastAPI app, the folder structure from the spec, and a green test harness — so every later phase starts from a known-good base.

**Tasks**
- [ ] Create repo + folder structure (per `PLANNING.md`), `.gitignore`, `.env` (gitignored)
- [ ] `config.py` (settings via env), `constants.py` (disclaimer text, batch size, model name, limits)
- [ ] FastAPI boots; `/health` endpoint; serve static `frontend/`
- [ ] `pytest` scaffold + `conftest.py` skeleton; one trivial passing test

**Deliverable:** `uvicorn app.main:app` serves the page; `pytest` runs green.
**Expected output:** browser shows the static page; `/health` returns `{"status":"ok"}`.
**Risks/tradeoffs:** none real — resist adding a frontend framework; plain JS is a deliberate choice to keep the surface small.
**Verification:** `pytest` green; manual hit of `/health` and the page.
**Tests this phase:** harness only (`test_health`).

---

### Phase 1 — Parsing & Clause Splitting
**Goal:** turn an uploaded PDF/DOCX/text into a clean, ordered list of clauses. Pure deterministic — the ideal test-first target.

**Tasks**
- [ ] `parsing/extract.py` — PyMuPDF (PDF), python-docx (DOCX), raw text passthrough
- [ ] Handle the multi-column contract layout without interleaving lines
- [ ] Graceful failure on a scanned/no-text-layer PDF (clear error, not a crash)
- [ ] `parsing/clause_splitter.py` — rule-based splitting (numbered clauses, headings, blank-line boundaries)
- [ ] `models/schemas.py` — Clause / request / response Pydantic models

**Deliverable:** function that maps a file → `list[Clause]`.
**Expected output:** each fixture doc yields the clause count/ids in `golden_clauses.json`.
**Risks/tradeoffs:** rule-based splitting is brittle on weird formatting — accepted for MVP; note it, don't gold-plate. Scanned PDFs are out of scope (OCR deferred).
**Verification:** unit tests green on all fixtures; manual eyeball of clause boundaries on `sample_multicolumn.pdf`.
**Tests this phase (test-first):** `test_extract.py` (each format, multi-column no-interleave, scanned → clean error), `test_clause_splitter.py` (numbered, headed, edge boundaries), `test_schemas.py`.

---

### Phase 2 — Groq Client & Simplification
**Goal:** batched, resilient calls that turn clauses into simplified JSON. First nondeterminism enters — so the client gets mocked everywhere.

**Tasks**
- [ ] `llm/groq_client.py` — batching (5–8 clauses/call), `asyncio.Semaphore` ceiling, exponential backoff on 429, structured-JSON request
- [ ] `llm/simplify.py` — prompt: simplify each clause + self-check flag; parse structured response
- [ ] Robust parser: tolerate malformed JSON, partial batches, a dropped/merged clause (never crash the whole doc)

**Deliverable:** `list[Clause]` → `list[SimplifiedClause]` (with `self_check` flag).
**Expected output:** on the `fake_groq` fixture, clauses come back simplified with flags; malformed responses degrade gracefully.
**Risks/tradeoffs:** batching trades robustness for cost — one bad clause can perturb its batch; mitigated by per-clause ids + a re-ask path for failed ids. Self-check in-call is weaker than an independent judge (upgraded in Phase 5 only if needed).
**Verification:** mocked-client tests green; one `@pytest.mark.live` smoke call passes locally.
**Tests this phase:** `test_groq_client.py` (batch assembly, semaphore respected, 429→backoff with **patched sleep** so tests stay instant), `test_simplify_parsing.py` (valid/malformed/partial/dropped-clause), `live/test_groq_smoke.py`.

---

### Phase 3 — Async Job Model + Frontend Polling  → DEMOABLE
**Goal:** the full loop in a browser without blocking. Upload returns a `job_id`; processing runs in the background; frontend polls and renders progressively.

**Tasks**
- [ ] `jobs/manager.py` — create/track/update jobs (in-memory dict for MVP; note SQLite as the persistence upgrade)
- [ ] `routers/documents.py` — upload/paste → start background task → return `job_id`
- [ ] `routers/results.py` — GET results by `job_id` (status + completed clauses)
- [ ] `frontend/script.js` — upload → poll → render clauses as they complete
- [ ] Wire Phases 1–2 into the background task

**Deliverable:** working product in the browser, LLM mocked or live.
**Expected output:** upload a contract → see simplified clauses stream in.
**Risks/tradeoffs:** in-memory jobs die on restart — acceptable for a demo; SQLite is a one-step upgrade. `BackgroundTasks` over Celery is deliberate (no infra for a portfolio app).
**Verification:** async endpoint tests green; manual full run in browser.
**Tests this phase:** `test_job_manager.py` (lifecycle: submitted→processing→done, and a failure path), `integration/test_upload_flow.py` (async: upload→job_id→poll→results, groq mocked), `integration/test_end_to_end.py` (fixture → full pipeline).

**→ Stop and record a demo here. Everything after is enhancement.**

---

### Phase 4 — Cache
**Goal:** stop re-simplifying identical clauses (contracts are full of repeated boilerplate) and make re-runs free.

**Tasks**
- [ ] `cache/store.py` — clause-hash → result (SQLite or JSON)
- [ ] Cache-check before every LLM call; write-through after
- [ ] Stable hashing (whitespace/normalization handled)

**Deliverable:** cache hits skip the LLM entirely.
**Expected output:** second run of the same doc makes ~0 LLM calls.
**Risks/tradeoffs:** cache invalidation if the prompt/model changes — key the cache on `(clause_hash, prompt_version)` so a prompt change doesn't serve stale output.
**Verification:** unit tests green; manual: re-run a doc, confirm call count drops to ~0.
**Tests this phase (test-first):** `test_cache_store.py` (hit/miss, hash stability across whitespace, prompt-version keying).

---

### Phase 5 — Readability + Verification-failure UX
**Goal:** a demoable before/after number, and the safety UX a legal tool needs.

**Tasks**
- [ ] `scoring/readability.py` — `textstat` Flesch-Kincaid, per-clause before/after
- [ ] Verify handling: flag → one retry → ⚠ badge; never suppress
- [ ] Frontend: original + simplified **side by side**, readability delta, ⚠ badges
- [ ] Persistent "automated summary, not legal advice" disclaimer
- [ ] *(optional upgrade)* promote self-check to independent judge in `verify.py` **only if** the eval shows hallucination

**Deliverable:** results view with deltas, flags, side-by-side, disclaimer.
**Expected output:** each clause shows original, simplification, grade-level drop, any warning.
**Risks/tradeoffs:** independent judge doubles cost/latency — earn it with eval evidence, don't add it by default.
**Verification:** unit tests green; **run `eval/run_eval.py`** to sanity-check faithfulness before trusting the output.
**Tests this phase (test-first for logic):** `test_readability.py` (score direction, empty/edge input), `test_verify_logic.py` (flag→retry→badge, never suppress). Plus seed `eval/golden_set.json` + `run_eval.py`.

---

### Phase 6 — Glossary RAG *(satellite)*
**Goal:** surface plain-language definitions for legal terms via local embedding search.

**Tasks**
- [ ] `rag/glossary_data/` — curate a few hundred term–definition entries
- [ ] `rag/embeddings.py` — sentence-transformers wrapper
- [ ] `rag/glossary_store.py` — **numpy cosine** (no Chroma/FAISS)
- [ ] Frontend: term tooltips

**Deliverable:** relevant glossary terms attached per clause.
**Expected output:** clause mentioning a term → correct definition retrieved.
**Risks/tradeoffs:** embedding recall vs. keyword matching — cosine over a few hundred vectors is trivial and enough; no vector DB needed.
**Verification:** unit tests green.
**Tests this phase (test-first):** `test_glossary_search.py` (top-k correctness on a known set, threshold behavior).

---

### Phase 7 — Translation *(optional)*
**Goal:** Hindi/Marathi output via local NLLB. Build only if the spine is solid.

**Tasks**
- [ ] `translation/nllb.py` — NLLB-distilled-600M wrapper (4GB VRAM tier)
- [ ] Frontend language toggle

**Deliverable:** simplified clauses translated on demand.
**Risks/tradeoffs:** legal-translation quality is hard to QA and VRAM-capped — clearly label as experimental; keep it off the critical path.
**Verification:** manual spot-check by a fluent reader; no automated quality gate (can't reliably assert MT quality).

---

### Phase 8 — LoRA Fine-tune *(stretch / resume line)*
Only if everything above is done. Colab/Kaggle, LoRA/QLoRA. A capability demonstration, not a product requirement.

---

## Running checklist (top level)

- [ ] Phase 0 — Setup & Skeleton
- [ ] Phase 1 — Parsing & Clause Splitting
- [ ] Phase 2 — Groq Client & Simplification
- [ ] Phase 3 — Async Job Model + Frontend → demoable
- [ ] Phase 4 — Cache
- [ ] Phase 5 — Readability + Verify UX
- [ ] Phase 6 — Glossary RAG
- [ ] Phase 7 — Translation (optional)
- [ ] Phase 8 — LoRA (stretch)

Default test command: `pytest -m "not live"` (fast, offline, no quota).
Live smoke: `pytest -m live`. Quality: `python tests/eval/run_eval.py`.
