# Embedding lưu trong PostgreSQL bằng pgvector, không dùng vector database riêng

Embedding của CV Document và Job được lưu trong cột `vector(1536)` với index HNSW. Nhờ vậy Rediscovery chạy dưới cùng các policy RLS như mọi truy vấn khác, và không có kho thứ hai nào phải giữ nhất quán hay cô lập theo Tenant. Chúng tôi loại Pinecone vì nó lặp lại việc cô lập tenant bên ngoài database và thêm một phụ thuộc trả phí bên ngoài.

## Hệ quả

- `text-embedding-3-large` được gọi với `dimensions=1536`. Index HNSW của pgvector hỗ trợ tối đa 2.000 chiều cho kiểu `vector`, trong khi số chiều gốc của model là 3.072.
- Đổi model embedding nghĩa là phải embed lại toàn bộ Talent Pool. Tên model và số chiều được lưu cùng mỗi vector.
