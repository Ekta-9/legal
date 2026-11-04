# Legal Document Simplifier

Upload a legal contract and get each clause rewritten in plain English, shown beside the original so you can check every line against the source.

> **Not legal advice.** The plain-English versions are written by an AI model. They can be wrong or leave things out. Always read the original of any clause that matters to you.

## Features

- **Upload or paste** a contract: PDF (with a text layer), DOCX or TXT.
- **Clause splitting** that follows the document's own numbering (`1.`, `1.1`, `SECTION 2`, `ARTICLE IV`), keeps the preamble that names the parties, and falls back to ALL-CAPS headings or paragraphs for unnumbered documents. In DOCX files it reads Word's automatic numbering and tables.
- **Document context (RAG)**: each clause is sent to the model with the parties, the definitions of terms it uses, and the sections it refers to, all retrieved from the same contract.
- **Plain-English rewrite** of every clause via Groq (`openai/gpt-oss-120b` by default). The model also reports when it is unsure, and those clauses are marked "model unsure" (the model's own judgement, not an independent check).
- **Nothing silently disappears**: a clause the model fails to return is retried once, then shown as "not simplified" with its original text.
- **Readability score** (Flesch-Kincaid grade, before → after) and glossary terms per clause.
- **Hindi / Marathi translation (experimental)** of the plain-English text with a local NLLB model. It is slow on CPU and has not been reviewed for legal accuracy.

**Not supported:** scanned PDFs (no OCR), and headers, footers and footnotes in DOCX files. PDF page headers and footers can end up inside clauses. Very long documents have not been tested.

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

On first use, the glossary embedding model (~90 MB) and, if you choose a translation, the NLLB model (~2.4 GB) are downloaded from Hugging Face.

## Tests

```bash
pytest                 # offline: no API key or network needed
pytest -m live         # real Groq call (uses your quota)
pytest -m slow         # loads the real NLLB translation model
```

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
