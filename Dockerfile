# Nirikshan Python service image (serves both the API and the worker).
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl tini \
    && rm -rf /var/lib/apt/lists/*

# --- dependency layer (cached) ---
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install ".[dev]"

# --- app layer ---
COPY alembic.ini ./
COPY migrations ./migrations
COPY evaluation ./evaluation
COPY infrastructure/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# non-root
RUN useradd --create-home --uid 10001 nirikshan && chown -R nirikshan:nirikshan /app
USER nirikshan

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=25s --retries=5 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

ENTRYPOINT ["tini", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["api"]
