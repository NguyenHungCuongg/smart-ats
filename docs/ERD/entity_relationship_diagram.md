# Sơ đồ Thực thể Quan hệ (ERD) & Thiết kế Cơ sở Dữ liệu

## Smart ATS — Nền tảng ATS Đa Người Thuê Hỗ trợ AI

**Phiên bản:** 3.2
**Ngày:** 2026-10-08

> ERD là nguồn sự thật cho **lược đồ dữ liệu**: bảng, cột, ràng buộc, index. Yêu cầu nằm trong [SRS](../SRS/software_requirements_specification.md); thuật ngữ trong `CONTEXT.md`; lý do thiết kế trong `docs/adr/`. Sơ đồ: `docs/ERD/database_diagram.html`.
>
> Số mục của tài liệu này được dẫn chiếu từ SAD (ví dụ ERD §8); không đánh số lại.

---

## 1. Chiến lược Cơ sở Dữ liệu

- **PostgreSQL 18** với extension **pgvector 0.8** và **citext** (tạo trong `infra/postgres/init`, vì `ats_owner` không có quyền `CREATE` trên database), một schema dùng chung (`public`).
- **Forced Row-Level Security** trên mọi bảng thuộc tenant (ADR-0001). Mỗi bảng có đúng một policy:
  ```sql
  USING      (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
  ```
- **Role:** `ats_owner` sở hữu mọi bảng và chạy migration. `ats_app` được API và worker dùng; chỉ có quyền DML (riêng `tenants` chỉ `SELECT`), không có `BYPASSRLS`.
- **Quy ước:**
  - Khóa chính là `uuid`, sinh bằng `uuidv7()` (có sẵn trong PostgreSQL 18, tăng theo thời gian, thân thiện với index).
  - Thời gian dùng `timestamptz`.
  - Enum là `text` kèm ràng buộc `CHECK`, dễ migrate hơn `CREATE TYPE`.
  - Mọi bảng thuộc tenant có `tenant_id uuid NOT NULL REFERENCES tenants(id)` và một index ghép bắt đầu bằng `tenant_id`.
  - Khóa ngoại giữa các bảng tenant là khóa ghép `(tenant_id, id)`. Vì vậy database từ chối một dòng tham chiếu tới dòng của tenant khác, kể cả khi ứng dụng truyền sai id.

Ký hiệu dùng bên dưới: **PK** khóa chính · **FK** khóa ngoại · **UQ** duy nhất · **NN** not null · **RLS** forced row-level security.

---

## 2. Nền tảng & Định danh

### `tenants` — RLS không force (bảng nền tảng; `ats_app` chỉ có `SELECT` và chỉ thấy dòng có `id` bằng `app.current_tenant_id`; `ats_owner` thấy tất cả, dùng cho seed và `auth_find_user`)

| Cột                   | Kiểu              | Ghi chú                             |
| --------------------- | ----------------- | ----------------------------------- |
| id                    | uuid PK           |                                     |
| name                  | text NN           |                                     |
| slug                  | text UQ NN        | dùng trong URL                      |
| logo_url              | text              | object storage key                  |
| plan_type             | text NN           | `FREE`, `STARTER`, `GROWTH`         |
| ai_budget_monthly_usd | numeric(10,2) NN  | AI Budget (FR-C1.4)                 |
| max_llm_concurrency   | int NN default 5  | công bằng giữa tenant (FR-C1.4)     |
| retention_months      | int NN default 12 | Retention Period (FR-C1.2, FR-C1.5) |
| privacy_notice_url    | text              | hiển thị trên form Public Apply     |
| status                | text NN           | `ACTIVE`, `SUSPENDED`               |
| created_at            | timestamptz NN    |                                     |

### `users` — RLS (đọc trong phạm vi tenant); tra cứu khi đăng nhập qua `SECURITY DEFINER auth_find_user(email)`

