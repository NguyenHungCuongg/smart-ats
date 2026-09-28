# Entity Relationship Diagram (ERD) & Database Design
## Smart ATS — AI-Powered Multi-Tenant ATS Platform

**Version:** 3.0
**Date:** 2026-09-27

---

## 1. Database Architecture Strategy
The system uses **PostgreSQL 18.x** with a **Shared Schema Multi-Tenant Strategy**. Data isolation is strictly enforced at the database engine level using **Row-Level Security (RLS)**.

- **Platform Layer**: Core tenant and user definitions.
- **Domain Layer**: Core business models (Jobs, Candidates, Campaigns) heavily protected by RLS on `tenant_id`.

---

## 2. Table Definitions

### 2.1 Platform Layer

**`tenants`**
- `id` (UUID, PK): Unique identifier for the company workspace.
- `name` (VARCHAR): Company name.
- `logo_url` (VARCHAR): URL to company logo in S3.
- `plan_type` (VARCHAR): Subscription tier.
- `ai_quota_monthly` (INT): Limit of AI invocations per month.
- `created_at` (TIMESTAMP): Creation date.

**`users`**
- `id` (UUID, PK): Unique user identifier.
- `tenant_id` (UUID, FK): Reference to `tenants.id`.
- `email` (VARCHAR, UNIQUE): User email.
- `password_hash` (VARCHAR): Argon2id hashed password.
- `role` (ENUM): 'SYSTEM_ADMIN', 'COMPANY_ADMIN', 'RECRUITER', 'REVIEWER'.
- `is_active` (BOOLEAN): Status.

### 2.2 Job & Candidate Domain (RLS Protected)

**`job_postings`**
- `id` (UUID, PK)
- `tenant_id` (UUID, FK) -> `tenants.id`
- `title` (VARCHAR): Job title.
- `level` (VARCHAR): Junior, Mid, Senior, etc.
- `status` (ENUM): 'DRAFT', 'PUBLISHED', 'PAUSED', 'CLOSED', 'ARCHIVED'.
- `parsed_jd` (JSONB): Structured output from AI Extraction.
- `weight_technical` (DECIMAL): E.g., 0.5.
- `weight_soft_skills` (DECIMAL): E.g., 0.2.
- `weight_experience` (DECIMAL): E.g., 0.3.
- `created_by` (UUID, FK) -> `users.id`
- `created_at` (TIMESTAMP)

**`candidates`**
- `id` (UUID, PK)
- `tenant_id` (UUID, FK) -> `tenants.id`
- `full_name` (VARCHAR): Stripped during scoring if needed.
- `email` (VARCHAR)
- `phone` (VARCHAR)
- `raw_cv_url` (VARCHAR): S3 path.
- `parsed_cv` (JSONB): Structured parsed CV data.
- `confidence_scores` (JSONB): Parsing accuracy metrics.
- `created_at` (TIMESTAMP)

### 2.3 Evaluation Domain (RLS Protected)

**`scoring_sessions`**
- `id` (UUID, PK)
- `tenant_id` (UUID, FK) -> `tenants.id`
- `job_posting_id` (UUID, FK) -> `job_postings.id`
- `trigger_mode` (ENUM): 'MANUAL', 'AGENT'

**`scoring_results`**
- `id` (UUID, PK)
- `session_id` (UUID, FK) -> `scoring_sessions.id`
- `candidate_id` (UUID, FK) -> `candidates.id`
- `technical_score` (DECIMAL)
- `soft_skills_score` (DECIMAL)
- `experience_score` (DECIMAL)
- `total_score` (DECIMAL)
- `fit_gap_report` (JSONB): Details of Strengths, Gaps, and Recommendations.
- `interview_questions` (JSONB): Generated STAR questions based on gaps.

### 2.4 Pipeline & Agent Domain (RLS Protected)

**`pipeline_stages`**
- `id` (UUID, PK)
- `tenant_id` (UUID, FK) -> `tenants.id`
- `candidate_id` (UUID, FK) -> `candidates.id`
- `job_posting_id` (UUID, FK) -> `job_postings.id`
- `stage` (ENUM): 'APPLIED', 'SCREENING', 'SHORTLISTED', 'INTERVIEW', 'OFFER', 'HIRED', 'REJECTED'.
- `changed_by` (UUID, FK) -> `users.id`
- `changed_at` (TIMESTAMP)
- `notes` (TEXT)

**`campaigns`** (Smart Agent Tracker)
- `id` (UUID, PK)
- `tenant_id` (UUID, FK) -> `tenants.id`
- `job_posting_id` (UUID, FK, NULLABLE) -> `job_postings.id`
- `brief` (TEXT): Natural language instructions from Recruiter.
- `target_count` (INT): Desired shortlist size.
- `status` (ENUM): 'PLANNING', 'EXECUTING', 'REFLECTING', 'NEEDS_APPROVAL', 'ESCALATED', 'APPROVED', 'REJECTED'.
- `planned_steps` (JSONB): Tool calls planned by agent.
- `reflection_log` (JSONB): Log of reasoning and suggestions.
- `reflection_count` (INT): Loops executed (max 2).

**`campaign_candidates`**
- `campaign_id` (UUID, FK) -> `campaigns.id`
- `candidate_id` (UUID, FK) -> `candidates.id`
- `status` (VARCHAR): Status of the candidate in this campaign (e.g. 'PENDING', 'SCORED', 'FAILED').
- `retry_count` (INT): Number of times the scoring task was retried.
- `scoring_result_id` (UUID, FK, NULLABLE) -> `scoring_results.id`

**`comments`**
- `id` (UUID, PK)
- `tenant_id` (UUID, FK) -> `tenants.id`
- `candidate_id` (UUID, FK) -> `candidates.id`
- `job_posting_id` (UUID, FK) -> `job_postings.id`
- `author_id` (UUID, FK) -> `users.id`
- `content` (TEXT): Collaborative notes.
- `interview_score` (SMALLINT)
- `created_at` (TIMESTAMP)
