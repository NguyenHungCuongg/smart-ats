# System Architecture Document (SAD)

## Smart ATS — AI-Powered Multi-Tenant ATS Platform

**Version:** 3.1
**Date:** 2026-09-28
**Target Audience:** Engineering, DevOps, Architecture Team
**Source of truth:** requirements in `docs/SRS/requirement_specification_v3.md`; decisions in `docs/adr/`; terms in `CONTEXT.md`; data model in `docs/ERD/`. Diagrams: `docs/SAD/architecture_diagram.html`.

---

## 1. Architectural Overview

Smart ATS is a modular monolith: one FastAPI codebase serves the REST API and, as separate processes, the Celery workers. A Next.js app is the only client. PostgreSQL is the single system of record for relational data, embeddings, and agent checkpoints. Redis is transport only (broker, pub/sub, rate-limit counters) and holds no data that cannot be rebuilt.

Two workflows exist:

1. **Deterministic scoring pipeline** (primary thesis contribution): Job parse → CV parse → Scoring Run → Fit-Gap → Shortlist.
2. **Agentic Campaign** (secondary contribution): an orchestration layer that calls the same domain services as tools and stops at a durable Checkpoint.

Quality attributes, in priority order: **tenant isolation**, **explainability and reproducibility of scores**, **fault isolation** in batch AI work, then performance.

## 2. Technology Stack

Pinned lines are in SRS §9.1, checked on 2026-09-28. Exact versions live in lockfiles. In short:

- Next.js 16.3 / React 19.3 / TypeScript 6.0 / TailwindCSS 4.3 / TanStack Query 5.
- Python 3.13, FastAPI 0.141, SQLAlchemy 2.1, psycopg 3.3, Pydantic 2.13.
- Celery 5.6, Redis 8.
- PostgreSQL 18 with pgvector 0.8.
- LangGraph 1.2 with `langgraph-checkpoint-postgres` 3.1.
- OpenAI models: `gpt-6-sol` (reasoning), `gpt-6-luna` (extraction), `text-embedding-3-large` at 1536 dimensions.
- Object storage: S3 in production, SeaweedFS locally. MinIO's repository has been archived, so it is not used.
- Email: SES or Resend in production, Mailpit locally.

---

## 3. Containers & Responsibilities

| Container                 | Responsibility                                                                                                          | Scales by                               |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| `web` (Next.js)           | UI only: recruiter app and the public `/apply/{slug}` page. No Server Actions talk to the backend (ADR-0003).           | Stateless replicas                      |
| `api` (FastAPI + Uvicorn) | Auth, RBAC, tenant context, CRUD, enqueueing, SSE stream, presigned URLs                                                | Stateless replicas                      |
| `worker-llm`              | CV/JD extraction, embedding, scoring, interview questions, email drafts. Concurrency is capped globally and per Tenant. | Replicas; bounded by the LLM rate limit |
| `worker-default`          | Non-AI work: file validation, PDF export, notifications, counters                                                       | Replicas                                |
| `worker-agent`            | LangGraph Campaign passes (plan / act / reflect until the Checkpoint)                                                   | Replicas                                |
| `worker-email`            | Sends queued `email_messages` through the provider                                                                      | 1–2 replicas                            |
| `beat`                    | Schedules the retention/anonymization job, Checkpoint expiry, and stale-task sweep                                      | Exactly 1                               |
| `postgres`                | System of record, RLS, pgvector, LangGraph checkpoints                                                                  | Vertical; read replica later            |
| `redis`                   | Celery broker, SSE pub/sub, rate-limit and concurrency counters                                                         | Vertical                                |
| `object storage`          | CV/JD files, logos, PDF reports, database backups                                                                       | Managed                                 |

---

## 4. Multi-Tenant Isolation (ADR-0001, ADR-0002)

### 4.1 Database layer

- Every tenant-owned table has `tenant_id NOT NULL`, RLS `ENABLE` **and** `FORCE`, and one policy using `NULLIF(current_setting('app.current_tenant_id', true), '')::uuid` in both `USING` and `WITH CHECK`.
- Foreign keys between tenant tables are composite `(tenant_id, id)`, so a row cannot point at another tenant's row.
- Roles:
  - `ats_owner` owns the tables and runs migrations only.
  - `ats_app` is used at runtime: DML only, no ownership, no `BYPASSRLS`.
  - No runtime role can bypass RLS.

### 4.2 Setting the tenant context — one helper, three entry points