| Cột                | Kiểu                            | Ghi chú                                                  |
| ------------------ | ------------------------------- | -------------------------------------------------------- |
| id                 | uuid PK                         |                                                          |
| tenant_id          | uuid FK → tenants, **nullable** | `NULL` chỉ với `SYSTEM_ADMIN`                            |
| email              | citext UQ NN                    | mỗi người một tài khoản trên nền tảng (SRS §2.1)         |
| password_hash      | text                            | `NULL` với tài khoản chỉ đăng nhập bằng Google           |
| google_sub         | text UQ                         | OIDC subject                                             |
| full_name          | text NN                         |                                                          |
| role               | text NN                         | `SYSTEM_ADMIN`, `COMPANY_ADMIN`, `RECRUITER`, `REVIEWER` |
| is_active          | boolean NN                      |                                                          |
| failed_login_count | int NN default 0                | khóa tạm tài khoản (FR-C1.1)                             |
| locked_until       | timestamptz                     |                                                          |
| last_login_at      | timestamptz                     |                                                          |
| created_at         | timestamptz NN                  |                                                          |

`CHECK ((role = 'SYSTEM_ADMIN') = (tenant_id IS NULL))` · `UNIQUE (tenant_id, id)`: đích của khóa ngoại ghép (§1)

### `refresh_tokens` — RLS

| Cột            | Kiểu                     | Ghi chú                                           |
| -------------- | ------------------------ | ------------------------------------------------- |
| id             | uuid PK                  |                                                   |
| tenant_id      | uuid NN                  |                                                   |
| user_id        | uuid FK → users NN       |                                                   |
| family_id      | uuid NN                  | dùng lại một token đã rotate sẽ thu hồi cả family |
| token_hash     | text UQ NN               | SHA-256 của token                                 |
| expires_at     | timestamptz NN           |                                                   |
| revoked_at     | timestamptz              |                                                   |
| replaced_by_id | uuid FK → refresh_tokens |                                                   |
| created_at     | timestamptz NN           |                                                   |

> Refresh token của System Admin lưu trong `platform_refresh_tokens` (cùng cấu trúc, không có `tenant_id`, không RLS).

### `invitations` — RLS; chấp nhận lời mời qua `SECURITY DEFINER accept_invitation(token)`

| Cột         | Kiểu               | Ghi chú             |
| ----------- | ------------------ | ------------------- |
| id          | uuid PK            |                     |
| tenant_id   | uuid NN            |                     |
| email       | citext NN          |                     |
| role        | text NN            | chỉ các role tenant |
| token_hash  | text UQ NN         |                     |
| invited_by  | uuid FK → users NN |                     |
| expires_at  | timestamptz NN     | TTL theo FR-C1.2    |
| accepted_at | timestamptz        |                     |
| revoked_at  | timestamptz        |                     |

---

## 3. Lõi Tuyển dụng (tất cả RLS)

### `jobs`

| Cột                                                     | Kiểu                     | Ghi chú                                                                                                            |
| ------------------------------------------------------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| id                                                      | uuid PK                  |                                                                                                                    |
| tenant_id                                               | uuid NN                  |                                                                                                                    |
| title                                                   | text NN                  |                                                                                                                    |
| level                                                   | text NN                  | `INTERN` … `MANAGER`                                                                                               |
| department, location                                    | text                     |                                                                                                                    |
| work_mode                                               | text                     | `REMOTE`, `HYBRID`, `ONSITE`                                                                                       |
| status                                                  | text NN                  | `DRAFT`, `PUBLISHED`, `PAUSED`, `CLOSED`, `ARCHIVED`                                                               |
| jd_document_key                                         | text                     | object storage key của JD Document                                                                                 |
| parse_status                                            | text NN                  | `PENDING`, `SUCCEEDED`, `FAILED`: task parse JD Document (FR-A1.1)                                                 |
| parse_error                                             | text                     | mã lỗi khi `FAILED`: mã của Document Extraction, `UNPRICED_MODEL` (model chưa có giá, FR-C1.4) hoặc `PARSE_FAILED` |
| criteria                                                | jsonb                    | criteria đã parse và được Recruiter xác nhận (kỹ năng kèm cờ `must_have`, số năm, học vấn, trách nhiệm, dải lương) |
| criteria_verification                                   | jsonb                    | `VERIFIED` hoặc `NEEDS_REVIEW` cho từng trường đã parse (FR-A1.1)                                                  |
| criteria_confirmed_at                                   | timestamptz              | chỉ được chấm điểm khi đã có giá trị; `CHECK (criteria_confirmed_at IS NULL OR criteria IS NOT NULL)`              |
| criteria_embedding                                      | vector(1536)             | dùng cho Rediscovery                                                                                               |
| weight_technical, weight_soft_skills, weight_experience | numeric(3,2) NN          | `CHECK (sum = 1.00)`, mỗi trọng số `>= 0`                                                                          |
| public_apply_enabled                                    | boolean NN default false |                                                                                                                    |
| public_slug                                             | text UQ                  | Public Apply Link                                                                                                  |
| apply_deadline                                          | date                     |                                                                                                                    |
| created_by                                              | uuid FK → users NN       |                                                                                                                    |
| created_at, updated_at                                  | timestamptz NN           |                                                                                                                    |

