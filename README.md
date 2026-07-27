# Legal Document Simplifier

Upload a contract → extract → split into clauses → simplify with an LLM → view original and simplified side by side.

See [`PLANNING.md`](PLANNING.md) for the spec and [`ROADMAP.md`](ROADMAP.md) for the phased build plan and test strategy.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env          # then fill in GROQ_API_KEY
```

## Run

```bash
uvicorn app.main:app --reload
```

Visit http://127.0.0.1:8000 — health check at `/health`.

## Test

```bash
pytest                # default: fast, offline, no live network calls
pytest -m live        # opt-in: real Groq API smoke test
python tests/eval/run_eval.py   # quality dashboard, not a pass/fail gate
```
