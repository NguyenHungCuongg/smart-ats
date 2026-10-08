# Hướng dẫn Đóng góp

Quy trình làm việc, điều kiện merge và quy tắc viết tài liệu cho Smart ATS. Cài đặt môi trường và các lệnh: [README.md](README.md).

## Bản đồ tài liệu

Mỗi loại câu hỏi có đúng một tài liệu sở hữu. Khi hai tài liệu mâu thuẫn, tài liệu sở hữu đúng; sửa tài liệu còn lại.

| Câu hỏi                                                       | Tài liệu                                               |
| ------------------------------------------------------------- | ------------------------------------------------------ |
| Vì sao làm, cho ai, quyết định phạm vi                        | [PRD](docs/PRD/product_requirements_document.md)       |
| Hệ thống phải làm gì: FR, NFR, tiêu chí nghiệm thu, ràng buộc | [SRS](docs/SRS/software_requirements_specification.md) |
| Kiến trúc, flow xử lý, công nghệ & phiên bản                  | [SAD](docs/SAD/system_architecture_document.md)        |
| Vì sao chọn giải pháp đó                                      | [ADR](docs/adr/)                                       |
| Bảng, cột, ràng buộc, index                                   | [ERD](docs/ERD/entity_relationship_diagram.md)         |
| Thuật ngữ                                                     | [CONTEXT.md](CONTEXT.md)                               |
| Đóng góp học thuật, dataset, thực nghiệm                      | [Kế hoạch Thực nghiệm](docs/EVAL/experiment_plan.md)   |
| Giai đoạn, mốc, phân công, rủi ro                             | [Roadmap](docs/PLAN/roadmap.md)                        |
| Việc cụ thể và trạng thái                                     | GitHub issues                                          |
| Cài đặt, chạy, lệnh                                           | [README.md](README.md)                                 |
| Tài liệu tham khảo khoa học                                   | [docs/references/README.md](docs/references/README.md) |
| Quy trình đóng góp                                            | File này                                               |

## Quy trình làm việc

1. **Issue trước.** Mọi việc bắt đầu từ một GitHub issue. Nhãn triage: [docs/agents/triage-labels.md](docs/agents/triage-labels.md).
2. **Branch.** Tạo từ `develop`, đặt tên `feature/issue-<số>-<mô-tả-ngắn>`, ví dụ `feature/issue-12-caddy-reverse-proxy`. Workflow `pr-to-in-review` lấy số issue từ tên branch để chuyển issue sang _In review_. Việc không gắn issue dùng `chore/<mô-tả-ngắn>`.
3. **Commit.** Theo [Conventional Commits](https://www.conventionalcommits.org/), viết tiếng Anh, thể mệnh lệnh: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `style:`, `test:`, kèm scope khi hữu ích (`fix(ci): …`).
4. **Pull request** vào `develop` theo [PR template](.github/pull_request_template.md), body có `Closes #<số>`. Khi PR được merge vào `develop`, workflow `close-issues-on-develop-merge` tự đóng issue.
5. **Sửa theo review:** thêm commit `chore: address review on <chủ đề>` vào cùng PR. Góp ý đến sau khi PR đã merge thì mở branch mới `feature/issue-<số>-<mô-tả>-review-followup`.
6. **`main`** chỉ nhận merge từ `develop`, tại các mốc của Roadmap.

## Điều kiện merge

Áp dụng cho mọi PR, kể cả PR do coding agent sinh ra:

- CI xanh. CI hiện chạy Prettier, ESLint, TypeScript, Ruff, mypy và smoke test hạ tầng.
- Hành vi thay đổi có test đi kèm. Bảng, endpoint hoặc task mới có test xuyên tenant.
- Đúng tiêu chí nghiệm thu của issue và các FR/NFR liên quan; không làm thêm ngoài phạm vi.
- Tài liệu sở hữu được cập nhật trong cùng PR: hành vi → SRS, schema → ERD, kiến trúc → SAD, lệnh hoặc cấu hình → README và `.env.example`.
- Thành viên còn lại đã review. Không merge code mà người merge không giải thích được.

## Checklist review bảo mật

- [ ] Mọi truy cập DB đi qua `tenant_session`; Celery task nhận `tenant_id` làm tham số đầu và dùng `@tenant_task` (ADR-0002).
- [ ] Bảng mới thuộc tenant có `tenant_id NOT NULL`, RLS `ENABLE` + `FORCE`, policy chuẩn, khóa ngoại ghép `(tenant_id, id)` (ERD §1).
- [ ] Endpoint mới kiểm tra role và Reviewer Assignment; id thuộc tenant khác trả về 404 (SAD §4.3).
- [ ] File chỉ phục vụ qua presigned URL sau khi kiểm tra quyền (NFR-SEC-09).
- [ ] Tool mới của Agent chỉ tạo dữ liệu dẫn xuất (bất biến FR-A0).
- [ ] Nội dung CV/JD đưa vào prompt nằm trong khối untrusted; lời gọi chấm điểm không có tool (FR-C2.2).
- [ ] Không log hoặc gửi ra ngoài PII và secret; không commit `.env` (NFR-SEC-10).

## Viết tài liệu

- **Ngôn ngữ:** tài liệu dự án (PRD, SRS, SAD, ERD, ADR, Roadmap, Kế hoạch Thực nghiệm, file này) viết tiếng Việt. Thuật ngữ chuyên ngành và các từ trong `CONTEXT.md` giữ tiếng Anh (Job, Candidate, Scoring Run…). Code, tên bảng, commit message và PR viết tiếng Anh.
- **Mỗi con số ở một chỗ:** ngưỡng, giới hạn và thời hạn chỉ ghi ở tài liệu sở hữu (thường là SRS); chỗ khác dẫn mã (`FR-…`, `NFR-…`, `ADR-…`).
- **Mã yêu cầu stable:** không đánh số lại FR/NFR. Số mục của SAD và ERD được code dẫn chiếu (ví dụ `SAD §3` trong `docker-compose.yml`), nên không đánh số lại.
- **Quyết định khó đảo ngược** thì ghi thành ADR mới trong `docs/adr/`. Thuật ngữ mới thì thêm vào `CONTEXT.md`.
- **Trích dẫn:** dẫn bài báo theo quy tắc trong [docs/references/README.md](docs/references/README.md), trích nguyên văn câu làm căn cứ.
