# Celery worker dùng DB session đồng bộ và nhận Tenant một cách tường minh

API dùng async engine của SQLAlchemy. Celery worker dùng sync engine, và cả hai chạy trên cùng driver `psycopg` 3. Chúng tôi giữ Celery vì độ trưởng thành và có Flower để giám sát; loại Taskiq (hệ sinh thái nhỏ hơn) và `asyncio.run()` bên trong task (lỗi event loop và pool).

Worker không bao giờ đi qua middleware của API, nên mọi task nhận `tenant_id` làm tham số đầu tiên và mở session qua một helper duy nhất `tenant_session(tenant_id)` để đặt RLS context. Một bước kiểm tra trong CI làm fail mọi task không dùng helper này; task không thuộc tenant phải được khai báo tường minh trong `NON_TENANT_TASKS` (`app/worker.py`).

## Hệ quả

- Task được chia theo từng item (một CV, một Score Result), acknowledge muộn (acks late), và idempotent nhờ khóa duy nhất như `(scoring_run_id, application_id)`. Task bị giao lại sẽ upsert thay vì tạo bản trùng.
- Không dùng chord của Canvas. Tiến độ batch được tính bằng cách đếm các dòng item, không dựa vào chord trong Redis.
