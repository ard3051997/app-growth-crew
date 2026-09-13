FROM ghcr.io/astral-sh/uv:0.8.22 AS uv

FROM python:3.12-slim-bookworm AS builder

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /build

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev \
    --extra analytics \
    --extra aso \
    --extra gcs \
    --extra orchestration \
    --no-install-project

FROM python:3.12-slim-bookworm AS runtime

RUN apt-get update \
    && apt-get install --no-install-recommends -y gosu sqlite3 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --home-dir /app --create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY src/ /app/src/
COPY --chmod=755 deploy/load-secrets.sh /usr/local/bin/load-secrets
COPY --chmod=755 deploy/scheduler-read-only-guard.sh /usr/local/bin/scheduler-read-only-guard
COPY --chmod=755 deploy/db-tools.sh /usr/local/bin/db-tools

RUN mkdir -p /app/config /app/data /backups \
    && chown -R app:app /app /backups

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ENTRYPOINT ["/usr/local/bin/load-secrets"]
CMD ["python", "-m", "uvicorn", "api_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
