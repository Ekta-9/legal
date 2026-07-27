import hashlib
import re
import sqlite3
import threading
from pathlib import Path

from app.constants import CACHE_PROMPT_VERSION

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "cache.sqlite3"


def normalize_clause_text(text: str) -> str:
    """Collapse whitespace so trivial formatting differences don't bust the cache."""
    return re.sub(r"\s+", " ", text).strip()


def clause_hash(text: str, prompt_version: str = CACHE_PROMPT_VERSION) -> str:
    normalized = normalize_clause_text(text)
    digest_input = f"{prompt_version}:{normalized}".encode("utf-8")
    return hashlib.sha256(digest_input).hexdigest()


class CacheStore:
    """clause-hash -> simplified result, keyed on (clause_hash, prompt_version)
    so bumping CACHE_PROMPT_VERSION invalidates everything cleanly if the
    prompt/model changes, without a manual purge.
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    hash TEXT PRIMARY KEY,
                    simplified TEXT NOT NULL,
                    self_check INTEGER NOT NULL,
                    heading TEXT
                )
                """
            )

    def get(self, text: str, prompt_version: str = CACHE_PROMPT_VERSION) -> dict | None:
        key = clause_hash(text, prompt_version)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT simplified, self_check, heading FROM cache WHERE hash = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        simplified, self_check, heading = row
        return {"simplified": simplified, "self_check": bool(self_check), "heading": heading}

    def put(
        self,
        text: str,
        simplified: str,
        self_check: bool,
        heading: str | None = None,
        prompt_version: str = CACHE_PROMPT_VERSION,
    ) -> None:
        key = clause_hash(text, prompt_version)
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache (hash, simplified, self_check, heading) VALUES (?, ?, ?, ?)",
                (key, simplified, int(self_check), heading),
            )