### `job_reviewers` — Reviewer Assignment

| Cột         | Kiểu               | Ghi chú                 |
| ----------- | ------------------ | ----------------------- |
| tenant_id   | uuid NN            |                         |
| job_id      | uuid FK → jobs NN  | PK (job_id, user_id)    |
| user_id     | uuid FK → users NN | phải có role `REVIEWER` |
| assigned_by | uuid FK → users NN |                         |
| assigned_at | timestamptz NN     |                         |

### `candidates`

| Cột                    | Kiểu           | Ghi chú                                       |
| ---------------------- | -------------- | --------------------------------------------- |
| id                     | uuid PK        |                                               |
| tenant_id              | uuid NN        |                                               |
| full_name              | text           | `NULL` sau khi ẩn danh hóa                    |
| email                  | citext         | UQ (tenant_id, email) khi khác null           |
| phone                  | text           |                                               |
| links                  | jsonb          | LinkedIn, GitHub                              |
| consent_source         | text NN        | `PUBLIC_APPLY_CONSENT`, `RECRUITER_ATTESTED`  |
| consent_at             | timestamptz NN |                                               |
| consent_notice_version | text           |                                               |
| last_activity_at       | timestamptz NN | mốc tính Retention Period                     |
| anonymized_at          | timestamptz    | do job retention hoặc yêu cầu xóa dữ liệu đặt |
| created_at             | timestamptz NN |                                               |

### `cv_documents`

| Cột                                 | Kiểu                     | Ghi chú                                           |
| ----------------------------------- | ------------------------ | ------------------------------------------------- |
| id                                  | uuid PK                  |                                                   |
| tenant_id                           | uuid NN                  |                                                   |
| candidate_id                        | uuid FK → candidates NN  |                                                   |
| storage_key                         | text NN                  | object storage key; bị xóa khi ẩn danh hóa        |
| file_name                           | text NN                  |                                                   |
| mime_type                           | text NN                  | đã kiểm tra bằng magic bytes                      |
| sha256                              | text NN                  | UQ (tenant_id, sha256) — chống trùng lặp          |
| parse_status                        | text NN                  | `PENDING`, `PARSED`, `FAILED`                     |
| parsed_profile                      | jsonb                    | profile có cấu trúc, **không** chứa nhân khẩu học |
| blind_profile                       | jsonb                    | đầu vào cho chấm điểm (FR-C2.4)                   |
| field_verification                  | jsonb                    | Verified / Needs review cho từng trường           |
| suspicious_content                  | boolean NN default false | cờ heuristic phát hiện injection (FR-C2.2)        |
| embedding                           | vector(1536)             | index HNSW; `NULL` sau khi ẩn danh hóa            |
| embedding_model                     | text                     |                                                   |
| parser_model, parser_prompt_version | text                     |                                                   |
| parsed_at, created_at               | timestamptz              |                                                   |

### `applications` — aggregate Candidate × Job (thực thể trung tâm)

| Cột                    | Kiểu                      | Ghi chú                                                                          |
| ---------------------- | ------------------------- | -------------------------------------------------------------------------------- |
| id                     | uuid PK                   |                                                                                  |
| tenant_id              | uuid NN                   |                                                                                  |
| job_id                 | uuid FK → jobs NN         | UQ (job_id, candidate_id)                                                        |
| candidate_id           | uuid FK → candidates NN   |                                                                                  |
| cv_document_id         | uuid FK → cv_documents NN | CV mà Application này được đánh giá trên                                         |
| source                 | text NN                   | `UPLOAD`, `PUBLIC_APPLY`, `REDISCOVERY`                                          |
| stage                  | text NN                   | `APPLIED`, `SCREENING`, `SHORTLISTED`, `INTERVIEW`, `OFFER`, `HIRED`, `REJECTED` |
| rejected_reason        | text                      |                                                                                  |
| version                | int NN default 0          | optimistic locking khi kéo thẻ Kanban                                            |
| created_at, updated_at | timestamptz NN            |                                                                                  |

