# Shared schema với forced Row-Level Security để cô lập tenant

Mọi Tenant dùng chung một schema PostgreSQL. Mỗi bảng thuộc tenant có `tenant_id` khác null và bật RLS **enabled và forced**, với một policy `USING` / `WITH CHECK` `tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid`. Chúng tôi chọn cách này thay vì schema-per-tenant hay database-per-tenant vì chỉ cần một đường migration duy nhất mà vẫn đẩy việc cô lập xuống database engine; đây cũng là một đóng góp của khóa luận có thể kiểm chứng bằng test.

## Hệ quả

- Ứng dụng kết nối bằng `ats_app`, một role không sở hữu bảng và không có `BYPASSRLS`. Migration chạy bằng `ats_owner`. Chủ sở hữu bảng bỏ qua RLS trừ khi RLS bị force, nên test chạy bằng role chủ sở hữu mà pass thì không chứng minh được gì.
- Tenant context được đặt cho từng transaction bằng `SELECT set_config('app.current_tenant_id', :tid, true)`. `SET LOCAL` không nhận bind parameter, còn `SET` ở mức session sẽ rò sang các connection dùng lại trong pool.
- Bắt buộc có `NULLIF(..., '')`: khi một connection trong pool đã từng dùng setting này, giá trị đọc lại là `''` chứ không phải `NULL`, và `''::uuid` sẽ báo lỗi thay vì trả về 0 dòng.
- Bảng con (ví dụ `score_results`) lặp lại `tenant_id` thay vì dựa vào phép join trong policy. Nhờ vậy policy đơn giản và dùng được index.
- Các tra cứu diễn ra trước khi biết Tenant (đăng nhập bằng email, Public Apply Link theo slug, chấp nhận lời mời) đi qua các hàm `SECURITY DEFINER` hẹp thuộc sở hữu của `ats_owner`, không bao giờ qua một role bỏ qua RLS.
- Bảng checkpoint của LangGraph nằm ngoài RLS. Chỉ agent runner đọc chúng, theo id của một Campaign mà runner đã nạp dưới RLS.
