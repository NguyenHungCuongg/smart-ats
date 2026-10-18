# Hướng dẫn chấm CV cho người chấm HR

**Phiên bản:** 0.1 (bản nháp, chờ đọc thử)
**Đối tượng đọc:** 2 người chấm HR (Phần 1–7), nhóm phát triển (Phần 8)

> Tài liệu này là hướng dẫn chấm viết sẵn mà [Kế hoạch Thực nghiệm](experiment_plan.md) §3–§4 yêu cầu. Nhãn bạn cho là chuẩn so sánh (ground truth) để đo hệ thống chấm CV tự động có giống đánh giá của chuyên gia hay không. Không có đáp án đúng hay sai, chỉ có đánh giá chuyên môn của bạn.

---

## 1. Bạn cần làm gì

Bạn được nhận một số **Job** (mỗi Job là một tin tuyển dụng) và với mỗi Job là khoảng 10–15 **CV**. Với mỗi Job:

1. Đọc tin tuyển dụng.
2. Chấm **từng CV** theo thang 1–5 (Phần 2).
3. Sau khi chấm hết CV của Job đó, chọn **5 CV tốt nhất** và xếp thứ tự (Phần 3).

Kết quả điền vào bảng tính (Phần 6). Bạn không cần viết nhận xét dài.

**Câu hỏi để tự hỏi khi chấm:** "Nếu tôi là HR của vị trí này, tôi có mời ứng viên này phỏng vấn không, và có mong họ làm tốt vị trí này không?"

---

## 2. Thang điểm 1–5

Chấm bằng **số nguyên** từ 1 đến 5, theo mô tả dưới đây. Mô tả luôn so với **yêu cầu của chính tin tuyển dụng đó**, kể cả cấp độ: CV của một sinh viên có thể được 5 điểm cho vị trí thực tập, nhưng chỉ 2 điểm cho vị trí senior.

| Điểm  | Ý nghĩa          | Dấu hiệu                                                                                                                                                   |
| ----- | ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **5** | Rất phù hợp      | Đáp ứng mọi yêu cầu bắt buộc, mỗi yêu cầu có bằng chứng cụ thể (dự án, công việc, kết quả). Mức kinh nghiệm đúng hoặc cao hơn yêu cầu. Mời phỏng vấn ngay. |
| **4** | Phù hợp          | Đáp ứng gần hết yêu cầu bắt buộc. Thiếu một yêu cầu nhỏ, hoặc có yêu cầu nhưng bằng chứng còn mỏng. Đáng phỏng vấn.                                        |
| **3** | Phù hợp một phần | Đáp ứng một số yêu cầu bắt buộc và thiếu một số khác, nhưng có nền tảng gần và có thể học nhanh. Cân nhắc nếu không có người tốt hơn.                      |
| **2** | Ít phù hợp       | Chỉ khớp phần nhỏ, thiếu phần lớn yêu cầu bắt buộc. Thường không mời phỏng vấn.                                                                            |
| **1** | Không phù hợp    | Sai lĩnh vực, hoặc chỉ liệt kê kỹ năng mà không có bằng chứng đã từng dùng.                                                                                |

### Nguyên tắc chấm

- **Chấm theo bằng chứng, không chấm theo từ khóa.** Một CV liệt kê đủ kỹ năng trong danh sách nhưng kinh nghiệm làm việc không liên quan thì điểm thấp. Ngược lại, CV dùng từ khác với tin tuyển dụng nhưng cùng nghĩa (ví dụ "Postgres" thay cho "PostgreSQL", hay "huấn luyện mô hình" thay cho "training") vẫn được tính là có kỹ năng.
- **Bỏ qua thông tin nhân khẩu học.** Tên, giới tính, tuổi, ảnh, quê quán, nơi ở, tình trạng hôn nhân và trường học (nếu không được tin tuyển dụng nêu) không được ảnh hưởng đến điểm.
- **Chỉ dùng thông tin trong CV và tin tuyển dụng.** Không tìm kiếm ứng viên trên mạng, không đoán thêm.
- **Yêu cầu bắt buộc quan trọng hơn yêu cầu ưu tiên.** Thiếu một mục "ưu tiên/nice to have" ít bị trừ điểm hơn thiếu một mục bắt buộc.
- **Không cần cố phân bố điểm cho đều.** Một Job có thể có nhiều CV 4–5 hoặc nhiều CV 1–2. Chấm đúng theo mô tả.
- **Đừng chấm vì định dạng.** Trình bày đẹp hay xấu, lỗi chính tả nhỏ không phải lý do tăng hay giảm điểm, trừ khi vị trí đòi hỏi (ví dụ content, biên tập).

### Phân biệt ranh giới giữa mức 3 và mức 4 (Trường hợp dễ phân vân nhất)

