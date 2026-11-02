# Nhật ký Thực nghiệm

**Đối tượng đọc:** Nhóm phát triển, GVHD, hội đồng (chương Thực nghiệm của báo cáo)

> Tài liệu này là nguồn sự thật cho **kết quả của từng lần chạy eval harness và thay đổi rút ra từ kết quả đó**. Thiết kế thực nghiệm, metric và ngưỡng mục tiêu nằm trong [Kế hoạch Thực nghiệm](experiment_plan.md); định nghĩa từng cột của bảng nằm trong [README của eval](../../packages/eval/README.md#metrics).

## Quy tắc ghi

- Mỗi lần chạy `python -m smart_ats_eval` có gọi API của provider là một mục. Lần chạy chỉ có Baseline (không có key) thì không ghi. Một lần chạy nối qua nhiều ngày bằng `--cache` là một mục, ghi khi bảng in ra, kèm ngày bắt đầu và ngày xong.
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

### 2026-11-02: hr-v1, split dev

- **Commit:** `d632835`, nhánh `chore/gemini-consented-real-cvs`
- **Lệnh:** `uv run --env-file .env python -m smart_ats_eval packages/eval/datasets/hr-v1.json --split dev --runs 1`
- **Provider:** `LLM_PROVIDER=gemini`; `LLM_REASONING_MODEL=gemini-3.6-flash`, `LLM_EXTRACTION_MODEL=gemini-3.5-flash-lite`, `EMBEDDING_MODEL=gemini-embedding-2`
- **Lý do chạy:** bảng ablation sáu dòng đầu tiên trên tập dev (#110)

Lệnh dừng giữa Config B, không in bảng. Dòng cuối của output:

```text
openai.RateLimitError: Error code: 429 - [...] Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20, model: gemini-3.6-flash, description: Generate content requests per day limit exceeded on Free Tier. [...] 'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier' [...] 'quotaValue': '20'
```

- **Nhận xét:** free tier của `gemini-3.6-flash` cho 20 request mỗi ngày. Một lần chạy trên hr-v1 cần khoảng 72 request của model chấm (Config B, C, D, mỗi Config 24 CV).
- **Thay đổi rút ra:** chưa có; chờ chọn model chấm hoặc cách chạy khác.