```
tenant_session(tenant_id):   # same helper, async flavour in API, sync flavour in workers
    BEGIN
    SELECT set_config('app.current_tenant_id', :tenant_id, true)   -- transaction-local
    ... work ...
    COMMIT                                                       -- context disappears
```

| Entry point               | Where `tenant_id` comes from                                                                                                      |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Authenticated API request | JWT claim `tid`. A FastAPI dependency opens `tenant_session` per request.                                                         |
| Celery task               | Required first argument of every task. A `@tenant_task` decorator opens the session, and a CI check rejects tasks without it.     |
| Public Apply endpoint     | `public_job_by_slug(slug)` (`SECURITY DEFINER`) returns `tenant_id` and `job_id`. The request then continues in `tenant_session`. |

Pre-tenant lookups (login, Google login, invitation acceptance) use the narrow `SECURITY DEFINER` functions listed in ERD §8.

### 4.3 Application layer

- RBAC and Reviewer Assignment are checked in FastAPI dependencies. Cross-tenant ids return **404**, never 403, so the response does not reveal that the resource exists.
- Files are only ever served as presigned URLs valid for 5 minutes or less, issued after the permission check. Object keys are prefixed `t/{tenant_id}/…`.
- The SSE channel is `sse:{tenant_id}:{user_id}`. A user only subscribes to their own channel, after redeeming a single-use SSE ticket.

---

## 5. Key Flows

### 5.1 CV upload & parse (fault-isolated)

1. `POST /jobs/{id}/uploads` (multipart, ≤ 50 files) runs in one transaction:
   - validate MIME with magic bytes and enforce ≤ 10 MB per file;
   - store each file in object storage;
   - create `upload_batches` and one `upload_batch_items` row per file;
   - enqueue one `parse_cv(tenant_id, item_id)` task per file. Tasks are enqueued **after commit** with an `on_commit` hook.
2. Each task:
   - checks SHA-256 deduplication;
   - extracts text (pypdf / python-docx, or vision OCR fallback);
   - runs LLM structured output with a JSON Schema;
   - verifies fields against the source;
   - splits the demographics out into a Blind Profile;
   - embeds;
   - upserts the Candidate (email deduplication), `cv_documents` and `applications`;
   - marks the item `SUCCEEDED`, or `FAILED` with an error code.
3. Progress events are published on Redis and streamed over SSE. The batch is `COMPLETED` when no item is `PENDING`. The count comes from the item rows, not from a chord.

### 5.2 Scoring Run

1. `POST /jobs/{id}/scoring-runs` freezes the weights, criteria, model, `prompt_version` and `rubric_version` into `scoring_runs`, then enqueues `score_application(tenant_id, run_id, application_id)` per Application.
2. Each task:
   1. computes Must-have Coverage deterministically: skill normalization → alias match → embedding similarity above a threshold;
   2. asks the LLM for anchored 1–5 rubric grades with Evidence quotes, at `temperature=0`, under a JSON Schema, with the Blind Profile only;
   3. checks the Evidence against the source text and drops unfound quotes;
   4. computes the axis and total scores;
   5. **upserts** on `(scoring_run_id, application_id)`;
   6. writes an `ai_usage_entries` row.
3. A retried or redelivered task overwrites its own row and never duplicates it.

### 5.3 Campaign with durable Checkpoint (ADR-0004)

1. `POST /campaigns` creates the Campaign (`PLANNING`) and enqueues `run_campaign(tenant_id, campaign_id)` on the `agent` queue.
2. The worker invokes the LangGraph graph with `thread_id = campaign_id` and the Postgres checkpointer.
3. The graph cycles **plan → act → reflect**. Every tool is a domain-service call wrapped with a **capability check**: agent tools only get _derived-data_ capabilities (create scoring runs, write proposals), never _mutating_ capabilities (change stage, create application, send email, edit job). Each step appends to `campaign_events`.
4. Reaching the Checkpoint:
   - write `campaign_proposals`;
   - set `status = AWAITING_DECISION`;
   - publish an SSE event;
   - call `interrupt()`.

   The task returns and the worker slot is free.

5. The Recruiter Decision (`POST /campaigns/{id}/decision`) is stored, and `resume_campaign(tenant_id, campaign_id, decision)` is enqueued.
6. The resume task calls the graph with `Command(resume=decision)`:
   - **APPROVE:** apply the accepted proposals through the normal domain services, **as the Recruiter** (stage changes, Rediscovery Applications), then `APPROVED`.
   - **REVISE:** back to plan.
   - **REJECT:** `REJECTED`, with no ATS change.