### `application_stage_history` — chỉ append

| Cột            | Kiểu                      | Ghi chú                                                                                                         |
| -------------- | ------------------------- | --------------------------------------------------------------------------------------------------------------- |
| id             | uuid PK                   |                                                                                                                 |
| tenant_id      | uuid NN                   |                                                                                                                 |
| application_id | uuid FK → applications NN |                                                                                                                 |
| from_stage     | text                      | `NULL` khi tạo mới                                                                                              |
| to_stage       | text NN                   |                                                                                                                 |
| changed_by     | uuid FK → users           | `NULL` chỉ khi tạo qua Public Apply; thay đổi do Agent đề xuất được áp dụng dưới tên Recruiter đã ra quyết định |
| campaign_id    | uuid FK → campaigns       | có giá trị khi được áp dụng từ một Recruiter Decision                                                           |
| note           | text                      |                                                                                                                 |
| changed_at     | timestamptz NN            |                                                                                                                 |

### `upload_batches`

| Cột                      | Kiểu               | Ghi chú                                              |
| ------------------------ | ------------------ | ---------------------------------------------------- |
| id                       | uuid PK            |                                                      |
| tenant_id                | uuid NN            |                                                      |
| job_id                   | uuid FK → jobs     | `NULL` = chỉ đưa vào Talent Pool                     |
| created_by               | uuid FK → users NN |                                                      |
| total_count              | int NN             |                                                      |
| status                   | text NN            | `PROCESSING`, `COMPLETED`; số đếm suy ra từ các item |
| created_at, completed_at | timestamptz        |                                                      |

### `upload_batch_items`

| Cột                       | Kiểu                        | Ghi chú                                                                                                           |
| ------------------------- | --------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| id                        | uuid PK                     |                                                                                                                   |
| tenant_id                 | uuid NN                     |                                                                                                                   |
| batch_id                  | uuid FK → upload_batches NN |                                                                                                                   |
| file_name                 | text NN                     |                                                                                                                   |
| storage_key               | text NN                     | object storage key của file đã upload; task parse đọc file từ đây                                                 |
| status                    | text NN                     | `PENDING`, `SUCCEEDED`, `FAILED`                                                                                  |
| cv_document_id            | uuid FK → cv_documents      | có giá trị khi thành công                                                                                         |
| dedupe                    | text                        | kết quả chống trùng (FR-A1.2): `EXISTING_CANDIDATE`, `CV_REPLACED`, `ALREADY_APPLIED`; `NULL` khi mọi thứ đều mới |
| error_code, error_message | text                        | ví dụ `ENCRYPTED_PDF`, `UNREADABLE`                                                                               |
| attempts                  | int NN default 0            |                                                                                                                   |

---

## 4. Đánh giá (tất cả RLS)

### `scoring_runs`

| Cột                                   | Kiểu                | Ghi chú                                                                                                                                                                                                         |
| ------------------------------------- | ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| id                                    | uuid PK             |                                                                                                                                                                                                                 |
| tenant_id                             | uuid NN             |                                                                                                                                                                                                                 |
| job_id                                | uuid FK → jobs NN   | index `(tenant_id, job_id, created_at)` để lấy run mới nhất                                                                                                                                                     |
| campaign_id                           | uuid FK → campaigns | `NULL` với lượt chạy thủ công; thêm cùng bảng `campaigns` (M4), nullable nên không cần backfill                                                                                                                 |
| trigger_mode                          | text NN             | `MANUAL`, `AGENT`                                                                                                                                                                                               |
| weights                               | jsonb NN            | snapshot đóng băng `{technical, soft_skills, experience}` từ `jobs.weight_*`, dạng phân số                                                                                                                      |
| criteria_snapshot                     | jsonb NN            | snapshot đóng băng: `jobs.criteria` cộng `title`, `level`                                                                                                                                                       |
| model, prompt_version, rubric_version | text NN             | tái lập (ADR-0006)                                                                                                                                                                                              |
| status                                | text NN             | `RUNNING`, `COMPLETED` (mọi dòng `SCORED`), `PARTIAL` (có dòng `FAILED`, kể cả khi mọi dòng `FAILED`; run không có trạng thái `FAILED`)                                                                         |
| created_by                            | uuid FK → users     |                                                                                                                                                                                                                 |
| created_at, completed_at              | timestamptz         | `completed_at` đặt khi không còn dòng `PENDING`. Run **đang chạy** chặn run mới của Job; định nghĩa và hạn của nó nằm ở `_RUNNING` (`apps/api/app/scoring_runs.py`), tạm thay cho lượt quét của `beat` (SAD §6) |

