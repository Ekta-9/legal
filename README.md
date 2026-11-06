# Legal Document Simplifier

Upload a legal contract and get each clause rewritten in plain English, shown beside the original so you can check every line against the source.

> **Not legal advice.** The plain-English versions are written by an AI model. They can be wrong or leave things out. Always read the original of any clause that matters to you.

## Features

- **Upload or paste** a contract: PDF (with a text layer), DOCX or TXT.
- **Clause splitting** that follows the document's own numbering (`1.`, `1.1`, `SECTION 2`, `ARTICLE IV`), keeps the preamble that names the parties, and falls back to ALL-CAPS headings or paragraphs for unnumbered documents. In DOCX files it reads Word's automatic numbering and tables.
- **Document context (RAG)**: each clause is sent to the model with the parties, the definitions of terms it uses, and the sections it refers to, all retrieved from the same contract. The same material is shown under each clause ("From this contract"), so the reader can see what "Losses" or "the Licensee" means without searching the document.
- **Plain-English rewrite** of every clause via Groq (`openai/gpt-oss-20b` by default; set `GROQ_MODEL=openai/gpt-oss-120b` for the larger model, which kept meaning better on hard clauses in `tests/eval` but has much lower free-tier rate limits). The model also reports when it is unsure, and those clauses are marked "model unsure" (the model's own judgement, not an independent check).
- **Numbers check**: every amount, date, deadline and section number in the original must also appear in the plain version. This is checked in code, not by the model. A clause that loses one is retried once, then marked with the missing numbers.
- **Nothing silently disappears**: a clause the model fails to return is retried once, then shown as "not simplified" with its original text.
- **Readability score** (Flesch-Kincaid grade, before → after) per clause.
- **Glossary**: plain definitions of general legal terms (indemnification, force majeure, termination for cause, …) shown only when the clause actually contains the term or the concept it names — matched with hand-written patterns, no AI.
- **Hindi / Marathi translation (experimental)** of the plain-English text with a local NLLB model. It is slow on CPU and has not been reviewed for legal accuracy.

**Not supported:** scanned PDFs (no OCR), and headers, footers and footnotes in DOCX files. PDF page numbers and repeated page headers and footers are removed, but a footnote or a one-off note in the page margin can still end up inside a clause.

**Limits:** uploads up to 10 MB, pasted text up to 200,000 characters, PDFs up to 100 pages, and documents up to 300 clauses (see `app/constants.py`).

## Your data

The document's text is sent to [Groq's API](https://groq.com/privacy-policy/) for simplification. Simplified clauses are cached on disk in `data/cache.sqlite3`. Job results are kept in memory until the server restarts.

## Setup

Developed and tested with Python 3.11.

```bash
git clone https://github.com/Ekta-9/legal.git
cd legal
python -m venv .venv
.venv\Scripts\activate          # Windows; on macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Get a free API key at <https://console.groq.com/keys> and create a file named `.env` in the project root:

```
GROQ_API_KEY=your-key-here
```

`.env` is gitignored, so the key never gets committed. To use a different Groq model, add `GROQ_MODEL=...` to the same file. Cached results are keyed by model, so switching models never serves another model's output.

## Running

```bash
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. The API and the frontend are served from the same address.

If you choose a translation, the NLLB model (~2.4 GB) is downloaded from Hugging Face on first use.

## Tests

```bash
pytest                 # offline: no API key or network needed
pytest -m live         # real Groq call (uses your quota)
pytest -m slow         # loads the real NLLB translation model
```

To score document-context retrieval against hand-labelled answers (offline, also run by `pytest`):

```bash
python -m tests.eval.rag_eval --details
python -m tests.eval.glossary_eval --details   # glossary term matching
```

To compare Groq models on the hand-written evaluation contracts (uses your quota):

```bash
python -m tests.eval.run_eval --model openai/gpt-oss-20b --model openai/gpt-oss-120b
```

It reports, per model, how many clauses came back, kept every number, and kept the required concepts (exceptions, conditions, who pays), plus the reading grade before and after. These are keyword checks, not a review of legal accuracy.

## How it works

1. **Extract**: text is read from the file (PyMuPDF for PDF, python-docx for DOCX).
2. **Split**: the text is cut into clauses (`app/parsing/clause_splitter.py`).
3. **Context**: parties, definitions and cross-referenced sections are retrieved for each clause (`app/rag/document_context.py`).
4. **Simplify**: clauses go to the model in batches of 6. Cached clauses are skipped, flagged clauses are retried once, and missing clauses are re-requested once (`app/llm/`).
5. **Show**: the page polls for results and fills in each clause as its batch finishes (`frontend/`).

## Project structure

```
app/
├── main.py            FastAPI app; serves the API and frontend/
├── routers/           /api/documents (upload, results), /api/translate
├── jobs/              background pipeline and in-memory job store
├── parsing/           text extraction and clause splitting
├── rag/               document context retrieval, glossary search
├── llm/               Groq client, prompt, response parsing, retry logic
├── cache/             SQLite clause cache
├── scoring/           readability
└── translation/       NLLB translation
frontend/              plain HTML/CSS/JS
tests/                 unit, llm, integration, live (opt-in)
```
