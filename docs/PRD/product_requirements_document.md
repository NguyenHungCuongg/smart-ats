# Product Requirements Document (PRD)
## Smart ATS — AI-Powered Multi-Tenant ATS Platform

**Version:** 3.1
**Date:** 2026-09-28
**Target Audience:** Development Team, QA Team, Stakeholders

> This PRD is a product summary. **Detailed requirements, acceptance criteria, numbers and versions live only in the SRS** (`docs/SRS/requirement_specification_v3.md`) and are referenced here by ID, not repeated. Terms follow `CONTEXT.md`.

---

## 1. Product Overview & Vision

Smart ATS is a multi-tenant SaaS Applicant Tracking System for Vietnamese SMEs. It turns unstructured CVs into ranked, explained Shortlists, and lets an agent run a hiring Campaign up to a human Checkpoint.

### 1.1 Problems Solved
- **Resume overload:** CVs are parsed and scored automatically, including CVs arriving through a Public Apply Link.
- **Subjective evaluation:** Hybrid scoring (deterministic coverage plus an anchored LLM rubric), with Evidence quoted for every claim.
- **Administrative burden:** Email drafting and sending, interview questions, bulk pipeline actions.
- **Lost talent:** Talent Rediscovery surfaces past Candidates for new Jobs.
- **Cost:** A shared multi-tenant platform with a per-tenant AI Budget.

### 1.2 Design Principles
- **AI-augmented, human-decided.** AI proposes; only people change Stages, criteria, or send email.
- **No-prompt UI.** Forms and buttons, not prompt boxes.
- **Explainability and reproducibility.** Every score has Evidence and a recorded model, prompt version and rubric version.
- **Fault isolation.** One bad file or failed call never blocks a batch.
- **Isolation by default.** Tenant data is separated by the database itself.

### 1.3 Success Metrics (targets defined in SRS §8)
- Scoring agrees with HR experts: Spearman ρ and NDCG@5 against a labelled dataset.
- Prompt-injection attack success rate is at or below the target.
- Zero cross-tenant leaks across the automated isolation suite.
- A new Recruiter reaches their first Fit-Gap Report within the onboarding target.

---

## 2. Personas & Roles (SRS §4)

| Role | Summary |
|---|---|
| **System Admin** | Runs the platform: Tenants, plans, AI Budgets, aggregate usage. **No access to any Tenant's recruitment data.** |
| **Company Admin** | Manages the Workspace and Members, sees AI usage, handles candidate data requests. **Has every Recruiter permission.** |
| **Recruiter** | Runs hiring end to end: Jobs, CVs, scoring, Rediscovery, Campaigns and Recruiter Decisions, email, pipeline. |
| **Reviewer** | Sees only assigned Jobs. Reads Fit-Gap Reports, comments, and gives Interview Scores. Cannot change Stages, run AI, send email, or see candidate contact details. |

Only Company Admins and Recruiters can start a Campaign.

---

## 3. Features (by SRS module)

| Module | Feature | SRS | Priority |
|---|---|---|---|
| A0 Agent | Campaign: plan / act / reflect, Rediscovery and What-if tools, durable Checkpoint with Approve / Revise / Reject | FR-A0 | P1 |
| A1 Evaluation | Job parsing with Recruiter confirmation | FR-A1.1 | P1 |
| | Fault-isolated CV upload & parsing (≤ 50 per batch), deduplication | FR-A1.2 | P1 |
| | Hybrid 3-axis scoring with Fit-Gap Report and Evidence | FR-A1.3 | P1 |
| | Ranking, Shortlist, STAR interview questions | FR-A1.4 | P1 |
| | PDF report | FR-A1.5 | P2 |
| | Talent Rediscovery | FR-A1.6 | P1 |
| A2 Collaboration | Email assistant: draft in 3 tones, **send** through a provider | FR-A2.1 | P1 |
| | Comments, @mentions, Interview Score | FR-A2.2 | P1 |
| A3 Pipeline | Job lifecycle | FR-A3.1 | P1 |
| | Kanban over Applications (5 active + 2 terminal Stages), bulk actions | FR-A3.2 | P1 |
| | Activity timeline & audit log | FR-A3.3 | P1 |
| | Public Apply Link | FR-A3.4 | P1 |
| C1 Platform | Auth (password + Google), sessions | FR-C1.1 | P1 |
| | Workspace & Member management, invitations | FR-C1.2 | P1 |
| | Forced RLS tenant isolation | FR-C1.3 | P1 |
| | AI Usage Ledger & AI Budget | FR-C1.4 | P1 |
| | Candidate personal-data protection (consent, retention, erasure) | FR-C1.5 | P1 |
| C2 AI Engine | Document extraction, prompt-injection defence, async processing, Blind Profile | FR-C2.1–C2.4 | P1 |

---

## 4. Key User Journeys

1. **Manual screening:**
   1. The Recruiter creates a Job from a JD Document and confirms the criteria and weights.
   2. The Recruiter uploads CVs or shares the Public Apply Link.
   3. The Recruiter runs scoring and reads the ranked list with Fit-Gap Reports.
   4. The Recruiter picks a Shortlist, generates interview questions, and sends invitations.
2. **Campaign:**
   1. The Recruiter writes a Campaign Brief with a target count.
   2. The agent scores the pool, tops it up through Rediscovery if short, and prepares a Shortlist or What-if Suggestions.
   3. The Recruiter approves, revises, or rejects at the Checkpoint. Nothing changes in the pipeline before that.
3. **Collaboration:** A Reviewer assigned to a Job reads Fit-Gap Reports, comments with an @mention, and records an Interview Score after the interview.
4. **Data request:** A candidate asks for deletion, and the Company Admin erases the Candidate. Files, identity fields and embeddings are removed.

---

## 5. Non-Functional Requirements (SRS §6)

- Performance, security, reliability and usability targets are defined only in SRS §6 (NFR-PERF, NFR-SEC, NFR-REL, NFR-USE).
- The UI is in Vietnamese (default) and English. CVs and JDs in both languages are supported.

## 6. Technology (SRS §9)

Next.js / React frontend; FastAPI / SQLAlchemy backend; Celery + Redis workers; PostgreSQL 18 with forced RLS and pgvector; LangGraph with a Postgres checkpointer; OpenAI GPT-6 Sol / Luna and `text-embedding-3-large`. Version lines were checked on 2026-09-28 and are listed in SRS §9.1. Exact pins live in the lockfiles.

## 7. Out of Scope (SRS §11)

Candidate accounts or a career portal, offer letters, calendar integration, inbound email, multi-tenant user membership, enterprise SSO, billing, a second LLM provider, and schema- or database-per-tenant.