Ranh giới giữa điểm 3 và điểm 4 là nơi dễ xảy ra bất đồng ý kiến nhất giữa hai người chấm, ảnh hưởng trực tiếp đến độ đồng thuận (Inter-rater reliability / Weighted Kappa). Để nhất quán, hãy phân biệt giữa **yêu cầu chuyên môn cốt lõi** và **công cụ phụ trợ**:

- **Yêu cầu cốt lõi (Core):** Ngôn ngữ/nền tảng chuyên môn chính (ví dụ: Python/Ruby backend, kế toán tổng hợp, chạy quảng cáo performance).
- **Công cụ phụ trợ (Tooling / Secondary):** Công cụ hỗ trợ quy trình (ví dụ: Docker, Git, thư viện test cụ thể, môi trường Linux).

**Quy tắc phân định:**

- **Chấm 4 điểm (Phù hợp — Đáng phỏng vấn):**
  - Đáp ứng tốt toàn bộ yêu cầu cốt lõi, chỉ thiếu **tối đa 1 yêu cầu phụ trợ nhỏ** mà ứng viên có thể dễ dàng tự học hoặc công ty đào tạo nhanh trong 1–2 tuần đầu thử việc (ví dụ: backend và SQL rất vững nhưng chưa từng dùng Docker trên thực tế).
  - Hoặc: Đạt đủ mọi yêu cầu bắt buộc nhưng bằng chứng còn mỏng, hoặc chưa có bất kỳ kỹ năng ưu tiên (nice-to-have) nào.
- **Chấm 3 điểm (Phù hợp một phần — Cân nhắc / Dự phòng):**
  - Thiếu **từ 2 yêu cầu bắt buộc trở lên** (kể cả công cụ phụ trợ, như Ví dụ C thiếu cả Docker lẫn test).
  - Hoặc: Thiếu **1 yêu cầu chuyên môn cốt lõi** dù có kỹ năng tương đương (ví dụ: JD tuyển Backend Python nhưng ứng viên làm Backend Java/Node.js; hoặc cần kế toán thuế nhưng ứng viên chỉ làm thủ kho). Trường hợp này cần nhiều thời gian đào tạo lại nên chỉ là phương án dự phòng khi pool ứng viên thiếu người tốt hơn.

### Ví dụ minh họa

Tin tuyển dụng dùng cho ví dụ: **Backend Engineer, mức junior** (`jd1-it-backend-junior.txt`). Các CV dưới đây chỉ để minh họa và **không thuộc dữ liệu cần chấm**.

**Ví dụ A: 5 điểm**

> Backend Engineer, 2 năm. Xây dựng REST API thanh toán cho ví điện tử bằng Python, FastAPI, SQLAlchemy, Alembic. PostgreSQL: thiết kế index, dùng transaction và ràng buộc để đảm bảo nhất quán dữ liệu. Dùng Redis cho hàng đợi tác vụ nền. Viết unit test và integration test bằng pytest, CI trên GitHub Actions, đóng gói Docker, triển khai trên Linux. Xử lý sự cố production: giảm lỗi trừ tiền trùng bằng idempotency key.

_Lý do:_ đủ mọi yêu cầu bắt buộc, mỗi mục có bằng chứng, lại có nhiều mục ưu tiên (FastAPI, Redis, idempotency, fintech).

**Ví dụ B: 4 điểm**

> Lập trình viên Python 1,5 năm. Django REST Framework, MySQL, Git, Docker. Viết unit test bằng Django TestCase, làm việc trên Ubuntu. Dự án: API quản lý đơn hàng cho website bán lẻ.

_Lý do:_ đủ Python, REST, cơ sở dữ liệu quan hệ (tin tuyển dụng chấp nhận "PostgreSQL hoặc tương tự"), Git, Linux, Docker, test. Điểm yếu: ít bằng chứng về integration test và xử lý sự cố, chưa có mục ưu tiên nào.

**Ví dụ C: 3 điểm**

> Sinh viên năm cuối ngành CNTT. Đồ án: ứng dụng quản lý thư viện bằng Python Flask và SQLite. Dùng Git để làm việc nhóm, đã cài và dùng Ubuntu. Chưa dùng Docker, chưa viết test.

_Lý do:_ có Python, REST, cơ sở dữ liệu, Git, Linux và một dự án cụ thể (tin tuyển dụng khuyến khích sinh viên mới tốt nghiệp có dự án). Thiếu Docker và test, là hai yêu cầu bắt buộc.

**Ví dụ D: 2 điểm**

> Frontend Developer 2 năm. React, TypeScript, Vue/Nuxt. Gọi REST API từ giao diện, dùng Git, chạy môi trường dev bằng Docker. Chưa làm backend hay cơ sở dữ liệu.

