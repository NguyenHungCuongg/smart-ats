# Smart ATS

Multi-tenant ATS with explainable AI scoring. Requirements: [`docs/SRS/requirement_specification_v3.md`](docs/SRS/requirement_specification_v3.md).

## Layout

| Path | Contents |
| --- | --- |
| `apps/web` | Next.js frontend (pnpm workspace) |
| `apps/api` | FastAPI backend and Celery workers (uv workspace) |
| `packages/eval` | Evaluation harness (uv workspace) |
| `infra/` | Docker and service configuration |

## Setup

Requires Node 24, [uv](https://docs.astral.sh/uv/) and Docker.

```sh
corepack enable          # provides the pnpm version pinned in package.json
pnpm install
uv sync                  # installs Python 3.13 if missing
cp .env.example .env     # then fill in secrets
```

## Development

Run from the repo root. Hostnames in `.env` are Compose service names; use `localhost` when running a process directly on the host.

| Task | Command |
| --- | --- |
| Web dev server (http://localhost:3000) | `pnpm --filter @smart-ats/web dev` |
| Web production build | `pnpm --filter @smart-ats/web build` |
| API dev server (http://localhost:8000) | `uv run --directory apps/api uvicorn app.main:app --reload` |
| Celery worker (one queue) | `uv run --env-file .env celery --workdir apps/api -A app.worker worker -Q default` |
| Celery Beat | `uv run --env-file .env celery --workdir apps/api -A app.worker beat` |

Queues: `llm`, `default`, `agent`, `email`. Health check: `GET /api/health`. Demo SSE stream: `GET /api/demo/sse`.

## Tests

| Side | Command |
| --- | --- |
| Web (Vitest) | `pnpm --filter @smart-ats/web test` |
| API (pytest) | `uv run pytest apps/api` |
