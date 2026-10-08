# Kế hoạch Thực nghiệm

## Smart ATS — Đóng góp của Đồ án & Phương pháp Đánh giá

**Phiên bản:** 3.2
**Ngày:** 2026-10-08
**Đối tượng đọc:** Nhóm phát triển, GVHD, hội đồng (chương Thực nghiệm của báo cáo)

> Tài liệu này là nguồn sự thật cho **đóng góp của đồ án, dataset, quy trình và ngưỡng mục tiêu của các thực nghiệm**. Ngưỡng hiệu năng và bảo mật của hệ thống nằm trong [SRS](../SRS/software_requirements_specification.md) và được dẫn bằng mã NFR. Harness hiện thực ở `packages/eval`. Tài liệu tham khảo cho phương pháp: [docs/references/README.md](../references/README.md).

---

## 1. Phân loại & Đóng góp của Đồ án

### 1.1. Phân loại Hệ thống AI

| Tiêu chí            | Phân loại                                                    | Ý nghĩa Triển khai                                                             |
| ------------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------ |
| **Mục đích**        | Decision Support System (DSS)                                | Hỗ trợ — không thay thế — quyết định tuyển dụng                                |
| **Cốt lõi AI**      | LLM Structured Output + Semantic Embeddings                  | JSON Schema output; embedding cho skill matching và Rediscovery                |
| **Kiến trúc Agent** | Agentic AI — Plan / Act / Reflect với dynamic tool selection | LangGraph `StateGraph`; Checkpoint bằng `interrupt()`                          |
| **Mức độ Tự chủ**   | Human-in-the-Loop                                            | Agent chỉ tạo dữ liệu dẫn xuất; mọi thay đổi ATS/policy qua Recruiter Decision |
| **Phạm vi ngành**   | Vertical Domain-Specific AI                                  | Prompt, rubric và few-shot cho tuyển dụng tại Việt Nam, CV song ngữ Việt–Anh   |

### 1.2. Đóng góp

**Đóng góp chính (nghiên cứu) — Explainable Hybrid Scoring cho tuyển dụng:**

> Thiết kế và đánh giá engine chấm điểm CV–Job kết hợp Must-have Coverage tất định, semantic skill matching bằng embedding, và LLM rubric có neo mức điểm bắt buộc trích dẫn Evidence — kèm đánh giá thực nghiệm về độ tương quan với chuyên gia HR, độ ổn định, khả năng chống prompt injection và giảm thiên kiến nhân khẩu học.

**Đóng góp phụ (nghiên cứu ứng dụng) — Agentic Recruitment Orchestration có kiểm soát:**

> Agent Plan/Act/Reflect lựa chọn tool theo ngữ cảnh (bao gồm Rediscovery và What-if Suggestion), dừng tại Checkpoint bền vững, và được so sánh định lượng với workflow cố định về chi phí, thời gian và chất lượng Shortlist.

**Đóng góp kỹ thuật (engineering) — Multi-Tenant SaaS với PostgreSQL Forced RLS:**

> Hiện thực và kiểm chứng cô lập dữ liệu đa tenant trên shared schema, bao phủ cả đường đi API, background worker và endpoint công khai. Đây là đóng góp kỹ thuật (kỹ thuật đã phổ biến), không trình bày như một hướng nghiên cứu.

### 1.3. Đóng góp nào được chứng minh bằng thực nghiệm nào

| Đóng góp                   | Thực nghiệm                                                                           | Yêu cầu liên quan         |
| -------------------------- | ------------------------------------------------------------------------------------- | ------------------------- |
| Explainable Hybrid Scoring | Experiment 1 (chất lượng), Experiment 2 (prompt injection), Experiment 6 (thiên kiến) | FR-A1.3, FR-C2.2, FR-C2.4 |
| Agentic Orchestration      | Experiment 3 (so với baseline workflow cố định)                                       | FR-A0                     |
| Multi-Tenant Forced RLS    | Experiment 4 (cô lập tenant)                                                          | FR-C1.3, NFR-SEC-03       |
| Hệ thống dùng được thật    | Experiment 5 (hiệu năng), usability test                                              | NFR-PERF-\*, NFR-USE-01   |

