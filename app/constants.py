# Groq call strategy (see PLANNING.md §2). Batch size and concurrency are
# settings (GROQ_BATCH_SIZE / GROQ_CONCURRENCY in .env), see app/config.py.
# The SDK's own retries are off so these are the only retries that happen.
GROQ_MAX_RETRIES = 4  # retries after the first attempt, for timeouts, connection and 5xx errors
# 429s only mean "wait"; with waits capped at 30s this allows several minutes of waiting per call
GROQ_MAX_RATE_LIMIT_RETRIES = 12
GROQ_BACKOFF_BASE_SECONDS = 1.0
GROQ_MAX_BACKOFF_SECONDS = 30.0  # cap on any single wait, including Groq's retry-after
GROQ_TIMEOUT_SECONDS = 60.0
GROQ_TEMPERATURE = 0.2  # low: faithful rewording, not creative variation
# gpt-oss counts its reasoning tokens against this cap too; 6 clauses with context fit with room to spare
GROQ_MAX_COMPLETION_TOKENS = 8192

# Response handling (flagged clauses get one retry in app/llm/verify.py)
DROPPED_MAX_RETRIES = 1  # re-ask once for clauses missing from the model's response, then report them as failed

# Cache — the model name is added to the cache key automatically (see cache/store.py)
CACHE_PROMPT_VERSION = "v8"  # bump to invalidate all cached results (v8: plain-language rules that keep every qualifier; v6: back to the v4 prompt)

# Input limits: keep one upload from exhausting memory or the Groq quota
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PASTE_CHARS = 200_000
MAX_PDF_PAGES = 100
MAX_CLAUSES = 300
MAX_TRANSLATE_CHARS = 5_000
SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".txt")
