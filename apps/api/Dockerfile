# Development image for the API, the Celery workers and Beat. Build context: repo root.
FROM python:3.13.16-slim-trixie
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv

# The venv lives outside the source tree that Compose Watch syncs into.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1

# The whole uv workspace must be present for the shared lockfile to resolve.
WORKDIR /repo
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/
COPY packages/eval/pyproject.toml packages/eval/
RUN uv sync --frozen --no-dev --package smart-ats-api

WORKDIR /repo/apps/api
COPY apps/api/ ./
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
