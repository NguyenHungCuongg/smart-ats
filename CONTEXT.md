# Smart ATS

Multi-tenant Applicant Tracking System for Vietnamese SMEs, with an AI layer that parses CVs, scores candidates against a job, and explains every score. Recruiters decide; AI only proposes.

## Language

### Tenancy & people

**Tenant**:
One customer company and everything it owns; the unit of data isolation.
_Avoid_: Company (in code), organization, account

**Workspace**:
The Tenant as seen by its members in the UI (name, logo, members, settings).
_Avoid_: Using it as a synonym for Tenant in code or schema

**Member**:
A User who belongs to a Tenant and holds exactly one Tenant Role (Company Admin, Recruiter, Reviewer).
_Avoid_: Employee, staff

**System Admin**:
A platform operator who manages Tenants and quotas but never reads a Tenant's recruitment data.
_Avoid_: Superuser, root

**Reviewer Assignment**:
The grant that lets a Reviewer see one Job and its Applications.
_Avoid_: Job access, sharing

### Recruitment

**Job**:
A position a Tenant is hiring for, with its structured criteria and scoring weights.
_Avoid_: JD (except for the source document), job posting (in prose), vacancy

**JD Document**:
The raw file or text a Job was parsed from.
_Avoid_: Job (for the file)

**Candidate**:
A person known to one Tenant, independent of any Job.
_Avoid_: Applicant (that is an Application), profile

**CV Document**:
One uploaded CV file of a Candidate, with its parsed and redacted content.
_Avoid_: Resume (in code), attachment

**Application**:
A Candidate being considered for one Job; it carries the current Stage.
_Avoid_: Candidacy, pipeline entry, submission

**Stage**:
Where an Application is in the hiring process: Applied, Screening, Shortlisted, Interview, Offer, or a terminal Hired / Rejected.
_Avoid_: Status (reserved for Jobs, Campaigns, tasks), step

**Talent Pool**:
All Candidates a Tenant holds whose retention period has not expired.
_Avoid_: Database, CRM

**Rediscovery**:
Finding Talent Pool Candidates who fit a new Job but have not applied to it.
_Avoid_: Reverse matching, sourcing

**Public Apply Link**:
The per-Job public URL where a person submits a CV and becomes a Candidate with an Application.
_Avoid_: Career page, job board

### Evaluation

**Scoring Run**:
One execution of the scoring pipeline for a Job over a set of Applications, with frozen weights, model and prompt versions.
_Avoid_: Scoring session, batch (reserved for uploads)

**Score Result**:
The outcome of one Application in one Scoring Run: three Axis Scores, the Total Score and the Fit-Gap Report.
_Avoid_: Match, rating (reserved for Interview Score)

**Axis Score**:
A 0–100 score on one of Technical Fit, Soft-Skill Claims, or Experience Fit.
_Avoid_: Sub-score, dimension

**Must-have Coverage**:
The share of a Job's must-have skills evidenced in a CV Document, computed deterministically.
_Avoid_: Keyword match

**Fit-Gap Report**:
Strengths, Gaps and Recommendations for one Score Result, each backed by quoted Evidence.
_Avoid_: Explanation, summary, AI comment

**Evidence**:
A verbatim quote from a CV Document or JD Document that supports a claim in a Fit-Gap Report.
_Avoid_: Citation, reference

**Blind Profile**:
The redacted view of a CV Document fed to scoring, with name, gender, age, photo, marital status and hometown removed.
_Avoid_: Anonymized CV

**Shortlist**:
The Applications a Recruiter selects for interview from a ranked Scoring Run.
_Avoid_: Top N (that is a UI filter)

**Interview Score**:
A 1–5 rating a Member gives an Application after an interview.
_Avoid_: Score (ambiguous with Axis/Total Score)

### Agent

**Campaign**:
One Agent-driven attempt to produce a Shortlist for a Job from a Campaign Brief.
_Avoid_: Agent run, job (ambiguous)

**Campaign Brief**:
The Recruiter's natural-language statement of what the Campaign must achieve.
_Avoid_: Prompt

**Checkpoint**:
The point where a Campaign stops and waits for a Recruiter Decision; nothing changes in the ATS before it.
_Avoid_: Approval step, pause

**Recruiter Decision**:
Approve, Revise, or Reject at a Checkpoint.
_Avoid_: Feedback

**Escalation**:
A Checkpoint reached because the Campaign could not meet its target, with the reason stated.
_Avoid_: Failure (that is a technical error)

**What-if Suggestion**:
A proposed criteria change with its computed effect on the Shortlist, shown at a Checkpoint and applied only by a Recruiter.
_Avoid_: Auto-adjustment, relaxation

### Operations

**Upload Batch**:
One multi-file CV upload whose files succeed or fail independently.
_Avoid_: Batch job

**AI Usage Entry**:
One billed model call recorded against a Tenant with its tokens and cost.
_Avoid_: Credit, log

**AI Budget**:
The monthly spending cap on AI Usage for one Tenant.
_Avoid_: Quota (in prose), limit

**Retention Period**:
How long a Candidate's personal data is kept after their last activity before it is anonymized.
_Avoid_: TTL, expiry
