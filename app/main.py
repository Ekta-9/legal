from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routers import documents, results, translate

app = FastAPI(title="Legal Document Simplifier")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(documents.router)
app.include_router(results.router)
app.include_router(translate.router)

app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
