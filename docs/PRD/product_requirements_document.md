# Product Requirements Document (PRD)
## Smart ATS — AI-Powered Multi-Tenant ATS Platform

**Version:** 3.0
**Date:** 2026-09-27
**Target Audience:** Development Team, QA Team, Stakeholders

---

## 1. Product Overview & Vision
Smart ATS is a Multi-Tenant Software-as-a-Service (SaaS) Applicant Tracking System (ATS) integrated with an Agentic AI layer. It aims to automate and optimize the recruitment process for Small and Medium Enterprises (SMEs) in Vietnam. 

### 1.1 Core Problems Solved
- **Resume Overload**: Automating unstructured CV parsing and matching.
- **Subjective Evaluation**: Establishing a structured, multi-axis semantic scoring system.
- **Administrative Burden**: Generating emails and interview questions, moving candidates through the pipeline.
- **Cost**: Providing an affordable multi-tenant SaaS model for SMEs.

### 1.2 Design Philosophy
- **AI-Augmented, Human-Decided**: AI handles bulk processing; recruiters make final hiring decisions.
- **No-Prompt UI**: Users do not need prompt engineering skills.
- **Explainability-First**: Every AI score is backed by a natural language Fit-Gap Report.
- **Fault Isolation**: Batch processing failures are isolated to ensure continuous execution.

---

## 2. User Personas & RBAC
Smart ATS implements a Role-Based Access Control (RBAC) system tailored for SME workflows:

1. **System Admin (Platform-level)**: Manages tenants, AI quotas, system audit logs. Cannot access tenant internal data.
2. **Company Admin (Tenant-level)**: Configures workspace, manages users/roles, oversees tenant AI quotas.
3. **Recruiter (Operations-level)**: Manages JDs, uploads CVs, triggers AI scoring, approves/rejects Agent actions, communicates with candidates. **Only role able to trigger the Smart Recruitment Agent.**
4. **Reviewer (Read & Annotate-level)**: Views specific assigned JDs, reviews Fit-Gap reports, leaves comments and interview scores. Cannot trigger AI actions or change pipeline states.

---

## 3. Functional Requirements

### 3.1 Module A0: Smart Recruitment Agent
- **Description**: An orchestration agent using the ReAct (Reasoning + Acting) pattern via LangGraph. 
- **Workflow**: Recruiter inputs a Campaign Brief. The Agent evaluates the `CampaignState` to dynamically select tools (e.g., `parse_jd`, `batch_parse_cvs`, `run_scoring`, `generate_shortlist`).
- **Checkpoints**: The Agent cannot alter thresholds independently. If candidate targets are unmet, it reflects, attempts a secondary plan, and escalates to a **Human Approval Checkpoint**. Recruiter must explicitly APPROVE, REJECT, or ACCEPT SUGGESTION.
- **Constraint**: Must execute within 15 minutes. Maximum of 2 reflection loops before mandatory escalation.

### 3.2 Module A1: AI Parsing & Candidate Evaluation
- **FR-A1.1 Parse JD & Config**: AI extracts Job Title, Level, Must-have/Nice-to-have Skills, Experience, Responsibilities. Recruiter can edit weights (default: Technical 50%, Soft Skills 20%, Experience 30%).
- **FR-A1.2 Batch CV Parsing**: Supports up to 50 CVs (PDF/DOCX) via drag-and-drop. Processes asynchronously via Celery. Failed files do not block the batch.
- **FR-A1.3 3-Axis Semantic Scoring**: Utilizes text-embedding-3-large and GPT-4o for matching. Outputs a detailed **Fit-Gap Report** (Strengths, Gaps, Recommendations) for every candidate. Implements Demographics Blind Scoring (removing age, gender, etc. before scoring).
- **FR-A1.4 Shortlist & Interview Qs**: Generates STAR-method interview questions specifically targeting identified Gaps in the candidate's profile.
- **FR-A1.5 PDF Report Export**: Generates professional PDF summaries of the JD, rankings, and Fit-Gap analysis.

### 3.3 Module A2: Collaboration
- **FR-A2.1 Recruitment Email Assistant**: AI drafts contextual emails (Invite, Reject, Follow-up) adjustable by Tone (Formal, Friendly, Concise).
- **FR-A2.2 Internal Review**: Recruiters and Reviewers can comment, @mention, and rate candidates internally without candidate visibility.

### 3.4 Module A3: ATS Pipeline
- **FR-A3.1 Job Lifecycle**: Draft → Published → Paused → Closed → Archived.
- **FR-A3.2 Kanban Board**: 6 stages (Applied, Screening, Shortlisted, Interview, Offer, Hired/Rejected) with drag-and-drop support and bulk actions.
- **FR-A3.3 Audit Log**: Tracks stage transitions, emails, and Agent runs.

### 3.5 Module C1: Identity & Multi-Tenancy
- **Authentication**: Email/Password (Argon2id hash) + Google OAuth2. JWT access (15m) and refresh (7d).
- **Isolation**: Shared PostgreSQL Database using **Row-Level Security (RLS)** based on `tenant_id` to strictly isolate data.

### 3.6 Module C2: Core AI Engine & Safety
- **Prompt Guard**: Structural isolation and validation of LLM JSON output to prevent prompt injection.
- **Async Execution**: Long-running tasks executed via Celery + Redis with WebSocket/SSE updates to the UI.

---

## 4. Non-Functional Requirements (NFRs)
- **Performance**: 
  - API CRUD P95 ≤ 500ms
  - Batch parsing of 50 CVs P95 ≤ 120s
  - LLM Time to First Token (TTFT) ≤ 3s
- **Security**: Argon2id hashing, TLS 1.3, RLS data isolation, strict rate limiting.
- **Reliability**: 99.5% uptime, Celery fallback for LLM timeouts (Graceful Degradation).
- **Usability**: UI supports Vietnamese (Default) and English. Async processes must show progress bars.

---

## 5. Technology Stack Requirements
*Must strictly use latest versions as of Sept 2026.*
- **Frontend**: Next.js 16.x, React 19.3.0, TailwindCSS 4.3.3, Zustand 5, TanStack Query v5.
- **Backend**: Python 3.12, FastAPI 0.141.1, SQLAlchemy 2.1.1 (asyncio).
- **AI Core**: LangGraph 1.2.12, LangChain 0.3.x, OpenAI GPT-4o, text-embedding-3-large.
- **Infrastructure**: PostgreSQL 18.x, Redis 8.10.2, Celery 5.6.3, AWS S3 / MinIO.
