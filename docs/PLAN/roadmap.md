# Lộ trình Phát triển (Roadmap)

## Smart ATS — Kế hoạch theo Giai đoạn

**Phiên bản:** 3.5
**Ngày:** 2026-11-12
**Đối tượng đọc:** Nhóm phát triển, GVHD

> Roadmap là nguồn sự thật cho **giai đoạn, tiêu chí hoàn thành và rủi ro dự án**. Việc cụ thể và trạng thái từng việc nằm trong GitHub issues; file này chỉ ghi trạng thái ở mức giai đoạn. Yêu cầu được dẫn bằng mã SRS (FR-…, NFR-…), thực nghiệm bằng tên (Experiment 1…6, xem [Kế hoạch Thực nghiệm](../EVAL/experiment_plan.md)).

---

## 1. Nguyên tắc

1. **Đóng góp chính đi trước.** Scoring core và eval harness bắt đầu từ GĐ 1, chạy offline trên dataset, không chờ UI hay pipeline ATS. Chất lượng prompt là bottleneck thực sự, nên cần nhiều vòng lặp nhất.
2. **Vertical Slice mỏng.** GĐ 1 chỉ làm đủ để một flow Job → CV → Score → Fit-Gap chạy thật trên nền RLS; quản lý Workspace và Member để sau.
3. **Dữ liệu đi trước.** Nhãn của người chấm HR là phụ thuộc bên ngoài lớn nhất, nên nhãn tập dev là tiêu chí hoàn thành GĐ 1 và nhãn tập test là tiêu chí hoàn thành GĐ 2.
4. **Test bảo mật viết trước tính năng.** Mỗi bảng, endpoint hoặc task mới có test xuyên tenant đi kèm (checklist trong [CONTRIBUTING.md](../../CONTRIBUTING.md#checklist-review-bảo-mật)).
5. **Đóng băng trước khi đo.** Lượt chạy thực nghiệm chính thức dùng model, prompt và rubric đã gắn tag; không tinh chỉnh trên tập test.
6. **Viết báo cáo dần.** Mỗi giai đoạn chốt một chương.
7. **Phần cốt lõi.** Chấm điểm lai cùng Experiment 1, 2, 6; Forced RLS cùng Experiment 4; Agent cùng Experiment 3; Public Apply Link; Kanban cơ bản; consent và xóa dữ liệu.

---

## 2. Tổng quan Giai đoạn

| Giai đoạn                              | Trạng thái                                    |
| -------------------------------------- | --------------------------------------------- |
| **0. Nền tảng dự án**                  | ✅                                            |
| **1. Vertical Slice**                  | ✅ phần kỹ thuật & tập dev (còn báo cáo §3.1) |
| **2. Chất lượng chấm điểm & ATS lõi**  | 🔄 đang thực hiện (§3.2)                      |
| **3. Hoàn thiện ATS**                  | ⬜ (đã làm trước FR-A3.4 và một phần FR-A3.5) |
| **4. Agent**                           | ⬜                                            |
| **5. Thực nghiệm chính thức & gia cố** | ⬜                                            |
| **6. Hoàn thiện & bảo vệ**             | ⬜                                            |

Mỗi giai đoạn chia thành ba workstream: **Nền tảng** (backend, bảo mật, pipeline ATS), **AI & Thực nghiệm** (extract, chấm điểm, agent, eval harness), **Dữ liệu & Báo cáo**.

---

## 3. Chi tiết Giai đoạn

### 3.0. GĐ 0 — Nền tảng dự án

Đã xong:

- Ý tưởng và tài liệu: SRS/PRD/SAD/ERD, ADR 0001–0006, `CONTEXT.md` (#1, #3); cấu trúc context cho AI agent (#4); tài liệu tham khảo (#14); tái cấu trúc tài liệu v3.2.
- Monorepo, biến môi trường, skeleton web/API/Celery và test runner (#7, #18); branch `develop` (#6).
- Hạ tầng Docker Compose: PostgreSQL 18 + pgvector với hai role (#8), Redis + Flower (#9), SeaweedFS + Mailpit (#10), container ứng dụng và topology queue (#11), Caddy với SSE (#12), smoke test hạ tầng (#13).
- Formatter, linter, type check, git hook và CI (#15).
- Kế hoạch dataset (#43 chọn 6 Job, #44 hướng dẫn chấm) và xác nhận 2 người chấm HR (#42).

**Tiêu chí hoàn thành:** CI xanh ✅; kế hoạch dataset + 2 người chấm xác nhận ✅.

### 3.1. GĐ 1 — Vertical Slice

**Nền tảng**

- ✅ CI chạy unit test (pytest, Vitest) song song với format, lint, type check và smoke test (#30).
- ✅ Alembic chạy bằng `ats_owner`; schema tối thiểu cho lát cắt (`tenants`, `users`, `refresh_tokens`, `jobs`, `candidates`, `cv_documents`, `applications`, `scoring_runs`, `score_results`, `ai_usage_entries`).
- ✅ Forced RLS, `tenant_session` (async cho API, sync cho worker), `@tenant_task` và bước CI kiểm tra task (ADR-0001, ADR-0002; #31, #34, #63, #68).
- ✅ Bộ test RLS xuyên tenant trên PostgreSQL thật (testcontainers) chạy trong CI (#61).
- ✅ Đăng nhập bằng mật khẩu, access/refresh token (FR-C1.1, chưa cần Google; #32, #66); tenant và user tạo bằng lệnh seed.
- ✅ Readiness check cho `api` (NFR-REL-05, #33).
- ✅ SSE ticket và event tiến độ thật (ADR-0003; #35, #67).

**AI & Thực nghiệm**

- ✅ Extract PDF/DOCX và JSON Schema cho JD/CV (FR-C2.1, #37); parse Job và form xác nhận criteria (FR-A1.1, #39).
- ✅ Upload 1 CV → parse → Blind Profile v0 → chấm 1 Application (rubric v0 + Must-have Coverage khớp chính xác/alias) → màn hình Fit-Gap (#38, #40, #41, #64).
- ✅ Scoring core gọi được trực tiếp từ eval harness, không cần API hay Celery.
- ✅ Eval harness v0 trong `packages/eval`: đọc dataset, tính Spearman ρ, NDCG@5, Precision@5, grounding rate, stability; cấu hình Baseline (#36, #65).

**Dữ liệu & Báo cáo**

- ✅ Hướng dẫn chấm cho HR (#44); thu thập 6 Job (#43) và CV; HR chấm xong **tập dev** `hr-v1` (#45, `for_report: false` dùng để tinh chỉnh).
- ⬜ Đối chiếu nguồn cho các nhận định ở PRD §1.1, hoặc lên kế hoạch khảo sát SME (#46).
- ⬜ Báo cáo: chương Cơ sở lý thuyết (từ danh sách tài liệu tham khảo, #47).

**Tiêu chí hoàn thành:**

- ✅ Flow Job → CV → Score → Fit-Gap chạy end-to-end trên Docker Compose.
- ✅ ≥ 15 test RLS xuyên tenant pass trong CI (`tests/test_tenancy.py`).
- ✅ Eval harness in bảng so sánh Baseline với scoring v0 trên tập dev.
- ✅ Nhãn tập dev hoàn tất (#45).

### 3.2. GĐ 2 — Chất lượng chấm điểm & ATS lõi

Phần không cần nhãn (workstream Nền tảng, cùng retry, idempotency và chế độ degraded) làm song song trong lúc HR chấm tập dev. Tinh chỉnh prompt và rubric chỉ bắt đầu khi đã có bảng của GĐ 1 trên tập dev, đo trên Scoring v0 gắn tag `scoring-v0`.

**AI & Thực nghiệm**

- ✅ Scoring v1 đủ FR-A1.3: chuẩn hóa kỹ năng, alias, khớp embedding, Experience timeline tất định, rubric có neo, grounding (#107–#109).
- 🔄 Blind Profile & an toàn AI: đã che định danh cơ bản trong `blind_profile` (FR-C2.4) và cô lập `<untrusted_document>` (#62); ⬜ phát hiện heuristic (FR-C2.2), bộ CV tấn công Experiment 2 và OCR fallback (FR-C2.1).
- 🔄 Đủ 6 cấu hình ablation của Experiment 1 trong harness (#110) và đã chạy sơ bộ trên `hr-v1` split `dev` (#119); ⬜ tinh chỉnh prompt/rubric trên tập dev để cải thiện Grounding và Spearman ρ, cùng lượt chạy đo Stability (`--runs >= 2`).
- ⬜ Retry, idempotency, chế độ degraded (FR-C2.3, #88).

**Nền tảng**

- ✅ Upload Batch với cô lập lỗi (FR-A1.2, #82).
- ✅ Vòng đời Job (FR-A3.1, #85); pipeline Application, Kanban, lịch sử Stage, optimistic locking (FR-A3.2, #86).
- ✅ Workspace, Member, lời mời (FR-C1.2, #83) và email outbox gửi qua Mailpit.
- ✅ Reviewer Assignment và test cho mọi ô ❌/Assigned của ma trận RBAC đã hiện thực (SRS §2.2, #84).
- 🔄 AI Usage Ledger (`app/usage.py`), ⬜ AI Budget và giới hạn đồng thời (FR-C1.4, #87).
- ✅ Giao diện song ngữ Vi/En (NFR-USE-03, #93): dựng `next-intl`, chuyển các trang đã có sang file ngôn ngữ, email theo ngôn ngữ người thao tác.

**Dữ liệu & Báo cáo**

- 🔄 Thu CV cho **tập test** và thu nhãn HR (#81).
- ⬜ Xác nhận với GVHD các nghĩa vụ theo Nghị định 13/2023/NĐ-CP và Luật Bảo vệ dữ liệu cá nhân (FR-C1.5), trước khi làm phần bảo vệ dữ liệu ở GĐ 3.
- ⬜ Báo cáo: chương Phân tích yêu cầu (từ PRD, SRS).

**Tiêu chí hoàn thành:**

- 🔄 Experiment 1 sơ bộ trên tập dev đã chạy (#119); Experiment 2 sơ bộ trên tập dev ⬜.
- ✅ Test ma trận RBAC pass (các ô của tính năng chưa làm còn đánh dấu skip theo FR).
- ⬜ Nhãn tập test hoàn tất (#81).

### 3.3. GĐ 3 — Hoàn thiện ATS

**Nền tảng**

- ✅ Public Apply Link (FR-A3.4, #96).
- 🔄 Đăng tin Đa kênh (FR-A3.5, #94): đã xong Meta app/Page (#95) và soạn Job Ad / share intent / Open Graph / `JobPosting` (#97); ⬜ kết nối và đăng lên Facebook Page (#98, #99).
- Activity Timeline & Audit Log (FR-A3.3).
- Comment, @mention, notification, Interview Score (FR-A2.2).
- Bảo vệ dữ liệu: consent, job retention, xóa dữ liệu (FR-C1.5).
- Bộ test Experiment 4 đầy đủ.

**AI & Thực nghiệm**

- Talent Rediscovery (FR-A1.6); câu hỏi phỏng vấn (FR-A1.4); trợ lý email soạn theo tone (FR-A2.1).
- Experiment 6 sơ bộ trên tập dev.
- Viết các kịch bản của Experiment 3 cùng tập hành động chấp nhận được, và baseline workflow, **trước** khi code Agent.
- PDF (FR-A1.5, P2).

**Dữ liệu & Báo cáo**

- Báo cáo: chương Thiết kế hệ thống (từ SAD, ERD, ADR).

**Tiêu chí hoàn thành:**

- Mọi FR P1 trừ FR-A0 hoàn tất.
- Bộ test Experiment 4 pass, 0 rò rỉ.
- Kịch bản Experiment 3 đã chốt.

### 3.4. GĐ 4 — Agent

- LangGraph Plan/Act/Reflect; tool kèm capability check; Postgres checkpointer với interrupt/resume (FR-A0, ADR-0004).
- What-if (`simulate_criteria_change`); giao diện Checkpoint và Recruiter Decision.
- Baseline workflow cho Experiment 3; test bất biến của Agent.
- Tuyển người tham gia usability test (NFR-USE-01) và viết kịch bản test.
- Báo cáo: phần Agent trong chương Thiết kế.

**Tiêu chí hoàn thành:**

- Experiment 3 chạy đủ kịch bản trên tập dev.
- Test bất biến pass.

### 3.5. GĐ 5 — Thực nghiệm chính thức & gia cố

- Trước lượt chạy chính thức: gắn git tag đóng băng model, prompt version, rubric version.
- Chạy chính thức Experiment 1–6 trên tập test.
- Load test (Experiment 5); security review theo checklist; diễn tập restore (NFR-REL-01); usability test (NFR-USE-01).
- Báo cáo: chương Thực nghiệm, viết song song khi có số liệu.

**Tiêu chí hoàn thành:** có số liệu cuối cùng cho mọi thực nghiệm.

### 3.6. GĐ 6 — Hoàn thiện & bảo vệ

- Hoàn thiện báo cáo, slide, video demo.
- **Đóng băng tính năng**: chỉ sửa lỗi.

**Tiêu chí hoàn thành:** bản demo stable trên staging; báo cáo hoàn chỉnh.

---

## 4. Theo dõi

- Mỗi giai đoạn tương ứng một GitHub Milestone; mọi issue của giai đoạn gắn milestone đó.
- Từ GĐ 2, sau mỗi vòng tinh chỉnh prompt, chạy eval harness trên tập dev và so với vòng trước.
- Khi kết thúc một giai đoạn: rà tiêu chí hoàn thành, cập nhật cột Trạng thái ở §2.

---

## 5. Rủi ro

CRUD, UI và hạ tầng không phải bottleneck. Bottleneck thực sự là dataset và người chấm HR, vòng lặp chất lượng prompt, tính đúng đắn bảo mật, và băng thông review code.

| Rủi ro                                                                                    | Mức        | Giảm thiểu                                                                                                                                                                             |
| ----------------------------------------------------------------------------------------- | ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Không tìm được / chậm có 2 người chấm HR                                                  | Cao        | Liên hệ sớm (qua GVHD, cựu sinh viên, công ty thực tập); nhãn tập dev và tập test là tiêu chí hoàn thành GĐ 1 và GĐ 2; dự phòng: 1 HR + 1 recruiter kỹ thuật, báo cáo Kappa trung thực |
| Sai sót bảo mật tinh vi trong code do coding agent sinh ra (quên tenant context, lộ file) | Cao        | Test RLS viết **trước** tính năng; CI chặn merge; checklist review bảo mật; Experiment 4                                                                                               |
| Chất lượng scoring không đạt kỳ vọng                                                      | Trung bình | Eval harness từ GĐ 1, tinh chỉnh lặp lại từ GĐ 2; ablation cho thấy đóng góp từng thành phần dù số tuyệt đối thấp                                                                      |
| Rate limit / chi phí OpenAI                                                               | Trung bình | Giới hạn đồng thời; LLM giả lập cho load test; AI Budget; theo dõi chi phí qua ledger                                                                                                  |
| Băng thông review code không theo kịp tốc độ sinh code                                    | Cao        | PR nhỏ theo vertical slice; test là điều kiện merge; không merge code không hiểu                                                                                                       |
| Nghĩa vụ pháp lý về dữ liệu cá nhân chưa rõ                                               | Trung bình | Xác nhận với GVHD trong GĐ 2; FR-C1.5; nêu rõ giới hạn trong báo cáo                                                                                                                   |
| Tập test bị "nhiễm" do tinh chỉnh prompt                                                  | Trung bình | Chỉ tinh chỉnh trên tập dev; đóng băng bằng git tag trước lượt chạy chính thức                                                                                                         |
| Thay đổi model/API của nhà cung cấp                                                       | Thấp       | Model qua cấu hình; lưu model + prompt version trong mọi kết quả                                                                                                                       |
