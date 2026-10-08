# Chấm điểm kết hợp coverage tất định với LLM rubric có neo

Axis Score không phải một con số 0–100 tự do do LLM đưa ra, vì con số tự do trôi giữa các lần chạy và không bảo vệ được. Must-have Coverage được tính tất định: kỹ năng được chuẩn hóa, rồi khớp chính xác hoặc khớp alias, và nếu không được thì khớp bằng độ tương đồng embedding trên một ngưỡng. LLM chấm mỗi trục theo rubric 1–5 có mô tả neo cho từng mức và bắt buộc trích Evidence. Điểm được quy đổi tuyến tính sang 0–100. Evidence không tìm thấy trong văn bản gốc bị loại, và nhận định mà nó hỗ trợ bị gắn cờ.

## Hệ quả

- Mỗi Score Result lưu `model`, `prompt_version`, `rubric_version` và snapshot trọng số của Scoring Run, nên mọi điểm số đều tái lập hoặc giải thích được về sau.
- Lời gọi chạy với `temperature=0` và seed cố định khi model hỗ trợ. Độ ổn định của điểm số là một metric được đo và báo cáo (Experiment 1), không phải một giả định.
