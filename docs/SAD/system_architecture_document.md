# Tài liệu Kiến trúc Hệ thống (SAD)

## Smart ATS — Nền tảng ATS Đa Người Thuê Hỗ trợ AI

**Phiên bản:** 3.2
**Ngày:** 2026-10-08
**Đối tượng đọc:** Nhóm phát triển (kỹ thuật, vận hành)

> SAD là nguồn sự thật cho **kiến trúc, flow xử lý, công nghệ và phiên bản**. Yêu cầu và mọi ngưỡng nằm trong [SRS](../SRS/software_requirements_specification.md) và được dẫn bằng mã; lý do của từng quyết định nằm trong `docs/adr/`; thuật ngữ trong `CONTEXT.md`; lược đồ dữ liệu trong [ERD](../ERD/entity_relationship_diagram.md). Sơ đồ: `docs/SAD/architecture_diagram.html`.
>
> Số mục của tài liệu này được code dẫn chiếu (ví dụ `SAD §3` trong `docker-compose.yml`); không đánh số lại.

---

## 1. Tổng quan Kiến trúc

Smart ATS là một modular monolith: một codebase FastAPI phục vụ REST API và, dưới dạng các tiến trình riêng, các Celery worker. Ứng dụng Next.js là client duy nhất. PostgreSQL là hệ thống lưu trữ chính duy nhất cho dữ liệu quan hệ, embedding và checkpoint của agent. Redis chỉ làm tầng vận chuyển (broker, pub/sub, bộ đếm rate limit) và không giữ dữ liệu nào không dựng lại được.

```
Browser (Next.js — Recruiter UI + trang /apply)
   │ HTTPS REST + SSE
   ▼
FastAPI (JWT → RBAC → set tenant context mỗi transaction)
   │                │                       │
   │ SQL (ats_app)  │ enqueue / pub-sub     │ put object
   ▼                ▼                       ▼
PostgreSQL       Redis ──consume──▶ Celery workers ──▶ OpenAI API
Forced RLS +     (broker, pub/sub)  llm · default ·    Email provider
pgvector                            agent · email      Object storage (S3)
   ▲                                        │
   └──────────── SQL (tenant_session) ──────┘
```

Có hai flow nghiệp vụ:

1. **Pipeline chấm điểm tất định** (đóng góp chính của khóa luận): parse Job → Recruiter xác nhận criteria → upload CV / Public Apply → parse từng CV (task riêng) → Scoring Run → xếp hạng + Fit-Gap → Shortlist → câu hỏi phỏng vấn / email / PDF.
2. **Agentic Campaign** (đóng góp phụ): một lớp điều phối gọi chính các domain service ở trên như tool và dừng tại một Checkpoint bền vững. Task `agent` chạy LangGraph (Plan/Act/Reflect) → `interrupt()` tại Checkpoint, state lưu trong Postgres, task kết thúc → SSE thông báo → Recruiter Decision → task mới resume graph → áp dụng thay đổi dưới tên Recruiter.

Thuộc tính chất lượng theo thứ tự ưu tiên: **cô lập tenant**, **khả năng giải trình và tái lập điểm số**, **cô lập lỗi** trong xử lý AI theo batch, rồi mới tới hiệu năng.

## 2. Công nghệ

> **Phiên bản tra cứu ngày 2026-09-28** từ PyPI, npm, endoflife.date và GitHub releases. Bảng ghi **dòng phiên bản (minor)**; phiên bản chính xác được khóa trong lockfile (`uv.lock`, `pnpm-lock.yaml`) — lockfile là nguồn sự thật cho phiên bản. Ràng buộc buộc phải chọn công nghệ: SRS §5.