7. Guards:
   - a 15-minute machine-time budget per pass;
   - a per-Campaign cost cap checked against `ai_usage_entries`;
   - `beat` expires Checkpoints older than 14 days.

### 5.4 Email (outbox)

1. Sending a draft sets `email_messages.status = QUEUED` in the same transaction as the business change (for example a bulk reject).
2. An `on_commit` hook enqueues `send_email(tenant_id, email_id)`.
3. The worker sends through the provider with `email_id` as the idempotency key, then sets the row to `SENT` or `FAILED`.
4. The `beat` sweep re-enqueues rows stuck in `QUEUED` for more than 10 minutes, which covers a lost enqueue.

### 5.5 Talent Rediscovery

The query is a single SQL statement under RLS:

```sql
SELECT ... FROM cv_documents d JOIN candidates c ...
WHERE c.anonymized_at IS NULL
  AND NOT EXISTS (SELECT 1 FROM applications a WHERE a.job_id = :job AND a.candidate_id = c.id)
ORDER BY d.embedding <=> :job_embedding
LIMIT 50
```

The HNSW index keeps it fast. Isolation needs no extra filter, because RLS already restricts the rows.

---

## 6. Fault Tolerance & Resilience

| Concern                   | Mechanism                                                                                                                                                        |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Worker crash mid-task     | `acks_late=True` and `task_reject_on_worker_lost=True`; the task is idempotent through natural unique keys                                                       |
| LLM timeout / 429 / 5xx   | Retry with backoff 5s → 15s → 60s, then the item is `FAILED` with a retry button                                                                                 |
| LLM provider outage       | Circuit breaker in Redis (≥ 5 consecutive failures in 1 min → _degraded_ for 2 min). New AI tasks wait, the UI shows a banner, and non-AI features keep working. |
| Noisy neighbour           | Per-tenant concurrency semaphore in Redis (`max_llm_concurrency`, default 5), plus AI Budget checks before enqueue                                               |
| Lost enqueue after commit | Outbox-style state rows (`upload_batch_items`, `email_messages`, `score_results`) plus a `beat` sweep of stale `PENDING`/`QUEUED` rows                           |
| Concurrent Kanban moves   | Optimistic locking on `applications.version`                                                                                                                     |
| Redis loss                | No durable data in Redis. In-flight tasks are recovered by the stale-row sweep, and SSE clients reconnect and refetch.                                           |
| Data loss                 | Daily PostgreSQL backup to object storage, 30-day retention, RPO ≤ 24h, RTO ≤ 2h; restore rehearsed once and documented. Object storage versioning is on.        |

---

## 7. AI Safety & Governance

- **Prompt structure:** untrusted document text sits inside `<untrusted_document>`. Scoring calls have no tools, and the output is constrained by a JSON Schema whose grades are integers from 1 to 5.
- **Grounding:** every Evidence quote is verified against the source, and unverifiable claims are flagged.
- **Blind Profile:** demographics are stripped before scoring. Known proxies are listed in SRS FR-C2.4.
- **Human authority:** the agent's capability set excludes every mutating operation (§5.3). The invariant is enforced in code and tests, not in prompts.
- **Reproducibility:** each Scoring Run and Score Result stores the model, prompt version, rubric version and weights. Prompts are versioned files in the repo.
- **Data minimisation:** only text is sent to the LLM provider, never photos. The provider is used under API terms that exclude training on the data.

---

## 8. Observability

- `structlog` JSON logs carrying `request_id`, `tenant_id`, `user_id` and `task_id`.
- Flower for queue depth and task failures.
- `ai_usage_entries` for cost per tenant, feature and model.
- `campaign_events` for agent traces.
- Langfuse tracing (P2), with PII masking before export.
- `/healthz` and `/readyz` on `api` and on the workers (through the Celery inspect ping).

---

## 9. Deployment

- **Local / staging:** Docker Compose with:
  - Caddy (TLS), `web`, `api`;
  - `worker-llm`, `worker-default`, `worker-agent`, `worker-email`, `beat`;
  - `postgres` (image with pgvector), `redis`, `seaweedfs`, `mailpit`, `flower`.
- **Demo production:** the same Compose file on one VPS (≥ 4 vCPU / 8 GB), with managed S3 and a managed email provider.
- **Scaling path (not in scope):** `api` and the workers are stateless and scale horizontally. PostgreSQL gets a read replica for reporting. Nothing in the design assumes a single node except `beat`.