---

## 2. Nguyên tắc Chung

- Mọi thực nghiệm chạy qua một **eval harness** trong repo (script + dataset có version), chạy lại được mỗi khi đổi prompt/model. Kết quả ghi kèm model, prompt version, rubric version và chi phí.
- Ngưỡng mục tiêu là kỳ vọng, không phải điều kiện "đạt". Kết quả thấp hơn vẫn được báo cáo và phân tích.
- **Không tinh chỉnh trên tập test.** Trước lượt chạy chính thức, model, prompt version và rubric version được đóng băng bằng một git tag; báo cáo ghi tag đó. Đổi bất kỳ thứ gì sau khi đóng băng thì phải chạy lại toàn bộ.

---

## 3. Dataset

- **Job:** 6 Job thuộc 3 nhóm ngành (IT, Marketing, Kế toán–Tài chính), mỗi ngành 2 cấp độ.
- **CV:** 10–15 CV mỗi Job (tổng 60–90 cặp), song ngữ Việt/Anh; nguồn: CV thật đã ẩn danh hóa có đồng ý, hoặc CV tổng hợp có kiểm duyệt. Ghi rõ tỷ lệ thật/tổng hợp.
- **Người chấm:** 2 chuyên gia HR độc lập chấm từng cặp theo thang 1–5 và xếp hạng Top 5 mỗi Job, dùng một hướng dẫn chấm viết sẵn.
- **Chia tập:** 1/3 dùng để tinh chỉnh prompt (dev), 2/3 giữ lại để báo cáo (test).

---

## 4. Experiment 1: Chất lượng Hybrid Scoring

**Ground truth:** trung bình điểm của 2 người chấm; độ đồng thuận đo bằng **weighted Cohen's Kappa (quadratic)** — báo cáo kể cả khi thấp.

**Metrics:**

- Spearman ρ giữa Total và điểm HR, tính **trong từng Job** rồi lấy trung bình.
- **NDCG@5** và **Precision@5** so với Top 5 của HR (sát với cách dùng thực tế: chọn Shortlist).
- **Grounding rate:** % Evidence tìm thấy trong văn bản gốc (mục tiêu ≥ 95%).
- **Độ ổn định:** độ lệch chuẩn Total qua 5 lần chấm lặp (mục tiêu ≤ 3 điểm).
- **Chi phí & độ trễ** mỗi Application.

**Mục tiêu tham chiếu:** Spearman ρ ≥ 0,6 và NDCG@5 cao hơn baseline có ý nghĩa.

**Ablation:**

| Cấu hình               | Mô tả                                                                 |
| ---------------------- | --------------------------------------------------------------------- |
| Baseline               | BM25 / TF-IDF giữa JD và CV                                           |
| Config A               | Chỉ embedding similarity                                              |
| Config B               | Chỉ LLM chấm tự do 0–100 (không rubric, không coverage)               |
| Config C               | LLM rubric có neo, không Must-have Coverage                           |
| **Config D (đề xuất)** | Must-have Coverage + semantic skill matching + LLM rubric + grounding |
| Config D-luna          | Như D nhưng dùng model rẻ cho mọi bước — đánh đổi chi phí/chất lượng  |

---

## 5. Experiment 2: Kháng Prompt Injection

- **Bộ tấn công:** 20 CV (10 kiểu × 2 biến thể: chỉ dẫn trực tiếp, giả mạo system prompt, văn bản ẩn trắng/cỡ 0, chỉ dẫn bằng tiếng Việt, v.v.) chèn vào pool thật.
- **Metric chính — Attack Success Rate (ASR):** tấn công thành công nếu Total tăng vượt ngưỡng của FR-A1.3 so với bản sạch **hoặc** ứng viên lọt vào Top 5 nhờ tấn công.
- **So sánh:** không phòng thủ vs. structural isolation vs. đầy đủ FR-C2.2. Mục tiêu ASR ≤ 5% với cấu hình đầy đủ.
- **Metric phụ:** detection rate và false positive rate của lớp heuristic trên 100 CV sạch.

---

## 6. Experiment 3: Giá trị của Agent