| Tầng               | Công nghệ                                                                                                   | Phiên bản         | Ghi chú                                                                     |
| ------------------ | ----------------------------------------------------------------------------------------------------------- | ----------------- | --------------------------------------------------------------------------- |
| **Runtime**        | Python                                                                                                      | 3.13.x            | Celery 5.6 và LangGraph 1.2 công bố hỗ trợ tới 3.13; chưa dùng 3.14         |
|                    | Node.js                                                                                                     | 24.x LTS          | Next.js 16 yêu cầu ≥ 20.9                                                   |
|                    | uv (quản lý gói Python)                                                                                     | 0.12.x            |                                                                             |
| **Frontend**       | Next.js (App Router)                                                                                        | 16.3.x            | Chỉ làm frontend (ADR-0003); Next 15 hết hỗ trợ 2026-10-21                  |
|                    | React                                                                                                       | 19.3.x            |                                                                             |
|                    | TypeScript                                                                                                  | 6.0.x             | TS 7.0 (compiler native) đã phát hành — nâng cấp khi Next.js công bố hỗ trợ |
|                    | TailwindCSS                                                                                                 | 4.3.x             |                                                                             |
|                    | shadcn/ui (CLI)                                                                                             | 4.x               |                                                                             |
|                    | TanStack Query / Table                                                                                      | 5.x / 9.x         |                                                                             |
|                    | Zustand                                                                                                     | 5.0.x             |                                                                             |
|                    | Zod                                                                                                         | 4.x               | Validate form & response                                                    |
|                    | next-intl                                                                                                   | 4.x               | Song ngữ Vi/En                                                              |
|                    | @hello-pangea/dnd                                                                                           | 18.x              | Kanban; hỗ trợ React 19                                                     |
| **Backend**        | FastAPI                                                                                                     | 0.141.x           |                                                                             |
|                    | Pydantic                                                                                                    | 2.13.x            |                                                                             |
|                    | SQLAlchemy                                                                                                  | 2.1.x             | Async engine (API) + sync engine (worker) — ADR-0002                        |
|                    | psycopg                                                                                                     | 3.3.x             | Một driver cho cả async và sync                                             |
|                    | Alembic                                                                                                     | 1.20.x            | Migration + RLS policy                                                      |
|                    | Uvicorn                                                                                                     | 0.54.x            |                                                                             |
| **Auth**           | PyJWT 2.15.x, pwdlib 0.3.x (Argon2), slowapi 0.1.x                                                          |                   | Google OAuth2 qua OIDC                                                      |
| **Async**          | Celery                                                                                                      | 5.6.x             | Queue: `llm`, `default`, `agent`, `email`; Celery beat cho tác vụ định kỳ   |
|                    | Flower                                                                                                      | 2.2.x             |                                                                             |
| **AI/Agent**       | LangGraph                                                                                                   | 1.2.x             |                                                                             |
|                    | langgraph-checkpoint-postgres                                                                               | 3.1.x             | Checkpoint bền vững (ADR-0004)                                              |
|                    | langchain-openai / openai SDK                                                                               | 1.6.x / 3.x       |                                                                             |
| **LLM**            | OpenAI `gpt-6-sol`                                                                                          | —                 | Scoring, Fit-Gap, câu hỏi phỏng vấn, lập kế hoạch Agent                     |
|                    | OpenAI `gpt-6-luna`                                                                                         | —                 | Extract JD/CV, soạn email, OCR fallback — rẻ, khối lượng lớn                |
|                    | OpenAI `text-embedding-3-large`                                                                             | `dimensions=1536` | ADR-0005                                                                    |
| **Document**       | pypdf 6.x, python-docx 1.2.x, WeasyPrint 70.x                                                               |                   | Không dùng PyMuPDF do giấy phép AGPL                                        |
| **Database**       | PostgreSQL                                                                                                  | 18.x              | Hỗ trợ tới 2030-11                                                          |
|                    | pgvector                                                                                                    | 0.8.x             | HNSW index                                                                  |
| **Cache/Broker**   | Redis                                                                                                       | 8.x               | Hoặc Valkey 9.x (tương thích, giấy phép BSD)                                |
| **Object storage** | AWS S3 (production) / SeaweedFS 4.x (local, staging)                                                        |                   | Repository mã nguồn của MinIO đã bị lưu trữ (archived) — không dùng         |
| **Email**          | Amazon SES hoặc Resend (production) / Mailpit (local)                                                       |                   | Webhook bounce — P2                                                         |
| **Edge**           | Caddy                                                                                                       |                   | TLS và reverse proxy, không buffer SSE                                      |
| **Observability**  | structlog 26.x; Langfuse 4.x (P2)                                                                           |                   |                                                                             |
| **Testing**        | pytest 9.x, pytest-asyncio, testcontainers 4.x (PostgreSQL thật cho test RLS), Playwright (E2E), Locust 2.x |                   |                                                                             |
| **Lint**           | Ruff 0.16.x, ESLint 10.x                                                                                    |                   |                                                                             |

