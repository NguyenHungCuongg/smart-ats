# Lộ trình Phát triển (Roadmap)

## Smart ATS — Kế hoạch 26 Tuần

**Phiên bản:** 3.3
**Ngày:** 2026-10-19
**Đối tượng đọc:** Nhóm phát triển, GVHD

> Roadmap là nguồn sự thật cho **giai đoạn, mốc, phân công và rủi ro dự án**. Việc cụ thể và trạng thái từng việc nằm trong GitHub issues; file này chỉ ghi trạng thái ở mức giai đoạn. Yêu cầu được dẫn bằng mã SRS (FR-…, NFR-…), thực nghiệm bằng tên (Experiment 1…6, xem [Kế hoạch Thực nghiệm](../EVAL/experiment_plan.md)).

**Mốc thời gian:** Tuần 1 bắt đầu thứ Hai 28/09/2026; tuần 26 kết thúc Chủ nhật 28/03/2027. Tết Nguyên Đán 2027 (mùng 1 dự kiến 06/02/2027) rơi vào cuối T19 – đầu T20.

---

## 1. Nguyên tắc

1. **Đóng góp chính đi trước.** Scoring core và eval harness bắt đầu từ GĐ 1, chạy offline trên dataset, không chờ UI hay pipeline ATS. Chất lượng prompt là bottleneck thực sự, nên cần nhiều vòng lặp nhất.
2. **Vertical Slice mỏng.** GĐ 1 chỉ làm đủ để một flow Job → CV → Score → Fit-Gap chạy thật trên nền RLS; quản lý Workspace và Member để sau.
3. **Dữ liệu có hạn chót.** Nhãn của người chấm HR là phụ thuộc bên ngoài lớn nhất, nên có mốc cứng: tập dev xong trước M1, tập test xong trước M2.
4. **Test bảo mật viết trước tính năng.** Mỗi bảng, endpoint hoặc task mới có test xuyên tenant đi kèm (checklist trong [CONTRIBUTING.md](../../CONTRIBUTING.md#checklist-review-bảo-mật)).
5. **Đóng băng trước khi đo.** Lượt chạy thực nghiệm chính thức dùng model, prompt và rubric đã gắn tag; không tinh chỉnh trên tập test.
6. **Viết báo cáo dần.** Mỗi giai đoạn chốt một chương, tháng cuối chỉ hoàn thiện.
7. **Có đệm, có danh sách cắt.** Một tuần đệm trùng Tết; khi trễ mốc thì cắt theo §5 thay vì ăn vào thời gian thực nghiệm.

---

## 2. Tổng quan Giai đoạn

| Giai đoạn                              | Tuần  | Thời gian               | Mốc | Trạng thái            |
| -------------------------------------- | ----- | ----------------------- | --- | --------------------- |
| **0. Nền tảng dự án**                  | 1–2   | 28/09 – 11/10/2026      | M0  | ✅ trừ dữ liệu (§3.0) |
| **1. Vertical Slice**                  | 3–6   | 12/10 – 08/11/2026      | M1  | ⬜                    |
| **2. Chất lượng chấm điểm & ATS lõi**  | 7–11  | 09/11 – 13/12/2026      | M2  | ⬜                    |
| **3. Hoàn thiện ATS**                  | 12–15 | 14/12/2026 – 10/01/2027 | M3  | ⬜                    |
| **4. Agent**                           | 16–19 | 11/01 – 07/02/2027      | M4  | ⬜                    |
| _Tết + tuần đệm_                       | 20    | 08/02 – 14/02/2027      | —   | ⬜                    |
| **5. Thực nghiệm chính thức & gia cố** | 21–23 | 15/02 – 07/03/2027      | M5  | ⬜                    |
| **6. Hoàn thiện & bảo vệ**             | 24–26 | 08/03 – 28/03/2027      | M6  | ⬜                    |

Mỗi giai đoạn chia thành ba workstream chạy song song: **Nền tảng** (backend, bảo mật, pipeline ATS), **AI & Thực nghiệm** (extract, chấm điểm, agent, eval harness), **Dữ liệu & Báo cáo**.

---

## 3. Chi tiết Giai đoạn

### 3.0. GĐ 0 — Nền tảng dự án (T1–2)

Đã xong:

- Ý tưởng và tài liệu: SRS/PRD/SAD/ERD, ADR 0001–0006, `CONTEXT.md` (#1, #3); cấu trúc context cho AI agent (#4); tài liệu tham khảo (#14); tái cấu trúc tài liệu v3.2.
- Monorepo, biến môi trường, skeleton web/API/Celery và test runner (#7, #18); branch `develop` (#6).
- Hạ tầng Docker Compose: PostgreSQL 18 + pgvector với hai role (#8), Redis + Flower (#9), SeaweedFS + Mailpit (#10), container ứng dụng và topology queue (#11), Caddy với SSE (#12), smoke test hạ tầng (#13).
- Formatter, linter, type check, git hook và CI (#15).

Còn lại:

- ⬜ Kế hoạch dataset và xác nhận 2 người chấm HR (chưa ghi nhận trong repo).

**M0:** CI xanh ✅; kế hoạch dataset + 2 người chấm xác nhận ⬜.

### 3.1. GĐ 1 — Vertical Slice (T3–6)

**Nền tảng**

- CI chạy unit test (pytest, Vitest); hiện CI mới chạy format, lint, type check và smoke test.
- Alembic chạy bằng `ats_owner`; schema tối thiểu cho lát cắt (`tenants`, `users`, `refresh_tokens`, `jobs`, `candidates`, `cv_documents`, `applications`, `scoring_runs`, `score_results`, `ai_usage_entries`).
- Forced RLS, `tenant_session` (async cho API, sync cho worker), `@tenant_task` và bước CI kiểm tra task (ADR-0001, ADR-0002).
- Bộ test RLS xuyên tenant trên PostgreSQL thật (testcontainers) chạy trong CI.
- Đăng nhập bằng mật khẩu, access/refresh token (FR-C1.1, chưa cần Google); tenant và user tạo bằng lệnh seed.
- Readiness check cho `api` (NFR-REL-05).
- SSE ticket và event tiến độ thật (ADR-0003).

**AI & Thực nghiệm**

- Extract PDF/DOCX và JSON Schema cho JD/CV (FR-C2.1); parse Job và form xác nhận criteria (FR-A1.1).
- Upload 1 CV → parse → Blind Profile v0 → chấm 1 Application (rubric v0 + Must-have Coverage khớp chính xác/alias) → màn hình Fit-Gap.
- Scoring core gọi được trực tiếp từ eval harness, không cần API hay Celery.
- Eval harness v0 trong `packages/eval`: đọc dataset, tính Spearman ρ, NDCG@5, Precision@5, grounding rate, stability; cấu hình Baseline.

**Dữ liệu & Báo cáo**

- Hướng dẫn chấm cho HR; thu thập 6 Job và CV; HR chấm xong **tập dev**.
- Đối chiếu nguồn cho các nhận định ở PRD §1.1, hoặc lên kế hoạch khảo sát SME.
- Báo cáo: chương Cơ sở lý thuyết (từ danh sách tài liệu tham khảo).

**M1:**

- Flow Job → CV → Score → Fit-Gap chạy end-to-end trên Docker Compose.
- ≥ 15 test RLS xuyên tenant pass trong CI.
- Eval harness in bảng so sánh Baseline với scoring v0 trên tập dev.
- Nhãn tập dev hoàn tất.

### 3.2. GĐ 2 — Chất lượng chấm điểm & ATS lõi (T7–11)

Phần không cần nhãn (workstream Nền tảng, cùng retry, idempotency và chế độ degraded) bắt đầu sớm từ T4, trong lúc HR chấm tập dev. Tinh chỉnh prompt và rubric chỉ bắt đầu khi đã có bảng của M1 trên tập dev, đo trên Scoring v0 gắn tag `scoring-v0`.

**AI & Thực nghiệm**

- Scoring v1 đủ FR-A1.3: chuẩn hóa kỹ năng, alias, khớp embedding, rubric có neo, grounding.
- Blind Profile đầy đủ (FR-C2.4); phòng thủ prompt injection (FR-C2.2) và bộ CV tấn công của Experiment 2.
- Đủ các cấu hình ablation của Experiment 1 trong harness; mỗi tuần một vòng tinh chỉnh prompt trên tập dev.
- Retry, idempotency, chế độ degraded (FR-C2.3).

**Nền tảng**

- Upload Batch với cô lập lỗi (FR-A1.2).
- Vòng đời Job (FR-A3.1); pipeline Application, Kanban, lịch sử Stage, optimistic locking (FR-A3.2).
- Workspace, Member, lời mời (FR-C1.2) và email outbox gửi qua Mailpit (cần cho lời mời).
- Reviewer Assignment và test cho mọi ô ❌/Assigned của ma trận RBAC (SRS §2.2).
- AI Usage Ledger, AI Budget, giới hạn đồng thời (FR-C1.4).

**Dữ liệu & Báo cáo**

- Thu CV cho **tập test** từ T4, song song với lúc HR chấm tập dev; HR chấm xong tập test (hạn cuối T10).
- Xác nhận với GVHD các nghĩa vụ theo Nghị định 13/2023/NĐ-CP và Luật Bảo vệ dữ liệu cá nhân (FR-C1.5), trước khi làm phần bảo vệ dữ liệu ở GĐ 3.
- Báo cáo: chương Phân tích yêu cầu (từ PRD, SRS).

**M2:**

- Experiment 1 và 2 sơ bộ trên tập dev, có đủ các cấu hình ablation.
- Test ma trận RBAC pass.
- Nhãn tập test hoàn tất.

### 3.3. GĐ 3 — Hoàn thiện ATS (T12–15)

**Nền tảng**

- Public Apply Link (FR-A3.4).
- Activity Timeline & Audit Log (FR-A3.3).
- Comment, @mention, notification, Interview Score (FR-A2.2).
- Bảo vệ dữ liệu: consent, job retention, xóa dữ liệu (FR-C1.5).
- Bộ test Experiment 4 đầy đủ.

**AI & Thực nghiệm**

- Talent Rediscovery (FR-A1.6); câu hỏi phỏng vấn (FR-A1.4); trợ lý email soạn theo tone (FR-A2.1).
- Experiment 6 sơ bộ trên tập dev.
- Viết các kịch bản của Experiment 3 cùng tập hành động chấp nhận được, và baseline workflow, **trước** khi code Agent.
- PDF (FR-A1.5, P2) nếu còn thời gian.

**Dữ liệu & Báo cáo**

- Báo cáo: chương Thiết kế hệ thống (từ SAD, ERD, ADR).

**M3:**

- Mọi FR P1 trừ FR-A0 hoàn tất.
- Bộ test Experiment 4 pass, 0 rò rỉ.
- Kịch bản Experiment 3 đã chốt.

### 3.4. GĐ 4 — Agent (T16–19)

- LangGraph Plan/Act/Reflect; tool kèm capability check; Postgres checkpointer với interrupt/resume (FR-A0, ADR-0004).
- What-if (`simulate_criteria_change`); giao diện Checkpoint và Recruiter Decision.
- Baseline workflow cho Experiment 3; test bất biến của Agent.
- Tuyển người tham gia usability test (NFR-USE-01) và viết kịch bản test.
- Báo cáo: phần Agent trong chương Thiết kế.

**M4:**

- Experiment 3 chạy đủ kịch bản trên tập dev.
- Test bất biến pass.

### 3.5. T20 — Tết + tuần đệm

Không lên kế hoạch việc mới. Dùng để bù phần trễ của GĐ 4 hoặc các giai đoạn trước.

### 3.6. GĐ 5 — Thực nghiệm chính thức & gia cố (T21–23)

- Đầu T21: gắn git tag đóng băng model, prompt version, rubric version.
- Chạy chính thức Experiment 1–6 trên tập test.
- Load test (Experiment 5); security review theo checklist; diễn tập restore (NFR-REL-01); usability test (NFR-USE-01).
- Báo cáo: chương Thực nghiệm, viết song song khi có số liệu.

**M5:** có số liệu cuối cùng cho mọi thực nghiệm.

### 3.7. GĐ 6 — Hoàn thiện & bảo vệ (T24–26)

- Hoàn thiện báo cáo, slide, video demo.
- **Đóng băng tính năng**: chỉ sửa lỗi.

**M6:** bản demo stable trên staging; báo cáo nộp đúng hạn.

---

## 4. Phân công

Từ 19/10/2026 đồ án còn một thành viên, phụ trách cả ba workstream. Review chéo được thay bằng điều kiện merge ở [CONTRIBUTING.md](../../CONTRIBUTING.md#điều-kiện-merge).

Trong mỗi giai đoạn, ưu tiên theo thứ tự:

1. Việc phụ thuộc bên ngoài, vì phải chờ phản hồi: dataset, người chấm, văn bản đồng ý.
2. Tiêu chí của mốc gần nhất mà coding agent không làm thay được: nhãn, báo cáo.
3. Code, phần coding agent đỡ được nhiều nhất.

---

## 5. Khi Trễ Mốc: Thứ tự Cắt giảm

Tại mỗi mốc, nếu tiêu chí chưa đạt, cắt theo thứ tự dưới đây trước khi lấn sang thời gian của GĐ 5–6. Cắt một yêu cầu P1 nghĩa là hạ nó xuống P2 trong SRS (ghi vào lịch sử phiên bản) và báo GVHD.

1. Các mục đã là P2: PDF (FR-A1.5), CAPTCHA (FR-A3.4), Langfuse (NFR-REL-04), webhook bounce.
2. Giao diện tiếng Anh; vẫn giữ xử lý CV/JD song ngữ (NFR-USE-03).
3. Đăng nhập Google; giữ đăng nhập mật khẩu (FR-C1.1).
4. Notification và email cho @mention; giữ comment và Interview Score (FR-A2.2).
5. Email từ chối hàng loạt; giữ đổi Stage hàng loạt (FR-A3.2).

**Đã cắt (19/10/2026, khi đồ án còn một thành viên):** mục 1–3. Khối lượng mỗi giai đoạn tăng gấp đôi, và cắt trước GĐ 3 thì không phải dựng i18n cho mọi trang của GĐ 2. Đăng nhập Google và giao diện tiếng Anh đã hạ xuống P2 trong SRS v3.3. Mục 4–5 xét lại tại M2.

**Không cắt:** chấm điểm lai cùng Experiment 1, 2, 6; Forced RLS cùng Experiment 4; Agent cùng Experiment 3; Public Apply Link; Kanban cơ bản; consent và xóa dữ liệu.

---

## 6. Theo dõi

- Mỗi giai đoạn tương ứng một GitHub Milestone (M1…M6); mọi issue của giai đoạn gắn milestone đó.
- Từ GĐ 2, cuối mỗi tuần chạy eval harness trên tập dev và so với tuần trước.
- Tại mỗi mốc: rà tiêu chí, cập nhật cột Trạng thái ở §2, quyết định cắt giảm theo §5.

---

## 7. Khả thi & Rủi ro

**Khả thi:** khối lượng code khả thi với 1 thành viên cùng coding agent, sau khi cắt mục 1–3 ở §5; CRUD, UI và hạ tầng không phải bottleneck. Bottleneck thực sự là dataset và người chấm HR, vòng lặp chất lượng prompt, tính đúng đắn bảo mật, và băng thông review code.

| Rủi ro                                                                                    | Mức        | Giảm thiểu                                                                                                                                                                  |
| ----------------------------------------------------------------------------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Không tìm được / chậm có 2 người chấm HR                                                  | Cao        | Liên hệ từ tuần 1 (qua GVHD, cựu sinh viên, công ty thực tập); mốc cứng cho tập dev (M1) và tập test (T10); dự phòng: 1 HR + 1 recruiter kỹ thuật, báo cáo Kappa trung thực |
| Sai sót bảo mật tinh vi trong code do coding agent sinh ra (quên tenant context, lộ file) | Cao        | Test RLS viết **trước** tính năng; CI chặn merge; checklist review bảo mật; Experiment 4                                                                                    |
| Chất lượng scoring không đạt kỳ vọng                                                      | Trung bình | Eval harness từ GĐ 1, tinh chỉnh hằng tuần từ GĐ 2; ablation cho thấy đóng góp từng thành phần dù số tuyệt đối thấp                                                         |
| Rate limit / chi phí OpenAI                                                               | Trung bình | Giới hạn đồng thời; LLM giả lập cho load test; AI Budget; theo dõi chi phí qua ledger                                                                                       |
| Chỉ còn một thành viên: khối lượng mỗi giai đoạn tăng gấp đôi                             | Cao        | Cắt sớm mục 1–3 ở §5; ưu tiên theo §4; làm sớm phần GĐ 2 không cần nhãn                                                                                                     |
| Băng thông review code không theo kịp tốc độ sinh code; không còn review chéo             | Cao        | PR nhỏ theo vertical slice; test là điều kiện merge; `/code-review` và checklist bảo mật cho mỗi PR; không merge code không hiểu                                            |
| Nghĩa vụ pháp lý về dữ liệu cá nhân chưa rõ                                               | Trung bình | Xác nhận với GVHD trong GĐ 2; FR-C1.5; nêu rõ giới hạn trong báo cáo                                                                                                        |
| Tập test bị "nhiễm" do tinh chỉnh prompt                                                  | Trung bình | Chỉ tinh chỉnh trên tập dev; đóng băng bằng git tag trước lượt chạy chính thức                                                                                              |
| Tết và lịch học làm giảm thời gian làm việc ở T19–T20                                     | Trung bình | T20 là tuần đệm; Agent bắt đầu từ T16 để có đủ 4 tuần trước Tết                                                                                                             |
| Thay đổi model/API của nhà cung cấp                                                       | Thấp       | Model qua cấu hình; lưu model + prompt version trong mọi kết quả                                                                                                            |

---

## 8. Khác gì so với lộ trình trong SRS v3.1

| Thay đổi                                                                         | Lý do                                                                                  |
| -------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Eval harness và scoring core bắt đầu ở GĐ 1 (trước đây: harness ở GĐ 2, tuần 12) | Đóng góp chính cần nhiều vòng tinh chỉnh nhất; harness không phụ thuộc UI              |
| Kết quả Experiment 1–2 sơ bộ ở M2 (T11) thay vì T12                              | Phát hiện sớm nếu scoring không đạt                                                    |
| Có hạn chót cho nhãn tập dev (M1) và tập test (T10)                              | Rủi ro "Cao" trước đây không có mốc                                                    |
| Workspace, Member, lời mời chuyển từ GĐ 1 sang GĐ 2                              | Vertical Slice mỏng hơn; lời mời cần email outbox nên làm cùng nhau                    |
| Thêm bước CI chạy unit test ở đầu GĐ 1                                           | CI hiện chưa chạy pytest/Vitest; test RLS không chặn merge được nếu CI không chạy test |
| Kịch bản Experiment 3 viết trong GĐ 3, trước khi code Agent                      | Tránh thiết kế kịch bản theo những gì Agent làm được                                   |
| Agent T16–19 (trước đây T17–20), thêm T20 làm tuần đệm                           | Tết 2027 rơi vào T19–T20; lộ trình cũ không có tuần đệm                                |
| Đóng băng bằng git tag trước GĐ 5                                                | Bảo đảm quy tắc "không tinh chỉnh trên tập test" kiểm chứng được                       |
| Báo cáo viết theo chương ở mỗi giai đoạn                                         | Lộ trình cũ dồn toàn bộ báo cáo vào 3 tuần cuối                                        |
| Thêm danh sách cắt giảm                                                          | Gần như mọi FR là P1; cần biết trước cắt gì để giữ thời gian thực nghiệm               |