### `score_results`

| Cột                                                  | Kiểu                      | Ghi chú                                                                                                                   |
| ---------------------------------------------------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| id                                                   | uuid PK                   |                                                                                                                           |
| tenant_id                                            | uuid NN                   |                                                                                                                           |
| scoring_run_id                                       | uuid FK → scoring_runs NN | **UQ (scoring_run_id, application_id)**, là idempotency key                                                               |
| application_id                                       | uuid FK → applications NN |                                                                                                                           |
| cv_document_id                                       | uuid FK → cv_documents NN | CV được chấm, chốt từ `applications.cv_document_id` lúc tạo run; khác CV hiện tại của Application khi đã có CV mới thay   |
| status                                               | text NN                   | `PENDING`, `SCORED`, `FAILED`; dòng kiểu outbox (SAD §6), tạo `PENDING` cùng run                                          |
| technical_score, soft_skills_score, experience_score | numeric(5,2)              | 0–100; số lẻ để Total khớp công thức trên đúng các số đã lưu                                                              |
| must_have_coverage                                   | numeric(4,3)              | 0–1, tất định; dùng để lọc theo tỉ lệ (FR-A1.4)                                                                           |
| must_have_detail                                     | jsonb                     | `{matched, missing}`: tên must-have đã khớp và còn thiếu, phần tất định giải thích được của Must-have Coverage (ADR-0006) |
| total_score                                          | numeric(5,2)              |                                                                                                                           |
| rubric_grades                                        | jsonb                     | điểm thô 1–5 của từng trục, kèm lý do và Evidence                                                                         |
| fit_gap_report                                       | jsonb                     | strengths / gaps / recommendations kèm Evidence                                                                           |
| grounding_rate                                       | numeric(4,3)              | tỷ lệ Evidence tìm thấy trong văn bản gốc                                                                                 |
| error_code                                           | text                      | khi `FAILED`: mã của Document Extraction, `READ_FAILED` (không đọc được file) hoặc `SCORING_FAILED` (lời gọi LLM lỗi)     |
| created_at                                           | timestamptz NN            |                                                                                                                           |

### `interview_question_sets`

| Cột                   | Kiểu                       | Ghi chú                                                                |
| --------------------- | -------------------------- | ---------------------------------------------------------------------- |
| id                    | uuid PK                    |                                                                        |
| tenant_id             | uuid NN                    |                                                                        |
| score_result_id       | uuid FK → score_results NN |                                                                        |
| questions             | jsonb NN                   | câu hỏi, mục đích, góc hỏi bổ trợ, tín hiệu trả lời tốt, gap liên quan |
| model, prompt_version | text NN                    |                                                                        |
| created_at            | timestamptz NN             |                                                                        |

---

## 5. Agent (tất cả RLS, trừ các bảng checkpoint của LangGraph)

### `campaigns`

| Cột                                    | Kiểu               | Ghi chú                                                                                                   |
| -------------------------------------- | ------------------ | --------------------------------------------------------------------------------------------------------- |
| id                                     | uuid PK            | đồng thời là `thread_id` của LangGraph                                                                    |
| tenant_id                              | uuid NN            |                                                                                                           |
| job_id                                 | uuid FK → jobs NN  |                                                                                                           |
| brief                                  | text NN            | Campaign Brief                                                                                            |
| target_count                           | int NN             |                                                                                                           |
| status                                 | text NN            | `PLANNING`, `EXECUTING`, `REFLECTING`, `AWAITING_DECISION`, `APPROVED`, `REJECTED`, `FAILED`, `CANCELLED` |
| escalation_reason                      | text               | có giá trị khi Checkpoint là Escalation                                                                   |
| reflection_count                       | int NN             | giới hạn mỗi lượt: FR-A0                                                                                  |
| revision_count                         | int NN             | giới hạn: FR-A0                                                                                           |
| cost_cap_usd                           | numeric(8,2) NN    |                                                                                                           |
| created_by                             | uuid FK → users NN |                                                                                                           |
| decided_by                             | uuid FK → users    |                                                                                                           |
| created_at, checkpoint_at, finished_at | timestamptz        |                                                                                                           |