> **Lựa chọn model:** tên model phản ánh danh mục OpenAI tại 2026-09. Model được chọn qua cấu hình (SRS §5), nên đổi model không cần sửa code và thực nghiệm so sánh được nhiều cấu hình.

---

## 3. Container & Trách nhiệm

| Container                 | Trách nhiệm                                                                                                                 | Mở rộng bằng                        |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------- | ----------------------------------- |
| `web` (Next.js)           | Chỉ UI: ứng dụng cho recruiter và trang công khai `/apply/{slug}`. Không có Server Action nào gọi xuống backend (ADR-0003). | Replica stateless                   |
| `api` (FastAPI + Uvicorn) | Auth, RBAC, tenant context, CRUD, enqueue, SSE stream, presigned URL                                                        | Replica stateless                   |
| `worker-llm`              | Extract CV/JD, embedding, chấm điểm, câu hỏi phỏng vấn, soạn email. Giới hạn đồng thời toàn cục và theo từng Tenant.        | Replica; bị chặn bởi rate limit LLM |
| `worker-default`          | Việc không dùng AI: kiểm tra file, xuất PDF, thông báo, bộ đếm                                                              | Replica                             |
| `worker-agent`            | Các lượt chạy LangGraph của Campaign (plan / act / reflect tới Checkpoint)                                                  | Replica                             |
| `worker-email`            | Gửi các `email_messages` đang chờ qua nhà cung cấp                                                                          | 1–2 replica                         |
| `beat`                    | Lập lịch job ẩn danh hóa theo Retention Period, hết hạn Checkpoint, quét task bị treo                                       | Đúng 1                              |
| `migrate`                 | Chạy một lần: Alembic migration bằng `ats_owner`, rồi thoát; `api`, worker và `beat` khởi động sau khi nó thành công        | Đúng 1, mỗi lần deploy              |
| `postgres`                | Lưu trữ chính, RLS, pgvector, checkpoint của LangGraph                                                                      | Theo chiều dọc; read replica sau    |
| `redis`                   | Celery broker, SSE pub/sub, bộ đếm rate limit và đồng thời                                                                  | Theo chiều dọc                      |
| `object storage`          | File CV/JD, logo, báo cáo PDF, bản sao lưu database                                                                         | Dịch vụ managed                     |

---

## 4. Cô lập Multi-Tenant (ADR-0001, ADR-0002)

### 4.1. Tầng database

- Mọi bảng thuộc tenant có `tenant_id NOT NULL`, RLS `ENABLE` **và** `FORCE`, và một policy dùng `NULLIF(current_setting('app.current_tenant_id', true), '')::uuid` cho cả `USING` lẫn `WITH CHECK`.
- Khóa ngoại giữa các bảng tenant là khóa ghép `(tenant_id, id)`, nên một dòng không thể trỏ tới dòng của tenant khác.
- Role:
  - `ats_owner` sở hữu bảng và chỉ dùng để chạy migration và seed demo.
  - `ats_app` dùng lúc runtime: chỉ có quyền DML (riêng `tenants` chỉ `SELECT` dòng của tenant hiện tại), không sở hữu bảng, không có `BYPASSRLS`.
  - Không role runtime nào bỏ qua được RLS.

### 4.2. Đặt tenant context — một helper, ba điểm vào

```
tenant_session(tenant_id):   # cùng một helper, bản async cho API, bản sync cho worker
    BEGIN
    SELECT set_config('app.current_tenant_id', :tenant_id, true)   -- chỉ trong transaction
    ... xử lý ...
    COMMIT                                                       -- context biến mất
```

| Điểm vào                | `tenant_id` lấy từ đâu                                                                                                                |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| API request đã xác thực | Claim `tid` trong JWT. Một FastAPI dependency mở `tenant_session` cho mỗi request.                                                    |
| Celery task             | Tham số đầu tiên, bắt buộc, của mọi task. Decorator `@tenant_task` mở session; một bước kiểm tra trong CI từ chối task không dùng nó. |
| Endpoint Public Apply   | `public_job_by_slug(slug)` (`SECURITY DEFINER`) trả về `tenant_id` và `job_id`. Request sau đó chạy tiếp trong `tenant_session`.      |