- **12 kịch bản** Campaign: Job đã/chưa parse; pool đủ / thiếu / rỗng; Talent Pool có / không có ứng viên phù hợp; tiêu chí hợp lý / quá chặt. Kịch bản và tập hành động chấp nhận được của từng kịch bản được viết **trước** khi hiện thực Agent.
- **Baseline:** workflow cố định (luôn chạy parse → score → shortlist → interview questions, không Rediscovery/What-if).
- **Metrics:**
  - Độ đúng lựa chọn tool so với tập hành động chấp nhận được của từng kịch bản.
  - **Số lần vi phạm bất biến = 0** (kiểm chứng bằng test và audit log).
  - Chi phí AI và thời gian máy so với baseline.
  - Tỷ lệ kịch bản thiếu ứng viên mà Agent đưa ra phương án hữu ích (Rediscovery hoặc What-if) so với baseline chỉ báo "không đủ".
  - Số vòng REFLECT trung bình.

---

## 7. Experiment 4: Kiểm chứng Cô lập Tenant

- **≥ 30 test case tự động**, chạy trong CI:
  - API: JWT tenant A truy cập mọi loại resource của tenant B (đọc, sửa, xóa, liệt kê, tải file).
  - SQL trực tiếp bằng `ats_app` với tenant context sai / chưa set / chuỗi rỗng.
  - Worker task nhận `tenant_id` A thao tác dữ liệu B.
  - Endpoint công khai (`/apply`) với slug của tenant A cố đọc dữ liệu khác.
  - Connection pool: request tenant A rồi request tenant B trên cùng connection.
  - Kiểm tra cấu hình: mọi bảng có `tenant_id` đều bật và **force** RLS; `ats_app` không sở hữu bảng và không có `BYPASSRLS`.
  - Rediscovery chỉ trả về Candidate cùng tenant.
- **Kỳ vọng:** 0 rò rỉ.

---

## 8. Experiment 5: Hiệu năng Hệ thống

**Công cụ:** Locust trên staging. Tách 2 chế độ: **LLM giả lập** (mock có độ trễ thực tế — đo overhead của hệ thống, rẻ, lặp lại được) và **LLM thật** (mẫu nhỏ — đo end-to-end).

| Hạng mục                | Kịch bản tải                 | Đạt khi                                  |
| ----------------------- | ---------------------------- | ---------------------------------------- |
| API CRUD                | Như đặc tả trong NFR-PERF-01 | Đạt NFR-PERF-01                          |
| Parse 1 CV              | 20 yêu cầu đồng thời         | Đạt NFR-PERF-02                          |
| Upload Batch tối đa     | 3 batch đồng thời (3 tenant) | Đạt NFR-PERF-03                          |
| Chấm điểm 1 Application | 30 yêu cầu đồng thời         | Đạt NFR-PERF-04                          |
| Rediscovery             | Như đặc tả trong NFR-PERF-07 | Đạt NFR-PERF-07                          |
| Ổn định                 | 10 người dùng × 30 phút      | 0 crash, 0 dữ liệu hỏng, 0 bản ghi trùng |
| Fairness                | 1 tenant spam 200 tác vụ AI  | Tenant khác vẫn đạt NFR-PERF-01–04       |

---

## 9. Experiment 6: Hiệu quả Giảm Thiên kiến

- **20 CV gốc × biến thể** chỉ khác thông tin nhân khẩu học: tên gợi giới tính (ví dụ tên đệm "Thị" / "Văn"), năm sinh/năm tốt nghiệp gợi tuổi.
- **Bước 1 — Có thiên kiến không?** Chấm ở chế độ **không ẩn**: đo chênh lệch điểm trung bình giữa các nhóm (paired test).
- **Bước 2 — Blind Profile có giảm không?** Chấm với Blind Profile: kỳ vọng chênh lệch ≤ 2 điểm và nhỏ hơn bước 1.
- **Bước 3 — Rò rỉ qua proxy:** giữ năm tốt nghiệp (proxy tuổi) trong Blind Profile và đo lại.
- Nếu bước 1 không phát hiện thiên kiến, báo cáo kết quả đó trung thực và giữ Blind Profile như biện pháp phòng ngừa.
