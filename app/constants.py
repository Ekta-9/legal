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
DROPPED_MAX_RETRIES = 1  # re-ask once for clauses missing from the model's response, then report them as failed

# Cache — the model name is added to the cache key automatically (see cache/store.py)
CACHE_PROMPT_VERSION = "v3"  # bump to invalidate all cached results (v3: no-invented-pronouns rule)

# Job store
JOB_POLL_INTERVAL_HINT_SECONDS = 1.5  # suggested frontend polling interval