### `campaign_events` — log lập luận và tool, chỉ append

| Cột         | Kiểu                   | Ghi chú                                                                             |
| ----------- | ---------------------- | ----------------------------------------------------------------------------------- |
| id          | uuid PK                |                                                                                     |
| tenant_id   | uuid NN                |                                                                                     |
| campaign_id | uuid FK → campaigns NN | UQ (campaign_id, seq)                                                               |
| seq         | int NN                 |                                                                                     |
| type        | text NN                | `PLAN`, `TOOL_CALL`, `TOOL_RESULT`, `REFLECTION`, `CHECKPOINT`, `DECISION`, `ERROR` |
| payload     | jsonb NN               |                                                                                     |
| created_at  | timestamptz NN         |                                                                                     |

### `campaign_proposals` — những gì agent đề xuất tại Checkpoint

| Cột            | Kiểu                   | Ghi chú                                        |
| -------------- | ---------------------- | ---------------------------------------------- |
| id             | uuid PK                |                                                |
| tenant_id      | uuid NN                |                                                |
| campaign_id    | uuid FK → campaigns NN |                                                |
| kind           | text NN                | `SHORTLIST`, `REDISCOVERY`, `WHAT_IF`          |
| application_id | uuid FK → applications | dùng cho `SHORTLIST`                           |
| candidate_id   | uuid FK → candidates   | dùng cho `REDISCOVERY`                         |
| payload        | jsonb NN               | ví dụ thay đổi what-if và tác động đã tính     |
| accepted       | boolean                | có giá trị khi Recruiter Decision được áp dụng |

> **Bảng checkpoint của LangGraph** (`checkpoints`, `checkpoint_writes`, `checkpoint_blobs`, `checkpoint_migrations`) do `langgraph-checkpoint-postgres` tạo. Chúng được khóa theo `thread_id = campaigns.id`, nằm ngoài RLS (ADR-0001), và chỉ chứa id và tóm tắt, không bao giờ chứa văn bản CV.

---

## 6. Cộng tác & Giao tiếp (tất cả RLS)

### `comments`

| Cột                               | Kiểu                      | Ghi chú     |
| --------------------------------- | ------------------------- | ----------- |
| id                                | uuid PK                   |             |
| tenant_id                         | uuid NN                   |             |
| application_id                    | uuid FK → applications NN |             |
| author_id                         | uuid FK → users NN        |             |
| content                           | text NN                   |             |
| interview_score                   | smallint                  | `CHECK 1–5` |
| created_at, edited_at, deleted_at | timestamptz               | soft delete |

### `comment_mentions`

| Cột        | Kiểu                  | Ghi chú                  |
| ---------- | --------------------- | ------------------------ |
| tenant_id  | uuid NN               |                          |
| comment_id | uuid FK → comments NN | PK (comment_id, user_id) |
| user_id    | uuid FK → users NN    |                          |

### `notifications`

| Cột        | Kiểu               | Ghi chú                                                    |
| ---------- | ------------------ | ---------------------------------------------------------- |
| id         | uuid PK            |                                                            |
| tenant_id  | uuid NN            |                                                            |
| user_id    | uuid FK → users NN |                                                            |
| type       | text NN            | `MENTION`, `BATCH_DONE`, `CHECKPOINT`, `BUDGET_WARNING`, … |
| payload    | jsonb NN           |                                                            |
| read_at    | timestamptz        |                                                            |
| created_at | timestamptz NN     |                                                            |

### `email_messages` — đồng thời là email outbox

| Cột                 | Kiểu                   | Ghi chú                                                                         |
| ------------------- | ---------------------- | ------------------------------------------------------------------------------- |
| id                  | uuid PK                | idempotency key gửi cho nhà cung cấp                                            |
| tenant_id           | uuid NN                |                                                                                 |
| application_id      | uuid FK → applications | `NULL` với lời mời Member                                                       |
| kind                | text NN                | `INVITE_INTERVIEW`, `RESULT`, `FOLLOW_UP`, `APPLY_RECEIPT`, `MEMBER_INVITATION` |
| tone                | text                   | `FORMAL`, `FRIENDLY`, `CONCISE`                                                 |
| to_address          | citext NN              |                                                                                 |
| subject, body       | text NN                |                                                                                 |
| status              | text NN                | `DRAFT`, `QUEUED`, `SENT`, `FAILED`                                             |
| provider_message_id | text                   |                                                                                 |
| attempts            | int NN default 0       |                                                                                 |
| sent_by             | uuid FK → users        |                                                                                 |
| created_at, sent_at | timestamptz            |                                                                                 |