Các tra cứu trước khi biết tenant (đăng nhập, đăng nhập Google, chấp nhận lời mời) dùng các hàm `SECURITY DEFINER` hẹp liệt kê ở ERD §8.

### 4.3. Tầng ứng dụng

- RBAC và Reviewer Assignment được kiểm tra trong FastAPI dependency. Id thuộc tenant khác trả về **404**, không bao giờ 403, để response không tiết lộ resource có tồn tại.
- File chỉ được phục vụ qua presigned URL (thời hạn theo NFR-SEC-09), cấp sau khi kiểm tra quyền. Object key có tiền tố `t/{tenant_id}/…`.
- Kênh SSE là `sse:{tenant_id}:{user_id}`. Người dùng chỉ subscribe kênh của chính mình, sau khi đổi một SSE ticket dùng một lần.

---

## 5. Key Flows

### 5.1. Upload & parse CV (cô lập lỗi)

1. `POST /jobs/{id}/uploads` (multipart, giới hạn số file và kích thước theo FR-A1.2) chạy trong một transaction:
   - kiểm tra MIME bằng magic bytes và giới hạn kích thước từng file;
   - lưu từng file vào object storage;
   - tạo `upload_batches` và một dòng `upload_batch_items` cho mỗi file;
   - enqueue một task `parse_cv(tenant_id, item_id)` cho mỗi file. Task được enqueue **sau khi commit** bằng hook `on_commit`.
2. Mỗi task:
   - kiểm tra trùng lặp bằng SHA-256;
   - trích văn bản (pypdf / python-docx, hoặc OCR bằng model đa phương thức khi cần);
   - gọi LLM structured output với JSON Schema;
   - kiểm chứng các trường với văn bản gốc;
   - tách thông tin nhân khẩu học ra, tạo Blind Profile;
   - tạo embedding;
   - upsert Candidate (chống trùng theo email), `cv_documents` và `applications`;
   - đánh dấu item `SUCCEEDED`, hoặc `FAILED` kèm mã lỗi.
3. Sự kiện tiến độ được publish lên Redis và stream qua SSE. Batch `COMPLETED` khi không còn item `PENDING`. Số đếm lấy từ các dòng item, không dùng chord.

### 5.2. Scoring Run

1. `POST /jobs/{id}/scoring-runs` đóng băng trọng số, criteria, model, `prompt_version` và `rubric_version` vào `scoring_runs`, rồi enqueue `score_application(tenant_id, run_id, application_id)` cho mỗi Application.
2. Mỗi task:
   1. tính Must-have Coverage tất định: chuẩn hóa kỹ năng → khớp alias → độ tương đồng embedding trên ngưỡng;
   2. yêu cầu LLM chấm rubric có neo 1–5 kèm Evidence trích nguyên văn, với cấu hình tái lập của FR-A1.3, theo JSON Schema, chỉ trên Blind Profile;
   3. đối chiếu Evidence với văn bản gốc và loại các quote không tìm thấy;
   4. tính điểm từng trục và Total;
   5. **upsert** theo `(scoring_run_id, application_id)`;
   6. ghi một dòng `ai_usage_entries`.
3. Task bị retry hoặc giao lại sẽ ghi đè dòng của chính nó, không bao giờ tạo bản trùng.

### 5.3. Campaign với Checkpoint bền vững (ADR-0004)

1. `POST /campaigns` tạo Campaign (`PLANNING`) và enqueue `run_campaign(tenant_id, campaign_id)` vào queue `agent`.
2. Worker gọi graph LangGraph với `thread_id = campaign_id` và Postgres checkpointer.
3. Graph lặp **plan → act → reflect**. Mỗi tool là một lời gọi domain service được bọc bởi **capability check**: tool của agent chỉ có capability tạo _dữ liệu dẫn xuất_ (tạo Scoring Run, ghi đề xuất), không bao giờ có capability _thay đổi_ (đổi Stage, tạo Application, gửi email, sửa Job). Mỗi bước được append vào `campaign_events`.
4. Khi tới Checkpoint:
   - ghi `campaign_proposals`;
   - đặt `status = AWAITING_DECISION`;
   - publish một event SSE;
   - gọi `interrupt()`.

   Task kết thúc và slot của worker được giải phóng.

