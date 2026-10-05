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
