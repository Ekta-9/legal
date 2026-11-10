# Saral for any Docker host. Simplification and Hindi/Marathi translation both go through Groq:
#   docker build -t saral . && docker run -p 7860:7860 -e GROQ_API_KEY=... saral
# For the local NLLB translator instead (TRANSLATION_BACKEND=local, ~4 GB of RAM), also install
# requirements-translation.txt, with torch from https://download.pytorch.org/whl/cpu.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY frontend ./frontend

# run as an unprivileged user; the clause cache (data/) needs to be writable
RUN useradd -m -u 1000 user \
 && mkdir -p /app/data \
 && chown -R user /app
USER user

EXPOSE 7860
# One worker: jobs are kept in memory, so a second worker would not see them.
# GROQ_API_KEY comes from the environment, never from a file in the image.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