_Lý do:_ có Git, Docker, hiểu REST ở phía client và có Vue/Nuxt (mục ưu tiên), nhưng thiếu ngôn ngữ backend (Python/Rails), thiếu cơ sở dữ liệu và test backend.

**Ví dụ E: 1 điểm**

> Kỹ năng: Python, FastAPI, PostgreSQL, Docker, Redis, Git, Linux, pytest, SQLAlchemy, Alembic, Kafka. Kinh nghiệm: nhân viên kinh doanh 3 năm tại công ty thiết bị y tế. Học vấn: Cao đẳng Quản trị kinh doanh.

_Lý do:_ có đủ từ khóa nhưng không có công việc hay dự án nào cho thấy đã dùng. Kinh nghiệm làm việc không liên quan.

**Ví dụ F: ca đặc biệt, 4 điểm (diễn đạt khác)**

> Software engineer, 18 months. Built HTTP services on an async Py3 framework, designed relational schemas on Postgres, wrote integration tests, set up CI with GitHub Actions and containerised services with docker-compose, deployed on Linux.

_Lý do:_ không dùng chữ "FastAPI", "PostgreSQL", "Docker" đúng như tin tuyển dụng, nhưng "Py3 async framework", "Postgres", "containerised" cùng nghĩa. Đáp ứng yêu cầu bắt buộc, nên chấm như một CV viết đúng từ khóa.

---

## 3. Chọn Top 5 cho mỗi Job

Sau khi chấm xong tất cả CV của một Job:

1. Chọn **5 CV bạn muốn đưa vào danh sách phỏng vấn** cho vị trí này.
2. Xếp thứ tự từ **tốt nhất (hạng 1) đến hạng 5**.
3. Năm CV phải **khác nhau**. Không để trống hạng nào, kể cả khi Job đó chỉ có vài CV tốt (khi đó chọn 5 CV tốt nhất tương đối).
4. Top 5 nên nhất quán với điểm đã cho: không đưa vào Top 5 một CV điểm thấp hơn trong khi để ngoài một CV điểm cao hơn, trừ khi bạn có lý do rõ ràng. Nếu có, ghi chú ngắn vào cột `note`.
5. **Xử lý khi nhiều CV bằng điểm (Tie-breaking):** Nếu có nhiều CV cùng điểm (ví dụ 6 CV cùng 4 điểm) khiến bạn phân vân khi chọn Top 5 hoặc khi xếp hạng từ 1 đến 5, hãy phân loại dựa trên:
   - Số lượng và chất lượng các kỹ năng ưu tiên / điểm cộng (nice-to-have).
   - Quy mô, độ phức tạp của dự án và độ phù hợp của lĩnh vực (domain).
   - Mức độ rõ ràng của bằng chứng thực tế và kết quả đã đạt được.
6. Có thể sửa lại điểm của chính mình trước khi nộp.

---

## 4. Quy tắc làm việc

Các quy tắc này giúp nhãn của hai người có thể so sánh với nhau và với hệ thống.

1. **Chấm độc lập.** Hai người chấm không trao đổi với nhau về CV, về điểm, về Top 5 hay về cách hiểu hướng dẫn, trong và sau khi chấm. Nếu có thắc mắc về hướng dẫn, hỏi nhóm phát triển (không hỏi người chấm kia), và nhóm sẽ trả lời bằng thông báo chung cho cả hai.
2. **Không xem điểm của hệ thống.** Bạn sẽ không được cho biết điểm AI. Nếu thấy được ở đâu đó, báo cho nhóm.
3. **Thứ tự CV đã được xáo trộn** và khác nhau giữa hai người. Mã CV (ví dụ `c7f3`) chỉ là mã ngẫu nhiên, không phản ánh chất lượng. Hãy chấm theo thứ tự trong bảng của bạn.
4. **Không dùng công cụ AI** (ChatGPT, Gemini, Copilot…) để hỗ trợ chấm, tóm tắt hay dịch CV. Nếu cần dịch từ, dùng từ điển.
5. **Không tra cứu ứng viên.** Nếu bạn nhận ra một CV là người quen, báo cho nhóm ngay và không chấm CV đó. Nhóm sẽ thay thế.
6. **Chấm một Job trong một lượt**, tốt nhất không ngắt quãng nhiều ngày giữa các CV của cùng một Job, để thước đo của bạn ổn định.
7. **Chấm xong thì nộp,** không sửa sau khi đã nộp.

---

## 5. Thời gian

- Khoảng **5 phút mỗi CV** (đọc tin tuyển dụng một lần cho mỗi Job, thêm vài phút đọc kỹ).
- **Tập dev** (2 Job, khoảng 24 CV): khoảng **2 giờ** mỗi người.
- Tập test (4 Job, khoảng 48 CV hoặc hơn): nhóm sẽ gửi thông báo riêng với hạn nộp.
- Có thể chia thành 2 buổi, mỗi buổi một Job.

