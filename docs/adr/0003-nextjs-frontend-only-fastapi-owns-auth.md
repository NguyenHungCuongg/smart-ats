# Next.js chỉ là frontend; FastAPI sở hữu auth và toàn bộ nghiệp vụ

Ứng dụng Next.js render UI và gọi REST API của FastAPI từ trình duyệt qua TanStack Query. Ứng dụng không dùng Server Action hay route handler làm backend-for-frontend. Một backend duy nhất giữ RBAC, RLS context và audit ở một chỗ, và hai sinh viên không đủ sức duy trì thêm một tầng server thứ hai.

## Hệ quả

- Access token nằm trong bộ nhớ. Refresh token (rotate, phát hiện dùng lại theo token family) là cookie `HttpOnly; Secure; SameSite=Strict` giới hạn ở `/auth/refresh` trên site của API. Endpoint refresh còn yêu cầu một custom header để chống CSRF. Thời hạn token: FR-C1.1.
- Tiến độ được đẩy bằng Server-Sent Events. `EventSource` không gửi được header `Authorization`, nên client lấy trước một SSE ticket dùng một lần, hạn 60 giây, rồi truyền qua query parameter.
