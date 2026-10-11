# Smart ATS — Agent Guidelines

## Commands

Run everything from the repo root; `README.md` owns the full command list (setup, Docker Compose, Celery). pnpm workspace for `apps/web` (package `@smart-ats/web`), uv workspace for `apps/api` and `packages/eval`.

| Task                    | Command                                                                                                                                                  |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| API tests               | `uv run pytest apps/api` (needs Docker: DB tests start PostgreSQL via testcontainers; never bare `uv run pytest`, `infra/tests` needs the running stack) |
| One API test            | `uv run pytest apps/api/tests/test_health.py::test_health_returns_ok`                                                                                    |
| Web tests / one file    | `pnpm --filter @smart-ats/web test` / `pnpm --filter @smart-ats/web test app/page.test.tsx`                                                              |
| Infra smoke tests       | `pnpm infra:test` (builds and starts the stack, then runs `infra/tests`)                                                                                 |
| Python lint/format/type | `uv run ruff check`, `uv run ruff format`, `uv run mypy` (strict, covers `apps/api` and `infra/tests`)                                                   |
| Web lint/format/type    | `pnpm --filter @smart-ats/web lint`, `pnpm format`, `pnpm --filter @smart-ats/web typecheck`                                                             |
| New / apply migration   | `uv run --directory apps/api alembic revision -m "<msg>"` / `docker compose run --rm migrate`                                                            |
| Seed demo tenant        | `docker compose exec -e SEED_PASSWORD=<pw> api python -m app.seed`                                                                                       |

CI (`.github/workflows/ci.yml`) runs all of the above on PRs to `develop` and `main`. Hostnames in `.env` are Compose service names; use `localhost` when running a process on the host. Line endings are LF everywhere.

`apps/web` runs Next.js 16, whose APIs differ from training data: read `apps/web/AGENTS.md` and the guide in `node_modules/next/dist/docs/` before writing web code.

## Architecture

Built so far: `/api/health`, a demo SSE endpoint, one demo Celery task per queue, the tenancy foundation (`tenants`, `users`, `app/db.py`, demo seed), and password login with rotating refresh tokens (`app/auth.py`, web `/login`). The target design lives in `docs/SAD/system_architecture_document.md`, with the reasons in `docs/adr/`. Invariants new code must follow:

- **Modular monolith.** One FastAPI codebase (`apps/api/app`) serves REST + SSE; the same code runs as Celery workers, one per queue (`llm`, `default`, `agent`, `email`), plus a single `beat`. Redis is transport only; PostgreSQL holds all state, including pgvector embeddings and LangGraph checkpoints (ADR-0004, ADR-0005).
- **Tenant isolation is enforced in the database** (ADR-0001, SAD §4). Every tenant table has `tenant_id NOT NULL`, forced RLS and composite `(tenant_id, id)` foreign keys. The runtime role `ats_app` cannot bypass RLS; `ats_owner` only runs migrations. All DB access goes through `tenant_session(tenant_id)`; an authenticated route takes `auth: Authenticated` (`app/auth.py`), which opens it from the JWT's `tid`; every Celery task takes `tenant_id` as its first argument and uses `@tenant_task` (ADR-0002). A cross-tenant id returns 404, never 403.
- **How that looks in code.** `app/db.py` has `tenant_session` (sync, workers) and `async_tenant_session` (API); each opens one transaction and sets `app.current_tenant_id` with `set_config(..., true)`, so the context dies at commit. Migrations in `apps/api/migrations` are raw SQL run as `ats_owner` by the one-shot `migrate` Compose service; a new tenant table copies the RLS block from `0001_tenants_and_users.py`. `tests/test_tenancy.py` checks the catalog, so any table with a `tenant_id` column that lacks forced RLS and the one standard policy fails CI. DB tests must run as `ats_app`: a test run as the table owner proves nothing.
- **Next.js is UI only** (ADR-0003): the browser calls FastAPI directly; no Server Actions or route handlers as a backend.
- **Scoring is hybrid** (ADR-0006): deterministic must-have coverage plus an anchored 1–5 LLM rubric with required Evidence; CV/JD text in prompts sits in an untrusted block.

Before merging, check the security review checklist in `CONTRIBUTING.md`. Branch from `develop` as `feature/issue-<n>-<slug>`, write Conventional Commits in English, and open PRs into `develop` with `Closes #<n>`.

## Agent skills

### Issue tracker

GitHub issues via `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Canonical triage roles mapped 1:1. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout (`CONTEXT.md` + `docs/adr/`). See `docs/agents/domain.md`.

### Project docs

Each kind of question has one owning document; the map is in `CONTRIBUTING.md` (section "Bản đồ tài liệu"). Requirements (FR/NFR IDs, acceptance criteria) live only in `docs/SRS/software_requirements_specification.md`. Project docs are written in Vietnamese with English technical terms; when editing them, follow `CONTRIBUTING.md` (section "Viết tài liệu"): every number lives in one document and is referenced by ID elsewhere, and SAD/ERD section numbers are cited from code, so never renumber them.

### References

Bài báo khoa học toàn văn trong `docs/references/` (~1 MB, không đọc hết). Chỉ dùng khi việc đang làm liên quan ADR/FR/Experiment hoặc báo cáo:

1. Đọc `docs/references/README.md` trước: bảng cho biết bài nào dùng cho quyết định nào, kèm lưu ý trích dẫn.
2. Cần chi tiết → Grep từ khóa trong file bài, chỉ đọc đoạn quanh kết quả. Không Read cả file.
3. Cần hiểu cả bài → giao subagent đọc, yêu cầu trả về tóm tắt kèm câu trích nguyên văn.

Khi dẫn một bài, trích nguyên văn câu làm căn cứ, không diễn giải theo trí nhớ.

## Core Coding Principles (Karpathy Guidelines)

Behavioral guidelines to reduce common LLM coding mistakes, derived from Andrej Karpathy's observations. These guidelines bias toward caution over speed.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.
- Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

- When editing existing code, don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.
- When your changes create orphans: remove imports/variables/functions that your changes made unused. Don't remove pre-existing dead code unless asked.
- The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

- Transform tasks into verifiable goals:
  - "Add validation" → "Write tests for invalid inputs, then make them pass"
  - "Fix the bug" → "Write a test that reproduces it, then make it pass"
  - "Refactor X" → "Ensure tests pass before and after"
- For multi-step tasks, state a brief plan:
  ```
  1. [Step] -> verify: [check]
  2. [Step] -> verify: [check]
  3. [Step] -> verify: [check]
  ```
- Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.
