FROM python:3.11-slim

WORKDIR /app

# Dependencies pinned to exact versions per ops audit (no floating installs).
# starlette==1.2.1 carries the CVE-2026-48710 ("BadHost") host-header
# auth-bypass fix — Starlette <1.0.1 is vulnerable. FastAPI 0.136.3 requires
# starlette>=0.46.0, so the patched 1.2.1 is admitted. (NB: the audit cited
# "CVE-2026-7482" for FastAPI, but that ID is the Ollama memory-disclosure CVE;
# the FastAPI/Starlette stack's actual exposure is CVE-2026-48710.)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir \
        "fastapi==0.136.3" \
        "starlette==1.2.1" \
        "uvicorn[standard]==0.49.0" \
        "pydantic==2.13.4"

COPY main.py .

EXPOSE 11435

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "11435", "--workers", "1"]
