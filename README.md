# Smart ATS

Multi-tenant ATS with explainable AI scoring. Requirements: [`docs/SRS/software_requirements_specification.md`](docs/SRS/software_requirements_specification.md). Documentation map and contribution workflow: [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Layout

| Path               | Contents                                                                          |
| ------------------ | --------------------------------------------------------------------------------- |
| `apps/web`         | Next.js frontend (pnpm workspace)                                                 |
| `apps/api`         | FastAPI backend and Celery workers (uv workspace)                                 |
| `packages/eval`    | Evaluation harness (uv workspace)                                                 |
| `packages/scoring` | Scoring library: Document Extraction, JD/CV parsing, Blind Profile (uv workspace) |
| `infra/`           | Docker and service configuration                                                  |

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

| Task                               | Command                       |
| ---------------------------------- | ----------------------------- |
| Start and wait until healthy       | `docker compose up -d --wait` |
| Start with hot reload (foreground) | `docker compose up --watch`   |
| Build, start and smoke-test        | `pnpm infra:test`             |
| Stop (keeps data)                  | `docker compose down`         |
| Stop and delete all data           | `docker compose down -v`      |

Hot reload uses [Compose Watch](https://docs.docker.com/compose/how-tos/file-watch/) rather than bind mounts, because Docker Desktop's file sharing drops file events on Windows and macOS. It copies edits under `apps/api` and `apps/web` into the containers, where uvicorn, `watchfiles` (workers, `beat`) and `next dev` reload. A change to `uv.lock` or `pnpm-lock.yaml` rebuilds the image. Without `--watch`, containers run the code baked in at build time; `docker compose up -d --build` refreshes it.

Caddy exposes a unified entrypoint at https://localhost (reverse proxying `/` to `web`, `/api/*`, `/openapi.json` and `/docs` to `api` with the `/api` prefix kept, and `/flower/` to `flower`). It signs `localhost` with its own CA, so the browser warns until you trust that CA: copy it out with `docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt .` and import it as a trusted root (Windows: `certutil -user -addstore Root root.crt`). Direct service ports remain published for development and smoke testing: API at http://localhost:8000, web app at http://localhost:3000. Workers `worker-llm`, `worker-default`, `worker-agent` and `worker-email` each consume only their own queue, with 2 processes each.

PostgreSQL is published on `127.0.0.1:${POSTGRES_HOST_PORT}`; set another port in `.env` if 5432 is taken. The scripts in `infra/postgres/init` (extensions, `ats_owner` / `ats_app` roles) run only when the data volume is empty, so run `docker compose down -v` after changing them.

The one-shot `migrate` service applies Alembic migrations (`apps/api/migrations`) as `ats_owner` and exits; `api`, the workers and `beat` start only after it succeeds. Everything else connects as `ats_app`, which forced RLS binds (ADR-0001). Compose Watch does not rerun it: after adding a migration, run `docker compose run --rm migrate`.

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
| New migration                          | `uv run --directory apps/api alembic revision -m "<message>"`                      |
| Seed demo tenant and Recruiter         | `docker compose exec -e SEED_PASSWORD=<password> api python -m app.seed`           |
| Eval comparison table (Experiment 1)   | `uv run python -m smart_ats_eval packages/eval/datasets/scratch-v1.json`           |

Queues: `llm`, `default`, `agent`, `email`. Health check: `GET /api/health`; readiness (DB, Redis, object storage): `GET /api/ready`. Progress events (SSE): `POST /api/events/ticket` with the access token returns a one-time ticket (lifetime: ADR-0003) for `GET /api/events?ticket=...`; workers send with `app.events.publish`. The seed creates tenant `demo` with Recruiter `recruiter@demo.local`; rerunning it changes nothing. Sign in at https://localhost/login: the refresh cookie is `Secure` and `SameSite=Strict`, so the web app and the API must share the Caddy origin (`NEXT_PUBLIC_API_URL`), not run on separate ports.

## Demo: Job → CV → Score → Fit-Gap

The end-to-end flow of Roadmap M1, on Docker Compose:

1. In `.env`, set `OPENAI_API_KEY`, or for free testing `GEMINI_API_KEY` with Gemini names in `LLM_EXTRACTION_MODEL` and `LLM_REASONING_MODEL` (synthetic CVs only, see `.env.example`). Each model must have a price in `app.usage.PRICES`, or parsing and scoring refuse to call it.
2. Start the stack and seed: `docker compose up -d --build --wait`, then `docker compose exec -e SEED_PASSWORD=<password> api python -m app.seed`.
3. Sign in at https://localhost/login as `recruiter@demo.local`.
4. **Create a Job:** on the home page, open "Tạo Job từ JD", upload a JD Document or paste its text. Once the parse finishes, review the criteria (fields marked "Cần kiểm tra" were not found verbatim in the JD) and press "Xác nhận criteria".
5. **Upload a CV:** in "Ứng viên" on the same page, pick a PDF or DOCX, confirm the lawful basis and press "Tải CV lên". The Application appears once the parse succeeds.
6. **Score:** in "Chấm điểm", press "Chấm điểm". Each Application updates over SSE as its task finishes; reloading the page shows the latest run too.
7. **Read the Fit-Gap Report:** each Application shows Total, the three Axis Scores, Must-have Coverage with the must-haves matched and missing, and Strengths, Gaps and Recommendations with their Evidence. A claim whose Evidence was not found in the CV is marked "Không có bằng chứng".

## Tests

| Side                                | Command                                     |
| ----------------------------------- | ------------------------------------------- |
| Web (Vitest)                        | `pnpm --filter @smart-ats/web test`         |
| API (pytest)                        | `uv run pytest apps/api`                    |
| Eval harness (pytest)               | `uv run pytest packages/eval`               |
| Scoring library (pytest)            | `uv run pytest packages/scoring`            |
| Infra smoke (pytest, stack running) | `uv run --env-file .env pytest infra/tests` |
| Infra smoke, starting the stack     | `pnpm infra:test`                           |

API tests need Docker: they start their own PostgreSQL and Redis with [testcontainers](https://testcontainers.com/), PostgreSQL bootstrapped from `infra/postgres/init` and the migrations.

Scoring tests fake the LLM. `packages/scoring/tests/test_openai.py` calls the real OpenAI API and is skipped unless `OPENAI_API_KEY` is set: run it with `uv run --env-file .env pytest packages/scoring`. For free testing, set `GEMINI_API_KEY` and Gemini model names instead; it wins over `OPENAI_API_KEY`.
