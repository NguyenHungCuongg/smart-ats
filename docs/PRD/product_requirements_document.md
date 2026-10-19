# Tài liệu Yêu cầu Sản phẩm (PRD)

## Smart ATS — Nền tảng ATS Đa Người Thuê Hỗ trợ AI

**Phiên bản:** 3.3
**Ngày:** 2026-10-19
**Đối tượng đọc:** Nhóm phát triển, GVHD

> PRD là nguồn sự thật cho **bối cảnh, định vị, nguyên tắc thiết kế, người dùng, hành trình chính và các quyết định phạm vi**. Yêu cầu chi tiết, tiêu chí nghiệm thu và mọi con số nằm trong [SRS](../SRS/software_requirements_specification.md) và được dẫn bằng mã (FR-…, NFR-…), không chép lại. Thuật ngữ theo `CONTEXT.md`. Bản đồ tài liệu: [CONTRIBUTING.md](../../CONTRIBUTING.md#bản-đồ-tài-liệu).

---

## 1. Tổng quan & Tầm nhìn

Smart ATS là Applicant Tracking System dạng SaaS đa người thuê cho SME Việt Nam. Hệ thống biến các CV phi cấu trúc thành Shortlist đã xếp hạng và có giải trình, và cho phép một agent điều phối Campaign tuyển dụng tới một Checkpoint do con người quyết định.

### 1.1. Bối cảnh & Vấn đề

Phần lớn doanh nghiệp vừa và nhỏ (SME) Việt Nam vẫn quản lý tuyển dụng bằng Excel, email và các phần mềm không tích hợp AI.

> Các nhận định định lượng trong mục này chưa có nguồn trích dẫn; việc đối chiếu nguồn hoặc thay bằng khảo sát SME do nhóm tự thực hiện nằm trong [Roadmap](../PLAN/roadmap.md).

| Vấn đề                                  | Biểu hiện                                                                                                                                 | Smart ATS giải quyết bằng                                                                      |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| **Quá tải sàng lọc**                    | Mỗi vị trí nhận hàng trăm CV phi cấu trúc; đọc – bóc tách – so sánh thủ công tốn hàng chục giờ; recruiter lướt vài giây mỗi CV nên bỏ sót | Parse và chấm điểm CV tự động, kể cả CV đến qua Public Apply Link                              |
| **Đánh giá thiếu nhất quán & chủ quan** | Điểm phụ thuộc cảm nhận từng recruiter; không có tiêu chí chuẩn hóa nên khó giải thích với Hiring Manager                                 | Chấm điểm lai (Must-have Coverage tất định + LLM rubric có neo), mọi nhận định kèm Evidence    |
| **Gánh nặng hành chính**                | Soạn thư mời, cập nhật trạng thái hồ sơ, tổng hợp báo cáo chiếm phần lớn thời gian vận hành                                               | Soạn và gửi email, sinh câu hỏi phỏng vấn, bulk action trên pipeline                           |
| **Mất ứng viên tiềm năng**              | CV cũ nằm im trong hộp thư, không được xem lại cho vị trí mới                                                                             | Talent Rediscovery tìm lại Candidate cũ phù hợp Job mới                                        |
| **Rào cản chi phí**                     | ATS quốc tế (Workday, Greenhouse, Lever) có chi phí hàng chục nghìn USD/năm, vượt ngân sách SME                                           | Nền tảng multi-tenant dùng chung hạ tầng, chi phí AI kiểm soát bằng AI Budget theo từng tenant |

### 1.2. Định vị Sản phẩm

**Smart ATS** là nền tảng ATS SaaS đa người thuê (Multi-Tenant) cho SME, tích hợp lớp AI để bóc tách CV, chấm điểm có giải trình, và một Agent điều phối có kiểm soát của con người.

```
┌─────────────────────────────────────────────────────────────┐
│                    SMART ATS PLATFORM                       │
│           (Multi-Tenant SaaS — AI-Powered ATS)              │
├─────────────────────────────────────────────────────────────┤
│  TENANT A (Cty ABC)  │  TENANT B (Cty XYZ)  │  TENANT N     │
│  Jobs · Candidates · Applications · Talent Pool · AI Budget │
├─────────────────────────────────────────────────────────────┤
│               SHARED PLATFORM SERVICES                      │
│  • Hybrid Scoring Engine (deterministic + LLM rubric)       │
│  • Agentic Campaign Engine (LangGraph + Checkpoint)         │
│  • Async Workers (Celery + Redis)                           │
│  • PostgreSQL — Forced RLS + pgvector                       │
└─────────────────────────────────────────────────────────────┘
```

### 1.3. Nguyên tắc Thiết kế

1. **AI-Augmented, Human-Decided**: AI xử lý khối lượng lớn và đề xuất; con người quyết định. Không có quyết định loại ứng viên hay thay đổi tiêu chí nào được thực hiện tự động.
2. **No-Prompt UI**: Người dùng không cần kiến thức prompt engineering; mọi khả năng LLM được trừu tượng hóa qua form, wizard và action button.
3. **Explainability-First**: Mọi điểm số kèm Fit-Gap Report có Evidence trích nguyên văn; mọi điểm số có thể tái lập (lưu model, prompt version, rubric version, trọng số).
4. **Fault Isolation**: Lỗi của một file hay một ứng viên không ảnh hưởng phần còn lại của batch.
5. **Isolation by Default**: Dữ liệu tenant được cô lập ở tầng database engine; code quên lọc `tenant_id` vẫn không lộ dữ liệu.

### 1.4. Chỉ số Thành công

Ngưỡng cụ thể nằm ở tài liệu được dẫn:

- Điểm số đồng thuận với chuyên gia HR: Spearman ρ và NDCG@5 trên bộ dữ liệu có nhãn (Experiment 1, [Kế hoạch Thực nghiệm](../EVAL/experiment_plan.md)).
- Tỷ lệ tấn công prompt injection thành công không vượt mục tiêu (Experiment 2).
- Không rò rỉ dữ liệu xuyên tenant trong bộ test cô lập tự động (Experiment 4).
- Recruiter mới đạt Fit-Gap Report đầu tiên trong thời gian NFR-USE-01.

---

## 2. Người dùng & Vai trò

Chi tiết quyền: SRS §2.

| Vai trò           | Tóm tắt                                                                                                                                                         |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **System Admin**  | Vận hành nền tảng: Tenant, gói dịch vụ, AI Budget, số liệu sử dụng tổng hợp. **Không truy cập dữ liệu tuyển dụng của bất kỳ Tenant nào.**                       |
| **Company Admin** | Quản lý Workspace và Member, xem AI usage, xử lý yêu cầu dữ liệu của ứng viên. **Có mọi quyền của Recruiter.**                                                  |
| **Recruiter**     | Vận hành tuyển dụng từ đầu tới cuối: Job, CV, chấm điểm, Rediscovery, Campaign và Recruiter Decision, email, pipeline.                                          |
| **Reviewer**      | Chỉ thấy Job được gán. Đọc Fit-Gap Report, comment, cho Interview Score. Không đổi Stage, không chạy AI, không gửi email, không xem thông tin liên hệ ứng viên. |

Chỉ Company Admin và Recruiter được khởi tạo Campaign.

---

## 3. Tính năng (theo module SRS)

| Module       | Tính năng                                                                                                      | SRS          | Ưu tiên |
| ------------ | -------------------------------------------------------------------------------------------------------------- | ------------ | ------- |
| A0 Agent     | Campaign: plan / act / reflect, tool Rediscovery và What-if, Checkpoint bền vững với Approve / Revise / Reject | FR-A0        | P1      |
| A1 Đánh giá  | Parse Job, Recruiter xác nhận criteria                                                                         | FR-A1.1      | P1      |
|              | Upload & parse CV theo batch, cô lập lỗi từng file, chống trùng lặp                                            | FR-A1.2      | P1      |
|              | Chấm điểm lai 3 trục kèm Fit-Gap Report và Evidence                                                            | FR-A1.3      | P1      |
|              | Xếp hạng, Shortlist, câu hỏi phỏng vấn STAR                                                                    | FR-A1.4      | P1      |
|              | Báo cáo PDF                                                                                                    | FR-A1.5      | P2      |
|              | Talent Rediscovery                                                                                             | FR-A1.6      | P1      |
| A2 Cộng tác  | Trợ lý email: soạn theo 3 tone, **gửi** qua nhà cung cấp                                                       | FR-A2.1      | P1      |
|              | Comment, @mention, Interview Score                                                                             | FR-A2.2      | P1      |
| A3 Pipeline  | Vòng đời Job                                                                                                   | FR-A3.1      | P1      |
|              | Kanban trên Application (5 Stage hoạt động + 2 Stage kết thúc), bulk action                                    | FR-A3.2      | P1      |
|              | Activity timeline & audit log                                                                                  | FR-A3.3      | P1      |
|              | Public Apply Link                                                                                              | FR-A3.4      | P1      |
| C1 Nền tảng  | Xác thực bằng mật khẩu, phiên đăng nhập                                                                        | FR-C1.1      | P1      |
|              | Đăng nhập Google                                                                                               | FR-C1.1      | P2      |
|              | Quản lý Workspace & Member, lời mời                                                                            | FR-C1.2      | P1      |
|              | Cô lập tenant bằng Forced RLS                                                                                  | FR-C1.3      | P1      |
|              | AI Usage Ledger & AI Budget                                                                                    | FR-C1.4      | P1      |
|              | Bảo vệ dữ liệu cá nhân ứng viên (đồng ý, lưu giữ, xóa)                                                         | FR-C1.5      | P1      |
| C2 AI Engine | Document extraction, chống prompt injection, xử lý bất đồng bộ, Blind Profile                                  | FR-C2.1–C2.4 | P1      |

---

## 4. Hành trình Người dùng Chính

1. **Sàng lọc thủ công:**
   1. Recruiter tạo Job từ JD Document, xác nhận criteria và trọng số.
   2. Recruiter upload CV hoặc chia sẻ Public Apply Link.
   3. Recruiter chạy chấm điểm và đọc danh sách xếp hạng kèm Fit-Gap Report.
   4. Recruiter chọn Shortlist, sinh câu hỏi phỏng vấn và gửi thư mời.
2. **Campaign:**
   1. Recruiter viết Campaign Brief kèm số lượng mục tiêu.
   2. Agent chấm điểm pool, bổ sung qua Rediscovery nếu thiếu, rồi chuẩn bị Shortlist hoặc What-if Suggestion.
   3. Recruiter approve, revise hoặc reject tại Checkpoint. Không có gì trong pipeline thay đổi trước bước này.
3. **Cộng tác:** Reviewer được gán vào một Job đọc Fit-Gap Report, comment có @mention, và ghi Interview Score sau buổi phỏng vấn.
4. **Yêu cầu dữ liệu:** Ứng viên yêu cầu xóa dữ liệu, Company Admin xóa Candidate. File, trường định danh và embedding bị xóa.

---

## 5. Quyết định Phạm vi

Ghi lại các quyết định phạm vi quan trọng để giải trình khi bảo vệ. Danh sách đầy đủ những gì nằm ngoài đề tài: SRS §6.

### 5.1. Loại bỏ Side B (Career Platform) — từ v3.0

- Side B (Reverse Matching, Career Advisor, CV Builder) là một sản phẩm B2C độc lập, khác domain, bảo mật và UX với B2B ATS.
- **Quyết định**: tập trung vào ATS B2B. Ứng viên chỉ tương tác qua **Public Apply Link** (một form nộp CV), không có tài khoản ứng viên.

### 5.2. Loại bỏ Offer/Contract Generator — từ v3.0

- Là CRUD template-fill thuần, không có giá trị AI; đặt vào roadmap thương mại.

### 5.3. Refine Smart Recruitment Agent — từ v3.0, bổ sung v3.1

- Agent **không bao giờ** tự thay đổi tiêu chí (score threshold, must-have, trọng số) hay trạng thái ATS.
- v3.1 bổ sung: Agent có **không gian quyết định thật** (khi thiếu ứng viên có thể chọn Rediscovery từ Talent Pool hoặc tính What-if Suggestion) và được so sánh với baseline workflow cố định trong Experiment 3 để chứng minh giá trị.

### 5.4. Bổ sung trong v3.1

| Bổ sung                                      | Lý do                                                                                                                                                                               |
| -------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Public Apply Link**                        | Không có kênh nộp hồ sơ thì stage "Applied" không có ý nghĩa; mọi ATS thực tế đều có. Chi phí thấp (một form).                                                                      |
| **Gửi email thật** qua dịch vụ transactional | Lời mời thành viên (FR-C1.2) và email từ chối hàng loạt (FR-A3.2) vốn đã cần gửi email; v3.0 "không SMTP" tự mâu thuẫn. Dùng dịch vụ có sẵn nên không phát sinh DevOps mail server. |
| **Talent Rediscovery**                       | Tận dụng embedding đã có; biến Talent Pool thành tài sản của tenant; là tool quan trọng cho Agent.                                                                                  |
| **AI Usage Ledger & AI Budget**              | Cần để enforce hạn mức theo chi phí thật, đo cost trong thực nghiệm, và là câu chuyện SaaS thực tế.                                                                                 |
| **Bảo vệ dữ liệu cá nhân**                   | CV chứa dữ liệu cá nhân và được gửi tới nhà cung cấp LLM nước ngoài; sản phẩm "doanh nghiệp dùng thật" bắt buộc có consent, retention và xóa dữ liệu.                               |

---

## 6. Phi Chức năng & Công nghệ

- Mục tiêu hiệu năng, bảo mật, độ tin cậy và khả dụng: SRS §4 (NFR-PERF, NFR-SEC, NFR-REL, NFR-USE).
- Ràng buộc thiết kế: SRS §5. Công nghệ và phiên bản: [SAD §2](../SAD/system_architecture_document.md#2-công-nghệ).