5. Recruiter Decision (`POST /campaigns/{id}/decision`) được lưu, và `resume_campaign(tenant_id, campaign_id, decision)` được enqueue.
6. Task resume gọi graph với `Command(resume=decision)`:
   - **APPROVE:** áp dụng các đề xuất được chấp nhận qua domain service thông thường, **dưới tên Recruiter** (đổi Stage, tạo Application từ Rediscovery), rồi `APPROVED`.
   - **REVISE:** quay lại plan.
   - **REJECT:** `REJECTED`, không thay đổi gì trong ATS.
7. Các chốt chặn (giới hạn ở FR-A0):
   - ngân sách thời gian máy mỗi lượt (NFR-PERF-05);
   - trần chi phí mỗi Campaign, đối chiếu với `ai_usage_entries`;
   - `beat` cho hết hạn các Checkpoint quá thời hạn quyết định.

**State của LangGraph** — chỉ chứa ID và tóm tắt, dữ liệu lớn nằm trong DB:

```python
class CampaignState(TypedDict):
    tenant_id: str
    campaign_id: str
    job_id: str
    brief: str
    target_count: int

    plan: list[PlannedStep]          # tool + lý do
    executed: list[ExecutedStep]     # tool + kết quả tóm tắt + thời gian + chi phí
    scoring_run_id: str | None
    qualified_count: int
    rediscovery_candidate_ids: list[str]
    what_if_suggestions: list[WhatIfSuggestion]
    draft_shortlist_application_ids: list[str]

    reflection_count: int            # giới hạn: FR-A0
    revision_count: int              # giới hạn: FR-A0
    escalation_reason: str | None
```

### 5.4. Email (outbox)

1. Gửi một bản nháp sẽ đặt `email_messages.status = QUEUED` trong cùng transaction với thay đổi nghiệp vụ (ví dụ từ chối hàng loạt).
2. Hook `on_commit` enqueue `send_email(tenant_id, email_id)`.
3. Worker gửi qua nhà cung cấp với `email_id` làm idempotency key, rồi đặt dòng thành `SENT` hoặc `FAILED`.
4. Lượt quét của `beat` enqueue lại các dòng kẹt ở `QUEUED` quá 10 phút, xử lý trường hợp mất lệnh enqueue.

### 5.5. Talent Rediscovery

Truy vấn là một câu SQL duy nhất chạy dưới RLS:

```sql
SELECT ... FROM cv_documents d JOIN candidates c ...
WHERE c.anonymized_at IS NULL
  AND NOT EXISTS (SELECT 1 FROM applications a WHERE a.job_id = :job AND a.candidate_id = c.id)
ORDER BY d.embedding <=> :job_embedding
LIMIT 50
```

Index HNSW giữ truy vấn nhanh. Cô lập không cần thêm điều kiện lọc, vì RLS đã giới hạn các dòng.

---

## 6. Chịu lỗi & Phục hồi

| Vấn đề                      | Cơ chế                                                                                                                                                      |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Worker chết giữa task       | `acks_late=True` và `task_reject_on_worker_lost=True`; task idempotent nhờ khóa duy nhất tự nhiên                                                           |
| LLM timeout / 429 / 5xx     | Retry với backoff theo FR-C2.3, sau đó item `FAILED` kèm button chạy lại                                                                                    |
| Nhà cung cấp LLM sập        | Circuit breaker trong Redis theo ngưỡng của FR-C2.3. Tác vụ AI mới phải chờ, UI hiện banner, chức năng không dùng AI vẫn hoạt động.                         |
| Noisy neighbour             | Semaphore đồng thời theo tenant trong Redis (`tenants.max_llm_concurrency`, giới hạn theo FR-C1.4), cộng kiểm tra AI Budget trước khi enqueue               |
| Mất lệnh enqueue sau commit | Các dòng trạng thái kiểu outbox (`upload_batch_items`, `email_messages`, `score_results`) cộng lượt quét của `beat` cho các dòng `PENDING`/`QUEUED` bị treo |
| Kéo thẻ Kanban đồng thời    | Optimistic locking trên `applications.version`                                                                                                              |
| Mất Redis                   | Redis không giữ dữ liệu bền. Task đang chạy được khôi phục nhờ lượt quét dòng treo; client SSE kết nối lại và tải lại dữ liệu.                              |
| Mất dữ liệu                 | Backup PostgreSQL hằng ngày lên object storage, bật versioning cho object storage; thời gian giữ, RPO, RTO và diễn tập restore theo NFR-REL-01              |

