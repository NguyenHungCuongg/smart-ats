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

### 2026-11-03 – 2026-11-11: hr-v1, split dev

- **Ngày bắt đầu / Ngày xong:** `2026-11-03` / `2026-11-11` (chạy nối nhiều ngày bằng `--cache` qua giới hạn 20 request/ngày của free tier `gemini-3.6-flash`).
- **Commit:** `a04bc50`, nhánh `develop` (worktree sạch).
- **Lệnh:** `uv run --env-file .env python -m smart_ats_eval packages/eval/datasets/hr-v1.json --split dev --runs 1 --cache packages/eval/.cache/hr-v1`
- **Provider:** `LLM_PROVIDER=gemini` (free tier); `LLM_REASONING_MODEL=gemini-3.6-flash`, `LLM_EXTRACTION_MODEL=gemini-3.5-flash-lite`, `EMBEDDING_MODEL=gemini-embedding-2`
- **Lý do chạy:** chạy bảng ablation sáu dòng sơ bộ của Experiment 1 trên split `dev` của `hr-v1` (#119), nối từ lượt chạy ngày `2026-11-02` (#110).
- **Ghi chú phạm vi:** model chấm là `gemini-3.6-flash` free tier (khác `gpt-6-sol` mà SRS dự kiến; Config D-luna dùng `gemini-3.5-flash-lite`), `--runs 1` nên chưa đo Stability (`-`), và `hr-v1` có `for_report: false` (`NOT FOR REPORT`) nên bảng chỉ là bản sơ bộ để kiểm tra và tinh chỉnh trên `dev`, không phải số liệu báo cáo.

```text
Dataset hr v1, split dev, 1 run(s): 2 Jobs, 24 CV Documents (3 real, 21 synthetic)
Weighted Kappa (quadratic) r1 vs r2: 0.990
NOT FOR REPORT: this dataset has for_report = false.

| Config | Model | Prompt | Rubric | Spearman rho | Rho excluded | NDCG@5 | P@5 | Grounding | Stability | Cost/App (USD) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline (BM25) | - | - | - | -0.090 | 0 | 0.639 | 0.450 | - | - | - |
| Config A | gemini-embedding-2 | - | - | 0.685 | 0 | 0.826 | 0.750 | - | - | 0.0000 |
| Config B | gemini-3.6-flash | b-v1 | - | 0.945 | 0 | 0.939 | 0.900 | - | - | 0.0000 |
| Config C | gemini-3.6-flash | v2 | v1 | 0.786 | 0 | 0.918 | 0.850 | 0.834 | - | 0.0000 |
| Config D | gemini-3.6-flash | v2 | v1 | 0.773 | 0 | 0.954 | 0.950 | 0.858 | - | 0.0000 |
| Config D-luna | gemini-3.5-flash-lite | v2 | v1 | 0.637 | 0 | 0.850 | 0.800 | 0.841 | - | 0.0000 |
```

- **Nhận xét:**
  - **Baseline (BM25) → Config A (`gemini-embedding-2`):** Spearman rho tăng từ `-0.090` lên `0.685` (+0.775), NDCG@5 tăng từ `0.639` lên `0.826` (+0.187), P@5 tăng từ `0.450` lên `0.750` (+0.300). Lọc từ khóa BM25 hầu như không phân biệt được thứ tự CV Document trên split này, trong khi embedding ngữ nghĩa cải thiện rõ rệt cả tương quan lẫn chất lượng Top 5.
  - **Config A → Config B (`gemini-3.6-flash`, prompt `b-v1`, chấm tự do 0–100):** Spearman rho tăng từ `0.685` lên `0.945` (+0.260), NDCG@5 tăng từ `0.826` lên `0.939` (+0.113), P@5 tăng từ `0.750` lên `0.900` (+0.150). LLM chấm tự do trên tiêu chí và Blind Profile đạt độ tương quan thứ hạng cao nhất toàn bảng, nhưng không có rubric hay Evidence giải trình (Grounding `-`).
  - **Config B → Config C (`gemini-3.6-flash`, prompt `v2`, rubric `v1`, không Must-have Coverage):** Spearman rho giảm từ `0.945` xuống `0.786` (-0.159), NDCG@5 giảm từ `0.939` xuống `0.918` (-0.021), P@5 giảm từ `0.900` xuống `0.850` (-0.050); Grounding đạt `0.834`. Chuyển từ chấm tự do 0–100 sang 3 trục rubric rời rạc 1–5 làm giảm độ tương quan thứ hạng toàn dải, và tỷ lệ Evidence hợp lệ chưa đạt ngưỡng mục tiêu Grounding rate trong [Kế hoạch Thực nghiệm](experiment_plan.md).
  - **Config C → Config D (`gemini-3.6-flash`, prompt `v2`, rubric `v1`, đủ Must-have Coverage):** NDCG@5 tăng từ `0.918` lên `0.954` (+0.036), P@5 tăng từ `0.850` lên `0.950` (+0.100) và Grounding tăng từ `0.834` lên `0.858` (+0.024); cả NDCG@5 (`0.954`) và P@5 (`0.950`) của Config D đều cao nhất toàn bảng (vượt cả Config B `0.939` và `0.900`). Ngược lại Spearman rho giảm nhẹ từ `0.786` xuống `0.773` (-0.013), cho thấy Must-have Coverage giúp chọn nhóm đầu (Top 5) chuẩn hơn nhưng tương quan thứ hạng toàn dải chưa bằng Config B.
  - **Config D (`gemini-3.6-flash`) → Config D-luna (`gemini-3.5-flash-lite`):** Spearman rho giảm từ `0.773` xuống `0.637` (-0.136), NDCG@5 giảm từ `0.954` xuống `0.850` (-0.104), P@5 giảm từ `0.950` xuống `0.800` (-0.150), Grounding giảm từ `0.858` xuống `0.841` (-0.017). Cả hai cùng có `Cost/App (USD)` là `0.0000` do dùng free tier Gemini (giá 0 trong `pricing.py`), nên lượt chạy này chưa đo được đánh đổi chi phí giữa hai cấp model.
- **Thay đổi rút ra:** không đổi code Scoring trong phạm vi #119; ghi nhận hai vấn đề cần kiểm tra ở bước tinh chỉnh tiếp theo trên `dev` trước khi đóng băng cho tập `test`: (1) nguyên nhân Grounding ở mức `0.834`–`0.858` (chưa đạt ngưỡng mục tiêu của [Kế hoạch Thực nghiệm](experiment_plan.md)), và (2) nguyên nhân Spearman rho của Config C/D (`0.786` / `0.773`) thấp hơn Config B (`0.945`) dù Config D dẫn đầu về NDCG@5 (`0.954`) và P@5 (`0.950`). Ngoài ra cần chạy với `gpt-6-sol` / `gpt-6-luna` và đủ số lần lặp theo [Kế hoạch Thực nghiệm](experiment_plan.md) khi có điều kiện để đo Stability và Cost/App thực tế.
