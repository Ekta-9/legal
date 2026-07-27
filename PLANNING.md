# Legal Document Simplifier — Working Spec (v2)

## Guiding principle

**Build the spine first, bolt on satellites later.**

Spine (must work end-to-end before anything else):
`upload → extract → split → simplify → render (original + simplified side by side)`

Satellites (only after the spine is demoable): glossary RAG, readability, translation, fine-tuning.

The failure mode to avoid: a project that's 70% done everywhere and shippable nowhere. If you only ever finish the spine, you still have a real, demoable product.

---

## 1. Stack

| Layer | Choice | Notes / changes from v1 |
|---|---|---|
| Backend | Python + FastAPI | unchanged |
| Frontend | Plain HTML/CSS/JS | unchanged — resist the urge to add a framework |
| LLM inference | Groq free tier, open-weight (Llama-class) | see call strategy below — this is where IRL smoothness is won or lost |
| PDF parsing | PyMuPDF (fitz) | unchanged, right call. Note dual-license (AGPL/commercial) for later |
| DOCX parsing | python-docx | unchanged |
| Embeddings (glossary) | sentence-transformers, local | keep, but small footprint |
| Vector search | **numpy cosine over the glossary — full stop** | **cut Chroma/FAISS.** A few hundred terms is nothing; the dependency buys you zero. Only revisit if the glossary somehow exceeds ~5k entries (it won't) |
| Caching | **SQLite (or a JSON dict for MVP), keyed by clause hash** | **new.** Contracts repeat boilerplate; cache clause→result so re-runs and repeats are free |
| Job store | FastAPI `BackgroundTasks` + in-memory dict (MVP) → SQLite if you want persistence | **new.** Async processing, not a blocking request |
| Readability | `textstat` (Flesch-Kincaid) | **decided: keep.** Clean before/after number, near-zero effort, demos well |
| Translation | NLLB-distilled-600M, local | **deferred to final phase / optional.** 4GB VRAM caps you at the distilled tier; legal-translation quality is hard to QA. Don't let it into the spine |
| Fine-tuning | LoRA/QLoRA (Colab/Kaggle) | **stretch only.** A resume line, not a product feature. Build only if everything else is done |

**Not a stack item but a requirement:** a persistent, visible **"This is an automated summary, not legal advice"** disclaimer on every result. A tool that reinterprets contracts needs it.

---

## 2. Groq call strategy (the part that makes it smooth)

This is the section that didn't exist in v1 and matters most.

- **Batch clauses.** Put 5–8 clauses in one prompt, request structured JSON out (`[{clause_id, simplified, self_check}]`). Turns ~200 calls into ~20.
- **Simplify + self-check in a single call** to start. Prompt asks the model to simplify *and* flag its own low-confidence/risky simplifications. Halves call count vs. a separate judge.
  - *Upgrade path:* if the demo shows hallucination, promote verification to an independent second call (LLM-as-judge). Real tradeoff: independent judge is more reliable but doubles cost/latency. Start cheap, upgrade only on evidence.
- **Concurrency with a ceiling.** `asyncio` + a `Semaphore` (e.g. 3–4 concurrent) so batches run in parallel without tripping rate limits.
- **Handle 429s.** Exponential backoff + retry. Free tier *will* rate-limit you; plan for it.
- **Cache before every call.** Hash the clause text; skip the LLM entirely on a hit.

> Free-tier RPM/TPM limits and available model names change — check Groq's current console before locking the batch size and concurrency numbers.

---

## 3. Verification-failure behavior (decided)

When the self-check (or judge) flags a simplification:

1. **One** retry.
2. If still flagged: show the simplified version **with a visible ⚠ badge** ("machine-check flagged this — read the original carefully").
3. **Never suppress, never silently loop.**

Independent of flags: **always render the original clause beside the simplified one.** For a legal tool this is non-negotiable — the user must be able to check the machine against the source.

---

## 4. Project structure

```
legal-simplifier/
├── app/
│  ├── main.py                # FastAPI entrypoint
│  ├── config.py              # env vars, keys, settings
│  ├── constants.py           # NEW: disclaimer text, batch size, model name, limits
│  ├── routers/
│  │   ├── documents.py       # POST upload/paste → returns job_id
│  │   ├── results.py         # GET results by job_id (frontend polls this)
│  ├── jobs/
│  │   ├── manager.py         # NEW: create/track/update background jobs
│  ├── parsing/
│  │   ├── extract.py         # PyMuPDF / python-docx text extraction
│  │   ├── clause_splitter.py # rule-based clause splitting
│  ├── llm/
│  │   ├── groq_client.py     # wrapper: batching, semaphore, backoff, 429 handling
│  │   ├── simplify.py        # batched simplify + self-check prompt
│  │   ├── verify.py          # independent judge (only if promoted from self-check)
│  ├── cache/
│  │   ├── store.py           # NEW: clause-hash → result (SQLite or JSON)
│  ├── rag/
│  │   ├── embeddings.py       # local embedding model wrapper
│  │   ├── glossary_store.py   # numpy cosine search (NO Chroma/FAISS)
│  │   ├── glossary_data/      # curated legal term definitions
│  ├── scoring/
│  │   ├── readability.py      # textstat Flesch-Kincaid, before/after
│  ├── translation/
│  │   ├── nllb.py             # DEFERRED — final phase / optional
│  ├── models/
│      ├── schemas.py          # Pydantic request/response schemas
├── frontend/
│   ├── index.html
│   ├── style.css
│   ├── script.js              # upload → poll results endpoint → render progressively
├── tests/
├── requirements.txt
├── .env                       # keys — gitignored, never committed
├── .gitignore
├── README.md
```

Changes from v1: added `constants.py`, `jobs/`, `cache/`; demoted `rag/` `scoring/` `translation/` to clearly-satellite status; `verify.py` is now optional-upgrade rather than always-on.

---

## 5. Flow (async, cached, batched)

1. **Open site** — browser loads static HTML/CSS/JS served by FastAPI.
2. **Upload or paste** — user submits PDF / DOCX / text. Backend **immediately returns a `job_id`** and starts a background task. No blocking.
3. **Parse & split** (background) — extract raw text, split into clauses.
4. **Process clauses in batches** (background):
   - For each clause: **check cache** → on miss, add to the current batch.
   - Send batch to Groq: **simplify + self-check** in one structured call (concurrency-limited, backoff on 429).
   - Write results to cache.
   - Apply verification-failure rule (retry once → ⚠ badge, never suppress).
5. **Score** — `textstat` readability before/after per clause (cheap, local).
6. **Frontend polls `results.py`** — shows progress and renders clauses **as they complete** (original + simplified side by side, readability delta, any ⚠ badges, disclaimer always visible).
7. **(Satellite, optional)** — glossary term tooltips (numpy RAG), then translation, only once the above is solid.

---

## 6. Build order (spine → satellites)

1. FastAPI skeleton + static frontend + upload endpoint returning a stubbed result.
2. Extraction (PDF/DOCX) + clause splitter.
3. Groq client with batching, semaphore, backoff. Single-call simplify+self-check.
4. Async job model + polling frontend. **→ at this point you have a demoable product.**
5. Cache layer.
6. Readability before/after.
7. Verification-failure UI (⚠ badges, side-by-side).
8. Glossary RAG (numpy).
9. *(optional)* Translation.
10. *(stretch)* LoRA fine-tune — resume line only.

Stop and ship a demo at step 4. Everything after is enhancement.
