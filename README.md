# Smart ATS

Multi-tenant ATS with explainable AI scoring. Requirements: [`docs/SRS/requirement_specification_v3.md`](docs/SRS/requirement_specification_v3.md).

## Layout

| Path            | Contents                                          |
| --------------- | ------------------------------------------------- |
| `apps/web`      | Next.js frontend (pnpm workspace)                 |
| `apps/api`      | FastAPI backend and Celery workers (uv workspace) |
| `packages/eval` | Evaluation harness (uv workspace)                 |
| `infra/`        | Docker and service configuration                  |

## Setup

Requires Node 24, [uv](https://docs.astral.sh/uv/) and Docker.

```sh
corepack enable          # provides the pnpm version pinned in package.json
pnpm install             # also installs the pre-commit hook (Husky)
uv sync                  # installs Python 3.13 if missing
cp .env.example .env     # then fill in secrets
```

The repo uses LF line endings everywhere. A clone made before `.gitattributes` existed may still hold CRLF files on Windows; convert it once, with no uncommitted changes (this resets the working tree):

```sh
git rm -r --cached -q . && git reset --hard
```

Open the repo in VS Code and install the recommended extensions: files are formatted on save (Prettier for web files, Ruff for Python). The pre-commit hook formats and lints staged files; CI runs the same checks on every PR to `develop` and `main`.

## Code quality

| Task                         | Command                                                         |
| ---------------------------- | --------------------------------------------------------------- |
| Format everything (Prettier) | `pnpm format` (check only: `pnpm format:check`)                 |
| Format Python (Ruff)         | `uv run ruff format` (check only: `uv run ruff format --check`) |
| Lint web (ESLint)            | `pnpm --filter @smart-ats/web lint`                             |
| Lint Python (Ruff)           | `uv run ruff check` (autofix: `--fix`)                          |
| Type-check web (TypeScript)  | `pnpm --filter @smart-ats/web typecheck`                        |
| Type-check Python (mypy)     | `uv run mypy`                                                   |

## Infrastructure

The whole stack (backing services, `api`, `web`, one Celery worker per queue, `beat`, `caddy`) runs in Docker Compose (`docker-compose.yml`), configured from `.env`.

| Task                               | Command                                     |
| ---------------------------------- | ------------------------------------------- |
| Start and wait until healthy       | `docker compose up -d --wait`               |
| Start with hot reload (foreground) | `docker compose up --watch`                 |
| Smoke-test the running stack       | `uv run --env-file .env pytest infra/tests` |
| Stop (keeps data)                  | `docker compose down`                       |
| Stop and delete all data           | `docker compose down -v`                    |

Hot reload uses [Compose Watch](https://docs.docker.com/compose/how-tos/file-watch/) rather than bind mounts, because Docker Desktop's file sharing drops file events on Windows and macOS. It copies edits under `apps/api` and `apps/web` into the containers, where uvicorn, `watchfiles` (workers, `beat`) and `next dev` reload. A change to `uv.lock` or `pnpm-lock.yaml` rebuilds the image. Without `--watch`, containers run the code baked in at build time; `docker compose up -d --build` refreshes it.

Caddy exposes a unified entrypoint at https://localhost (reverse proxying `/` to `web`, `/api/*`, `/openapi.json` and `/docs` to `api` with the `/api` prefix kept, and `/flower/` to `flower`). It signs `localhost` with its own CA, so the browser warns until you trust that CA: copy it out with `docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt .` and import it as a trusted root (Windows: `certutil -user -addstore Root root.crt`). Direct service ports remain published for development and smoke testing: API at http://localhost:8000, web app at http://localhost:3000. Workers `worker-llm`, `worker-default`, `worker-agent` and `worker-email` each consume only their own queue, with 2 processes each.

PostgreSQL is published on `127.0.0.1:${POSTGRES_HOST_PORT}`; set another port in `.env` if 5432 is taken. The scripts in `infra/postgres/init` (extension, `ats_owner` / `ats_app` roles) run only when the data volume is empty, so run `docker compose down -v` after changing them.

Redis is published on `127.0.0.1:${REDIS_HOST_PORT}`. It keeps nothing on disk, so restarting it drops queued tasks. Flower is at http://localhost:5555/flower/ (login from `FLOWER_BASIC_AUTH`); start workers with `-E` to see task events.

SeaweedFS serves the S3 API on `127.0.0.1:8333` (credentials from `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY`) and creates `S3_BUCKET` on startup. Presigned URLs must be signed against `S3_PUBLIC_ENDPOINT`, since the browser cannot reach `seaweedfs:8333`. Mailpit accepts SMTP on `127.0.0.1:1025` and shows every caught email at http://localhost:8025; nothing is delivered.

## Development

Run from the repo root. Hostnames in `.env` are Compose service names; use `localhost` when running a process directly on the host.

| Task                                   | Command                                                                            |
| -------------------------------------- | ---------------------------------------------------------------------------------- |
| Web dev server (http://localhost:3000) | `pnpm --filter @smart-ats/web dev`                                                 |
| Web production build                   | `pnpm --filter @smart-ats/web build`                                               |
| API dev server (http://localhost:8000) | `uv run --directory apps/api uvicorn app.main:app --reload`                        |
| Celery worker (one queue)              | `uv run --env-file .env celery --workdir apps/api -A app.worker worker -Q default` |
| Celery Beat                            | `uv run --env-file .env celery --workdir apps/api -A app.worker beat`              |

Queues: `llm`, `default`, `agent`, `email`. Health check: `GET /api/health`. Demo SSE stream: `GET /api/demo/sse`.

## Tests

| Side                                | Command                                     |
| ----------------------------------- | ------------------------------------------- |
| Web (Vitest)                        | `pnpm --filter @smart-ats/web test`         |
| API (pytest)                        | `uv run pytest apps/api`                    |
| Infra smoke (pytest, stack running) | `uv run --env-file .env pytest infra/tests` |
