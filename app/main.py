import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.routers import documents, results, translate

# Uvicorn only sets up its own loggers; without this, app.* INFO logs go nowhere.
# Logs carry job ids, counts and errors, never document text.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Legal Document Simplifier")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.middleware("http")
async def no_store_frontend(request: Request, call_next):
    """Dev convenience: browsers will happily cache the static frontend
    files (index.html/script.js/style.css/...) without ever revalidating,
    which makes an edited file silently keep running the old version.
    Disable caching on everything except the JSON API while this is under
    active development.
    """
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(documents.router)
app.include_router(results.router)
app.include_router(translate.router)

app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
