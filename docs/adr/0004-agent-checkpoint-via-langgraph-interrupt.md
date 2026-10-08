# Checkpoint của Agent dùng LangGraph interrupt với Postgres checkpointer

Một Campaign tới Checkpoint bằng cách gọi `interrupt()` của LangGraph. State được `langgraph-checkpoint-postgres` lưu dưới `thread_id = campaign_id`, rồi Celery task kết thúc. Recruiter Decision enqueue một task mới để resume graph bằng `Command(resume=decision)`. Con người có thể mất hàng giờ để quyết định, và giữ một worker slot trong ngần ấy thời gian sẽ làm nghẽn queue.

## Hệ quả

- Ngân sách thời gian của Campaign (NFR-PERF-05) chỉ tính thời gian máy, không tính thời gian chờ tại Checkpoint.
- Trước Checkpoint, agent được tạo dữ liệu dẫn xuất (Scoring Run, Score Result, What-if Suggestion). Agent không được đổi Stage, tạo Application, hay thay đổi criteria hoặc trọng số của Job. Những thay đổi đó chỉ xảy ra khi Recruiter Decision được áp dụng, trong task resume, dưới tên Recruiter đó.
