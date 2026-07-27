DISCLAIMER = (
    "This is an automated summary, not legal advice. "
    "Always verify against the original text before relying on it."
)

# Groq call strategy (see PLANNING.md §2)
GROQ_BATCH_SIZE = 6  # clauses per batched call
GROQ_CONCURRENCY = 4  # max in-flight batch requests
GROQ_MAX_RETRIES = 5  # 429 backoff attempts
GROQ_BACKOFF_BASE_SECONDS = 1.0

# Verification-failure behavior (see PLANNING.md §3)
VERIFY_MAX_RETRIES = 1  # exactly one retry before showing the warning badge

# Cache
CACHE_PROMPT_VERSION = "v1"  # bump to invalidate all cached results

# Job store
JOB_POLL_INTERVAL_HINT_SECONDS = 1.5  # suggested frontend polling interval
