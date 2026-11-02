# Nhật ký Thực nghiệm

**Đối tượng đọc:** Nhóm phát triển, GVHD, hội đồng (chương Thực nghiệm của báo cáo)

> Tài liệu này là nguồn sự thật cho **kết quả của từng lần chạy eval harness và thay đổi rút ra từ kết quả đó**. Thiết kế thực nghiệm, metric và ngưỡng mục tiêu nằm trong [Kế hoạch Thực nghiệm](experiment_plan.md); định nghĩa từng cột của bảng nằm trong [README của eval](../../packages/eval/README.md#metrics).

## Quy tắc ghi

- Mỗi lần chạy `python -m smart_ats_eval` có gọi API của provider là một mục. Lần chạy chỉ có Baseline (không có key) thì không ghi.
- Mục mới thêm vào cuối file. Mục cũ giữ nguyên; sai sót được đính chính bằng một mục mới dẫn ngày của mục cũ.
- Output của lệnh được dán nguyên văn. Mọi con số trong mục, kể cả trong Nhận xét, lấy từ output đó.
- Chạy trên worktree sạch, để commit ghi trong mục đúng là code đã chạy. Worktree có thay đổi chưa commit thì ghi rõ thay đổi đó.
- Lượt chạy chính thức trên tập test ghi thêm git tag đóng băng (Kế hoạch Thực nghiệm §2).

## Mẫu một mục

````markdown
### YYYY-MM-DD: <dataset>-v<n>, split <split>

- **Commit:** `<git rev-parse --short HEAD>`, tag nếu có
- **Lệnh:** `uv run --env-file .env python -m smart_ats_eval <dataset> --split <split> --runs <n>`
- **Provider:** `LLM_PROVIDER`, `LLM_REASONING_MODEL`, `LLM_EXTRACTION_MODEL`, `EMBEDDING_MODEL`
- **Lý do chạy:** thay đổi cần đo, hoặc câu hỏi cần trả lời

```text
<output nguyên văn của lệnh>
```

- **Nhận xét:** cặp Config nào chênh nhau, chênh bao nhiêu, trên metric nào
- **Thay đổi rút ra:** ví dụ "viết lại neo Experience, `RUBRIC_VERSION` v1 → v2", hoặc "không đổi"
````

## Các lần chạy

_Chưa có lần chạy nào._
