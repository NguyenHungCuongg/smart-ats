# System Architecture Document (SAD)
## Smart ATS — AI-Powered Multi-Tenant ATS Platform

**Version:** 3.0
**Date:** 2026-09-27
**Target Audience:** Engineering, DevOps, Architecture Team

---

## 1. Architectural Overview
Smart ATS follows a scalable, modern web application architecture leveraging a separation of concerns across Presentation, API Gateway, Domain Services, Async Workers, and Data layers. The system is designed to provide high-performance multi-tenant isolation and reliable asynchronous AI processing.

## 2. Technology Stack (Latest Versions as of Sep 2026)
- **Frontend**: Next.js 16.x (App Router), React 19.3.0, TailwindCSS 4.3.3.
- **API & Core Backend**: FastAPI 0.141.1 (Python 3.12+), SQLAlchemy 2.1.1 (Async ORM).
- **Async Workers**: Celery 5.6.3 + Redis 8.10.2.
- **Database**: PostgreSQL 18.x with Row-Level Security (RLS).
- **AI Orchestration**: LangGraph 1.2.12, LangChain ~0.3.x.
- **LLM Models**: OpenAI GPT-4o, text-embedding-3-large (Gemini 2.0 Flash fallback).

---

## 3. High-Level System Layers

### 3.1 Presentation Layer
- **Client**: Browser-based Next.js SPA utilizing Server Actions and React 19 concurrent features.
- **State Management**: TanStack Query v5 for server state, Zustand for client state.
- **Real-time**: WebSockets/SSE to receive task completion notifications from the backend.

### 3.2 API Gateway Layer (FastAPI)
- **Authentication**: JWT-based auth via custom middleware. Extracts Tenant ID from token.
- **Tenant Context Setting**: Middleware sets PostgreSQL local variable (`app.current_tenant_id`) immediately upon connection checkout for RLS enforcement.
- **Routing & Validation**: Routes requests to domain services. Uses Pydantic v2 for aggressive request validation and prompt sanitization.

### 3.3 Domain Service Layer
- Handles synchronous business logic: CRUD operations for Jobs, Candidates, Pipeline state, and Collaboration features.
- Commits transactions to the database, dispatching heavy compute tasks (parsing, scoring) to the worker queue.

### 3.4 Async Worker Engine (Celery + Redis)
- **CV Parsing Pipeline**: Extracts unstructured PDF/DOCX to JSON in parallel.
- **Scoring Engine**: Generates embeddings, queries Pinecone/pgvector (if used), runs LLM reasoning prompts, computes the 3-axis score, and saves the Fit-Gap report.
- **Smart Agent Runner**: Executes the LangGraph `StateGraph`. Manages the ReAct loops, context handling, tool dispatching, and escalation states.

### 3.5 Infrastructure & Persistence
- **PostgreSQL 18.x**: Shared schema architecture. Enforces strict logical isolation using native Row-Level Security (RLS) policies.
- **Redis 8.10.2**: Acts as Celery broker, result backend, and Pub/Sub mechanism for WebSockets.
- **AWS S3 / MinIO**: Encrypted blob storage for raw PDFs and generated reports.

---

## 4. Multi-Tenant Isolation Design (RLS)
The database avoids the complexity of schema-per-tenant while ensuring total logical isolation.
1. All domain tables have a `tenant_id` UUID column.
2. `ENABLE ROW LEVEL SECURITY` is set on domain tables.
3. Policy configured as:
   `USING (tenant_id = current_setting('app.current_tenant_id')::uuid)`
4. The application layer sets this variable at the beginning of each SQLAlchemy session.
5. Failsafe: Without the session variable set, RLS evaluates to false, returning 0 rows.

---

## 5. Data Flow (Smart Agent Campaign Mode)
1. **Trigger**: Recruiter sends a brief via UI.
2. **API Layer**: FastAPI validates the request and enqueues a Celery task, returning a Task ID.
3. **Execution**: Celery worker picks up the task and starts the LangGraph workflow.
4. **Plan Node**: Evaluates `CampaignState`, decides if JD parse or CV parse is needed.
5. **Action Nodes**: Executes the selected tools dynamically.
6. **Reflect Node**: Assesses if targets are met. If not, analyzes gaps and recommends changes. Limits reflection loops to 2 to prevent endless execution.
7. **Human Checkpoint**: Task enters a paused state (`NEEDS_APPROVAL`). WebSocket pushes notification to UI.
8. **Resolution**: Recruiter interacts with the UI to approve or reject, which continues the state machine to finalize database mutations.

---

## 6. AI Safety & Guardrails
- **Prompt Structural Isolation**: Untrusted candidate data is delimited explicitly (`<untrusted_document_content>`) to prevent prompt injection.
- **Demographics Blind Scoring**: Extraction layer completely strips PII demographics before feeding data to the Scoring Engine.
- **Deterministic Checkpoints**: AI Agent lacks the permission to mutate ATS states without explicit human approval.