---

## 7. Vận hành

### `ai_usage_entries` — RLS, chỉ append

| Cột                                        | Kiểu             | Ghi chú                                                                                 |
| ------------------------------------------ | ---------------- | --------------------------------------------------------------------------------------- |
| id                                         | uuid PK          |                                                                                         |
| tenant_id                                  | uuid NN          |                                                                                         |
| user_id                                    | uuid FK → users  |                                                                                         |
| feature                                    | text NN          | `JOB_PARSE`, `CV_PARSE`, `OCR`, `SCORING`, `INTERVIEW_Q`, `EMAIL`, `AGENT`, `EMBEDDING` |
| model                                      | text NN          |                                                                                         |
| input_tokens, output_tokens, cached_tokens | int NN           |                                                                                         |
| cost_usd                                   | numeric(12,6) NN |                                                                                         |
| ref_type, ref_id                           | text, uuid       | đối tượng mà lời gọi phục vụ                                                            |
| created_at                                 | timestamptz NN   | index (tenant_id, created_at) để cộng chi phí theo tháng                                |

### `audit_logs` — RLS, chỉ append (`ats_app` chỉ có `INSERT` và `SELECT`)

| Cột                    | Kiểu            | Ghi chú                             |
| ---------------------- | --------------- | ----------------------------------- |
| id                     | uuid PK         |                                     |
| tenant_id              | uuid NN         |                                     |
| actor_type             | text NN         | `USER`, `AGENT`, `SYSTEM`, `PUBLIC` |
| actor_user_id          | uuid FK → users |                                     |
| action                 | text NN         | ví dụ `application.stage_changed`   |
| entity_type, entity_id | text, uuid      |                                     |
| before, after          | jsonb           |                                     |
| request_id             | text            |                                     |
| ip                     | inet            |                                     |
| created_at             | timestamptz NN  |                                     |

### `platform_audit_logs` — _không RLS_, chỉ System Admin

Cùng cấu trúc với `audit_logs`, không có `tenant_id` và có thêm `target_tenant_id`.

---

## 8. Hàm `SECURITY DEFINER` trước khi biết tenant

Thuộc sở hữu của `ats_owner`. `ats_app` chỉ có quyền `EXECUTE`. Mỗi hàm chỉ trả về số cột tối thiểu cần dùng.

Vì RLS bị force, policy ràng buộc cả `ats_owner`: một hàm `SECURITY DEFINER` không thấy dòng nào của bảng tenant khi chưa có tenant context, nên mỗi hàm ở đây phải tự đặt context. `auth_find_user` lần lượt đặt context của từng Tenant để tìm, rồi trả lại context của caller (migration `0002`).

| Hàm                                 | Trả về                                                                                   | Dùng cho          |
| ----------------------------------- | ---------------------------------------------------------------------------------------- | ----------------- |
| `auth_find_user(email)`             | id, tenant_id, role, password_hash, is_active, locked_until                              | Đăng nhập         |
| `auth_find_user_by_google_sub(sub)` | như trên                                                                                 | Đăng nhập Google  |
| `public_job_by_slug(slug)`          | tenant_id, job_id, title, status, apply_deadline, tên/logo/URL quyền riêng tư của tenant | Public Apply Link |
| `accept_invitation(token_hash)`     | tenant_id, email, role (và đánh dấu đã chấp nhận)                                        | Chấp nhận lời mời |

---

## 9. Index Chính

- Index bắt đầu bằng `(tenant_id, …)` trên mọi bảng tenant.
- `applications (tenant_id, job_id, stage)` cho Kanban board.
- `score_results UNIQUE (scoring_run_id, application_id)`.
- `scoring_runs (tenant_id, job_id, created_at)` cho run mới nhất của Job.
- `cv_documents UNIQUE (tenant_id, sha256)` và HNSW trên `embedding vector_cosine_ops`.
- `candidates UNIQUE (tenant_id, email) WHERE email IS NOT NULL`.
- `ai_usage_entries (tenant_id, created_at)`.
- `jobs UNIQUE (public_slug)`.