---

## 7. An toàn AI & Quản trị

- **Cấu trúc prompt:** văn bản tài liệu không tin cậy nằm trong `<untrusted_document>`. Lời gọi chấm điểm không có tool, và output bị ràng buộc bởi JSON Schema với điểm là số nguyên từ 1 đến 5.
- **Grounding:** mọi quote Evidence được đối chiếu với văn bản gốc, nhận định không kiểm chứng được bị gắn cờ.
- **Blind Profile:** thông tin nhân khẩu học bị loại trước khi chấm điểm. Các proxy đã biết được liệt kê ở SRS FR-C2.4.
- **Quyền quyết định của con người:** tập capability của agent loại trừ mọi thao tác thay đổi (§5.3). Bất biến này được thực thi bằng code và test, không bằng prompt.
- **Tái lập:** mỗi Scoring Run và Score Result lưu model, prompt version, rubric version và trọng số. Prompt là file có version trong repo.
- **Tối thiểu hóa dữ liệu:** chỉ gửi văn bản cho nhà cung cấp LLM, không gửi ảnh. Nhà cung cấp được dùng theo điều khoản API không huấn luyện trên dữ liệu.

---

## 8. Quan sát (Observability)

- Log JSON bằng `structlog` mang `request_id`, `tenant_id`, `user_id` và `task_id`.
- Flower cho độ sâu queue và task lỗi.
- `ai_usage_entries` cho chi phí theo tenant, tính năng và model.
- `campaign_events` cho trace của agent.
- Langfuse tracing (P2), che PII trước khi xuất.

**Health check** (yêu cầu: NFR-REL-05):

| Service    | Liveness                      | Readiness (DB, Redis, object storage) |
| ---------- | ----------------------------- | ------------------------------------- |
| `api`      | `GET /api/health` — đã có     | `GET /api/ready` — đã có              |
| `worker-*` | Celery inspect ping — chưa có | —                                     |

Healthcheck của Docker Compose cho `api`, `web` và `caddy` chỉ mở kết nối TCP, không gọi endpoint HTTP, để không làm đầy access log. `/api/ready` là endpoint kiểm tra khi cần, không để poller gọi định kỳ: trả 200 khi DB, Redis và object storage đều kết nối được, trả 503 kèm danh sách phụ thuộc lỗi (`database`, `redis`, `object_storage`) khi không.

---

## 9. Triển khai

- **Local / staging:** Docker Compose gồm:
  - Caddy (TLS, reverse proxy), `web`, `api`;
  - `worker-llm`, `worker-default`, `worker-agent`, `worker-email`, `beat`;
  - `postgres` (image có pgvector), `redis`, `seaweedfs`, `mailpit`, `flower`.
- **Production cho demo:** cùng file Compose trên một VPS (≥ 4 vCPU / 8 GB RAM), với S3 managed và nhà cung cấp email managed; backup PostgreSQL hằng ngày lên object storage.
- **CI (GitHub Actions)** trên mọi PR vào `develop` và `main`:
  - hiện có: Prettier, ESLint, TypeScript, Ruff, mypy, unit test (pytest, Vitest), và smoke test hạ tầng (dựng toàn bộ stack bằng Compose);
  - cần bổ sung (Roadmap GĐ 1): integration test RLS trên PostgreSQL thật (testcontainers), build image.
- **Hướng mở rộng (ngoài phạm vi):** `api` và worker stateless nên mở rộng ngang được. PostgreSQL có read replica cho báo cáo. Ngoài `beat`, thiết kế không giả định chạy trên một node.
