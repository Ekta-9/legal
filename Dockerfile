# Saral on Hugging Face Spaces (Docker SDK, free CPU tier). Also runs anywhere Docker does:
#   docker build -t saral . && docker run -p 7860:7860 -e GROQ_API_KEY=... saral
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.hf-cache

WORKDIR /app

# CPU-only PyTorch first: the default Linux wheel bundles CUDA and is several GB larger.
# 2.13.0+cpu satisfies the torch==2.13.0 pin, so requirements.txt keeps it.
COPY requirements.txt .
RUN pip install torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r requirements.txt

COPY app ./app
COPY frontend ./frontend

# Spaces runs the container as user 1000: the clause cache (data/) and the
# translation model download (HF_HOME) need somewhere writable
RUN useradd -m -u 1000 user \
 && mkdir -p /app/data /app/.hf-cache \
 && chown -R user /app
USER user

EXPOSE 7860
# One worker: jobs are kept in memory, so a second worker would not see them.
# GROQ_API_KEY comes from the environment (a Space secret), never from a file in the image.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