---

## 6. Bảng tính nhập kết quả

Mỗi người nhận **bản riêng** của bảng tính, gồm hai sheet. Đã có sẵn `job_id` và `cv_id`; bạn chỉ điền các cột còn trống.

**Sheet `scores`**: mỗi hàng là một cặp (Job, CV).

| job_id            | cv_id | score      | note                                   |
| ----------------- | ----- | ---------- | -------------------------------------- |
| it-backend-junior | c7f3  | _điền 1–5_ | _tùy chọn, ví dụ "đáng 4 nhưng sát 5"_ |

**Sheet `top5`**: mỗi hàng là một Job.

| job_id            | rank_1  | rank_2  | rank_3  | rank_4  | rank_5  |
| ----------------- | ------- | ------- | ------- | ------- | ------- |
| it-backend-junior | _cv_id_ | _cv_id_ | _cv_id_ | _cv_id_ | _cv_id_ |

Lưu ý:

- `score` chỉ nhận **số nguyên 1–5**. Không nhập 4,5 hay 9/10.
- `rank_1` đến `rank_5` điền bằng `cv_id`, không điền tên hay số thứ tự.
- **Giữ nguyên chính xác mã `job_id` và `cv_id`** (không đổi chữ hoa/thường, không thêm/bớt khoảng trắng hay ký tự lạ), vì hệ thống xử lý dữ liệu tự động so khớp chính xác từng ký tự của các mã này.
- Cột `note` không bắt buộc và sẽ không đưa vào dữ liệu thực nghiệm, chỉ để nhóm hiểu khi phân tích.

---

## 7. Cam kết bảo mật

Một số CV trong dữ liệu là CV thật, đã được chủ CV đồng ý và ẩn danh hóa (xóa tên, liên hệ, địa chỉ, ngày sinh, ảnh, liên kết cá nhân). Khi nhận CV để chấm, bạn cam kết:

1. Chỉ dùng CV và tin tuyển dụng cho mục đích chấm trong đề tài này.
2. Không sao chép, chụp màn hình, in, gửi cho người khác hoặc đưa vào công cụ AI.
3. Không tìm cách xác định danh tính chủ CV. Nếu nhận ra ai đó, báo cho nhóm và dừng chấm CV đó.
4. Không bàn luận nội dung CV với bất kỳ ai, kể cả người chấm còn lại.
5. Xóa mọi bản đã tải về sau khi nộp kết quả.

_Xác nhận:_ trả lời email gửi kèm tài liệu này bằng câu "Tôi đã đọc và đồng ý với cam kết bảo mật" (hoặc ký tên vào bản in). Nhóm lưu xác nhận này ngoài repo.

---

## 8. Dành cho nhóm phát triển (xóa phần này trước khi gửi)

### Chuẩn bị gửi cho người chấm

- [ ] Chuyển Phần 1–7 sang Google Doc hoặc PDF, bỏ Phần 8. Không gửi file Markdown.
- [ ] Gửi 6 JD (hoặc 2 JD dev) dạng `.txt` đã ẩn danh, không gửi PDF gốc.
- [ ] Với mỗi người chấm, tạo bản bảng tính riêng. Điền sẵn `job_id` và `cv_id`, **xáo thứ tự CV độc lập cho từng người**. Mã CV phải ngẫu nhiên (không đặt kiểu `be-01`).
- [ ] CV gửi dạng văn bản đã ẩn danh. Không gửi PDF/DOCX gốc.
- [ ] Mỗi người chấm chỉ thấy bản của mình (không dùng chung một file).

### Ví dụ minh họa

Sáu CV ở Phần 2 chỉ để minh họa cho Job `jd1`. **Không đưa chúng vào dataset.** Nếu dùng làm ví dụ cho Job khác, cần viết lại.

### Từ sheet sang dataset

- `scores` → `cvs[].labels` (`{"r1": 4, "r2": 5}`).
- `top5` → `top5.r1` / `top5.r2` (danh sách `cv_id` theo thứ tự).
- Dùng `r1`/`r2` làm id người chấm, không ghi tên.
- Loader của harness (`packages/eval`) từ chối nhãn không phải số nguyên 1–5 và Top 5 không đủ 5 CV khác nhau, nên lỗi nhập liệu sẽ bị bắt khi chạy thử.

### Việc còn lại theo ticket #44

- [ ] GVHD hoặc một người chấm đọc thử và góp ý. Ghi lại những chỗ họ hiểu khác nhau, sửa mô tả neo cho rõ rồi tăng phiên bản.
- [ ] Sau khi xác nhận, tăng phiên bản lên 1.0 và không sửa khi người chấm đã bắt đầu. Nếu sửa, thông báo cho cả hai.
