# Legal Document Simplifier

Upload a legal contract and get it broken down into individual clauses, simplified in plain English by an LLM, and displayed side-by-side with the original — so you can actually understand what you're signing.

## Features

- **Document upload** — drop in a contract (PDF/DOCX/TXT)
- **Automatic clause extraction** — the document is parsed and split into individual clauses
- **LLM-powered simplification** — each clause is rewritten in plain, easy-to-understand language
- **Side-by-side view** — compare the original legal text against the simplified version clause by clause

## Project Structure

```
legal-simplifier/
├── app/            # Backend application (document processing + LLM simplification pipeline)
├── frontend/        # Client-side UI for uploading documents and viewing results
├── docs/            # Project documentation
├── tests/           # Test suite
├── pytest.ini        # Pytest configuration
└── requirements.txt  # Python dependencies
```


### Installation

```bash
git clone https://github.com/Ekta-9/legal-simplifier.git
cd legal-simplifier
pip install -r requirements.txt
```


## How It Works

1. **Upload** — a contract is submitted through the frontend.
2. **Extract** — text is pulled from the uploaded document.
3. **Split** — the document is segmented into individual clauses.
4. **Simplify** — each clause is passed to an LLM, which returns a plain-language rewrite.
5. **Compare** — the original and simplified clauses are rendered side by side in the UI.

