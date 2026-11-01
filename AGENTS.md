# Smart ATS — Agent Guidelines

## Commands

Run everything from the repo root; `README.md` owns the full command list (setup, Docker Compose, Celery). pnpm workspace for `apps/web` (package `@smart-ats/web`), uv workspace for `apps/api`, `packages/eval` and `packages/scoring`.

| Task                    | Command                                                                                                                                                  |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| API tests               | `uv run pytest apps/api` (needs Docker: DB tests start PostgreSQL via testcontainers; never bare `uv run pytest`, `infra/tests` needs the running stack) |
| One API test            | `uv run pytest apps/api/tests/test_health.py::test_health_returns_ok`                                                                                    |
| Scoring tests           | `uv run pytest packages/scoring` (the OpenAI test skips without `OPENAI_API_KEY`; run it with `uv run --env-file .env pytest packages/scoring`)          |
| Eval tests / table      | `uv run pytest packages/eval` / `uv run python -m smart_ats_eval packages/eval/datasets/scratch-v1.json` (see `packages/eval/README.md`)                 |
| Web tests / one file    | `pnpm --filter @smart-ats/web test` / `pnpm --filter @smart-ats/web test app/page.test.tsx`                                                              |
| Infra smoke tests       | `pnpm infra:test` (builds and starts the stack, then runs `infra/tests`)                                                                                 |
| Python lint/format/type | `uv run ruff check`, `uv run ruff format`, `uv run mypy` (strict, covers `apps/api`, `infra/tests` and `packages/*`)                                     |
| Web lint/format/type    | `pnpm --filter @smart-ats/web lint`, `pnpm format`, `pnpm --filter @smart-ats/web typecheck`                                                             |
| New / apply migration   | `uv run --directory apps/api alembic revision -m "<msg>"` / `docker compose run --rm migrate`                                                            |
| Seed demo tenant        | `docker compose run --rm -e SEED_PASSWORD=<pw> migrate python -m app.seed`                                                                               |

CI (`.github/workflows/ci.yml`) runs all of the above on PRs to `develop` and `main`. Hostnames in `.env` are Compose service names; use `localhost` when running a process on the host. Line endings are LF everywhere.

`apps/web` runs Next.js 16, whose APIs differ from training data: read `apps/web/AGENTS.md`, `DESIGN.md`, and the guide in `node_modules/next/dist/docs/` before writing web code.

## Architecture

Built so far: `/api/health`, per-user SSE progress events with one-time tickets (`app/events.py`), one demo Celery task per queue, the tenancy foundation (`tenants`, `users`, `app/db.py`, demo seed), password login with rotating refresh tokens (`app/auth.py`, web `/login`), Members managed by the Company Admin: invited by email through the email outbox sent on queue `email` (`app/emails.py`), accepted via `accept_invitation`, re-roled and revoked (`app/members.py`, web `/settings/members` and `/invitations/accept`), Jobs created from a JD Document with the parse on queue `llm` and criteria confirmed by the Recruiter (`app/jobs.py`, web `/jobs/new` and `/jobs/[id]`), CV upload into a Job as an Upload Batch within the limits of FR-A1.2, checked whole before any is stored, whose per-file parse on queue `llm` dedupes and creates the Candidate, CV Document with Blind Profile and Application (`app/uploads.py`, web `/jobs/[id]`), Scoring Runs that score every Application of a confirmed Job on queue `llm` and show its Fit-Gap Report (`app/scoring_runs.py`, web `/jobs/[id]`), the bilingual vi/en UI with a language switch on every page (`next-intl` without i18n routing, `apps/web/i18n/`, catalogs in `apps/web/messages/`; the invitation email follows the same `NEXT_LOCALE` cookie, `app.emails.locale`), the AI Usage Ledger (`app/usage.py`; the price table is `packages/scoring/src/smart_ats_scoring/pricing.py`, shared with the eval harness, and needs each OpenAI model added before use), the offline eval harness with a BM25 Baseline (`packages/eval`), and the scoring library's Document Extraction, JD/CV parsing, Blind Profile, scoring core v1 (`packages/scoring`: Must-have Coverage matched exactly, by alias, then by meaning, and a deterministic Experience timeline, both shown in the Fit-Gap Report; compared in the eval harness as Config D, v0 kept at tag `scoring-v0`) and Embedder seam with a similarity threshold per embedding model (`embedding.py`, calibrated on `tests/skill_pairs.json`; like a price, each model needs one before use), which has no API, Celery or DB dependency so the eval harness and workers share it. The target design lives in `docs/SAD/system_architecture_document.md`, with the reasons in `docs/adr/`. Invariants new code must follow:

- **Modular monolith.** One FastAPI codebase (`apps/api/app`) serves REST + SSE; the same code runs as Celery workers, one per queue (`llm`, `default`, `agent`, `email`), plus a single `beat`. Redis is transport only; PostgreSQL holds all state, including pgvector embeddings and LangGraph checkpoints (ADR-0004, ADR-0005).
- **Tenant isolation is enforced in the database** (ADR-0001, SAD §4). Every tenant table has `tenant_id NOT NULL`, forced RLS and composite `(tenant_id, id)` foreign keys. The runtime role `ats_app` cannot bypass RLS and only reads its own `tenants` row; `ats_owner` only runs migrations and the demo seed. All DB access goes through `tenant_session(tenant_id)`; an authenticated route takes `auth: Authenticated` (`app/auth.py`), which opens it from the JWT's `tid`; every Celery task takes `tenant_id` as its first argument and uses `@tenant_task` (ADR-0002). A cross-tenant id returns 404, never 403.
- **How that looks in code.** `app/db.py` has `tenant_session` (sync, workers) and `async_tenant_session` (API); each opens one transaction and sets `app.current_tenant_id` with `set_config(..., true)`, so the context dies at commit. Migrations in `apps/api/migrations` are raw SQL run as `ats_owner` by the one-shot `migrate` Compose service; a new tenant table copies the RLS block from `0001_tenants_and_users.py`. `tests/test_tenancy.py` checks the catalog, so any table with a `tenant_id` column that lacks forced RLS and the one standard policy, has a nullable `tenant_id` (only `users` may), or has a foreign key to another tenant table without `tenant_id` fails CI. DB tests must run as `ats_app`: a test run as the table owner proves nothing.
- **Next.js is UI only** (ADR-0003): the browser calls FastAPI directly; no Server Actions or route handlers as a backend.
- **UI text lives in both catalogs** (NFR-USE-03, SAD §5.7): a page takes its words from `apps/web/messages/vi.json` and `en.json` (same keys, checked by a test) and formats dates and numbers with `useLocale()`. An API error shows the catalog's message for its status or code, never the English `detail`; Fit-Gap Report, Evidence and CV/JD text are shown as stored, never translated. An email renders its subject and body in `app.emails.locale(...)` when its row is written.
- **UI Design System:** All UI components, styles, and layouts in `apps/web` must strictly adhere to `DESIGN.md` (color tokens, Archivo/Be Vietnam Pro/JetBrains Mono typography, component behaviors, and Dark Mode contrast invariance). Ad-hoc colors, generic fonts, and banned anti-patterns in `DESIGN.md` are strictly forbidden. Before generating or editing frontend code, agents MUST read `DESIGN.md`.
- **Scoring is hybrid** (ADR-0006): deterministic must-have coverage plus an anchored 1–5 LLM rubric with required Evidence; CV/JD text in prompts sits in an untrusted block.

Before merging, check the security review checklist in `CONTRIBUTING.md`. Branch from `develop` as `feature/issue-<n>-<slug>` and write Conventional Commits in English. Git stays local: the user pushes every branch and tag and opens each PR into `develop` (`Closes #<n>`) themselves, so never run `git push` or `gh pr create`. When the work is committed, hand over the branch name and a PR body ready to paste.

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
