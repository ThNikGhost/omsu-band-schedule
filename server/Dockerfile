# Build context is the repository root, because shared/ is needed at runtime:
#   docker build -f server/Dockerfile .
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Must match the runtime stage: uv bakes an absolute interpreter path into the
# console scripts, so a venv built under /build cannot be copied to /app.
WORKDIR /app
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project


FROM python:3.12-slim

# tzdata is required: every date decision is made in Asia/Omsk.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Omsk \
    DATA_DIR=/data \
    BELLS_PATH=/app/shared/bells.json \
    ABBREVIATIONS_PATH=/app/abbreviations.yaml

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY server/app /app/app
COPY server/abbreviations.yaml /app/abbreviations.yaml
COPY shared /app/shared

USER 1000
EXPOSE 8080

# Uses urllib rather than curl so the runtime image stays free of extra tools.
HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=5).status == 200 else 1)"]

# --workers 1 is mandatory: snapshots, the rate limiter and the scheduler all
# live in process memory. A second worker means a second scheduler.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log"]
