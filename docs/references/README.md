# Tài liệu tham khảo — Smart ATS

Danh sách tài liệu dùng trong báo cáo khóa luận. Mỗi tài liệu phải hỗ trợ ít nhất một nhận định, quyết định thiết kế (ADR/FR) hoặc thực nghiệm ([Kế hoạch Thực nghiệm](../EVAL/experiment_plan.md)) cụ thể. Theo dõi tại issue #14.

**Quy tắc**

- Mỗi tài liệu là một file `.md` (bản toàn văn chuyển từ PDF), tên file là tiêu đề viết kebab-case.
- Chỉ thêm tài liệu đã xác minh có thật (DOI, arXiv ID hoặc URL chính thức) và có nơi đăng rõ ràng.
- Phép thử: *bỏ tài liệu này thì câu nào trong báo cáo mất căn cứ?* Không chỉ ra được → bỏ.
- Trích bản đã xuất bản chính thức. Nếu file trong thư mục là bản arXiv nhưng bài đã được nhận đăng, trích theo nơi đăng ghi trong bảng.
- Preprint chưa qua bình duyệt vẫn được trích, nhưng ghi rõ "preprint" và ưu tiên bài đã bình duyệt nếu cùng một ý.
- Bản toàn văn có bản quyền của nhà xuất bản (ACM, IPSJ, Anthropic…). Chỉ giữ trong repo private; nếu repo chuyển sang public thì xóa các file toàn văn, chỉ giữ README này.

## Danh sách

Định dạng trích dẫn: IEEE. Vai trò: **Biện minh** (căn cứ cho quyết định thiết kế), **Phương pháp** (thực nghiệm dùng lại metric/quy trình), **Động cơ** (vấn đề có thật), **Định vị** (khác công trình trước ở đâu), **Hạn chế** (bằng chứng ngược chiều, dùng cho phần Threats to validity).

### Chấm điểm lai: rubric có neo và Evidence (ADR-0006, FR-A1.3, Experiment 1)

Đóng góp chính của khóa luận (SAD §1).

| # | Trích dẫn | File | Vai trò | Dùng cho |
|---|---|---|---|---|
| 1 | S. Vaishampayan *et al.*, "Human and LLM-based resume matching: An observational study," in *Findings Assoc. Comput. Linguistics: NAACL 2025*, 2025, pp. 4823–4838. | `human-and-llm-based-resume-matching.md` | Động cơ, Phương pháp, Định vị | So điểm GPT-4 zero-shot với người chấm trên 736 CV: điểm LLM chỉ tương quan yếu với người nên không thay thế được. Là căn cứ cho việc Experiment 1 đo Spearman ρ so với HR thay vì mặc định tin LLM. CoT cải thiện chất lượng chấm; điểm LLM không chênh lệch giữa nhóm giới/chủng tộc nhiều hơn người (dùng thêm cho Experiment 6). |
| 2 | Q. Li, S. Dou, K. Shao, C. Chen, and H. Hu, "Evaluating scoring bias in LLM-as-a-judge," in *Proc. DASFAA*, 2026. (arXiv:2506.22316) | `evaluating-scoring-bias-in-llm-as-a-judge.md` | Biện minh | Điểm của LLM thay đổi khi chỉ đổi prompt chấm: thứ tự các mức rubric, ký hiệu điểm, điểm của đáp án mẫu. Là căn cứ cho việc cố định rubric, versioning `rubric_version` / `prompt_version`, và không cho LLM chấm tự do 0–100. |
| 3 | A. Bagaria, S. S. Sundaram, G. S. Krishnan, and B. Ravindran, "Judging LLM-as-a-judge: Concerning rubric artifacts in LLM-based automated text generation evaluation," in *Proc. EMNLP*, 2026. (arXiv:2609.02942) | `judging-llm-as-a-judge.md` | Hạn chế | Chỉ từ nội dung rubric (không xem câu trả lời) đã đoán được điểm ở mức đáng kể; model chấm thường không đổi điểm khi câu trả lời hoặc tiêu chí bị đảo ngược. Đưa vào phần hạn chế: rubric có neo giảm trôi điểm nhưng không loại bỏ được thiên lệch do cách viết rubric. |
| 4 | A. Yeginbergen, A. Wührl, A. Rogers, and R. Agerri, "Explicit evidence grounding via structured inline citation generation," arXiv:2606.07130, 2026. *Preprint.* | `explicit-evidence-grounding-via-structured-inline-citation-generation.md` | Biện minh, Phương pháp | LLM tìm đúng tài liệu liên quan khá tốt nhưng kém khi chỉ ra chính xác đoạn bằng chứng. Là căn cứ cho việc kiểm chứng Evidence bằng code (so khớp với văn bản gốc, loại quote không tìm thấy) và cho metric grounding rate. |

### Agent (FR-A0, ADR-0004, Experiment 3)

| # | Trích dẫn | File | Vai trò | Dùng cho |
|---|---|---|---|---|
| 5 | L. Wang *et al.*, "A survey on large language model based autonomous agents," *Front. Comput. Sci.*, vol. 18, no. 6, Art. 186345, 2024, doi: 10.1007/s11704-024-40231-1. | `a-survey-on-large-language-model-based-autonomous-agents.md` | Định vị | Định nghĩa agent và khung profile / memory / planning / action trong chương Cơ sở lý thuyết. |
| 6 | S. Yao *et al.*, "ReAct: Synergizing reasoning and acting in language models," in *Proc. ICLR*, 2023. | `react-synergizing-reasoning-and-acting-in-language-models.md` | Biện minh | Bước ACT của Campaign: xen kẽ suy luận và gọi tool. |
| 7 | N. Shinn, F. Cassano, A. Gopinath, K. Narasimhan, and S. Yao, "Reflexion: Language agents with verbal reinforcement learning," in *Proc. NeurIPS*, 2023. | `reflexion-language-agents-with-verbal-reinforcement-learning.md` | Biện minh | Bước REFLECT. **Lưu ý:** Reflexion phản tư qua nhiều lần thử với bộ nhớ episodic; REFLECT của Smart ATS chỉ kiểm tra `qualified_count ≥ target_count` trong một lượt (tối đa 2 vòng). Viết là "lấy cảm hứng từ", không viết là "cài đặt Reflexion". |
| 8 | Anthropic, "Building effective agents," *Anthropic Engineering*, Dec. 19, 2024. [Online]. Available: https://www.anthropic.com/engineering/building-effective-agents | `building-effective-agents.md` | Biện minh | Phân biệt *workflow* và *agent*: lý do scoring là pipeline tất định còn Campaign mới là agent; lý do baseline của Experiment 3 là workflow cố định. Nguồn ngành, không qua bình duyệt. |
| 9 | S. Yao, N. Shinn, P. Razavi, and K. Narasimhan, "τ-bench: A benchmark for tool-agent-user interaction in real-world domains," in *Proc. ICLR*, 2025. | `a-benchmark-for-tool-agent-user-interaction-in-real-world-domains.md` | Phương pháp | Experiment 3: đánh giá agent bằng trạng thái cuối so với trạng thái mục tiêu và tuân thủ policy (tương ứng bất biến "0 vi phạm"); metric pass^k cho độ ổn định qua nhiều lần chạy. File là bản preprint arXiv; trích bản ICLR 2025. |

### Sàng lọc CV bằng LLM agent (Tổng quan)

| # | Trích dẫn | File | Vai trò | Dùng cho |
|---|---|---|---|---|
| 10 | C. Gan, Q. Zhang, and T. Mori, "Application of LLM agents in recruitment: A novel framework for automated resume screening," *J. Inf. Process.*, vol. 32, pp. 881–893, 2024, doi: 10.2197/ipsjjip.32.881. | `application-of-llm-agents-in-recruitment-a-novel-framework-for-automated-resume-screening.md` | Định vị, Động cơ | Công trình gần nhất. Điểm khác để nêu trong Tổng quan: (a) bài cho LLM chấm điểm tự do "Grade: XX/100", đúng Config B trong ablation, cách mà ADR-0006 loại bỏ; (b) bài ẩn thông tin cá nhân bằng phân loại câu, tương tự Blind Profile; (c) agent "CEO" tự chọn ứng viên, trong khi Smart ATS dừng tại Checkpoint để Recruiter quyết định. Số liệu "nhanh hơn 11 lần so với sàng lọc thủ công" dùng cho phần Động cơ. |

### Prompt injection (FR-C2.2, Experiment 2)

| # | Trích dẫn | File | Vai trò | Dùng cho |
|---|---|---|---|---|
| 11 | Y. Liu, Y. Jia, R. Geng, J. Jia, and N. Z. Gong, "Formalizing and benchmarking prompt injection attacks and defenses," in *Proc. 33rd USENIX Security Symp.*, 2024. | `formalizing-and-benchmarking-prompt-injection-attacks-and-defenses.md` | Phương pháp, Biện minh | Định nghĩa hình thức tấn công vào ứng dụng tích hợp LLM; phân loại kiểu tấn công làm cơ sở cho bộ 10 kiểu tấn công; so sánh có/không phòng thủ như Experiment 2. |

### Thiên kiến (FR-C2.4 Blind Profile, Experiment 6)

| # | Trích dẫn | File | Vai trò | Dùng cho |
|---|---|---|---|---|
| 12 | J. An, D. Huang, C. Lin, and M. Tai, "Measuring gender and racial biases in large language models: Intersectional evidence from automated resume evaluation," *PNAS Nexus*, vol. 4, Art. pgaf089, 2025, doi: 10.1093/pnasnexus/pgaf089. | `measuring-gender-and-racial-biases-in-large-language-models.md` | Phương pháp, Động cơ | Thiết kế Experiment 6: giữ nguyên nội dung CV, chỉ đổi danh tính rồi so điểm (~361.000 CV, 5 LLM). Thiên kiến không theo chiều dự đoán (ưu ái ứng viên nữ, bất lợi cho nam da đen): căn cứ cho việc phải đo chứ không giả định, và báo cáo trung thực kể cả khi không thấy thiên kiến. |
| 13 | M. Raghavan, S. Barocas, J. Kleinberg, and K. Levy, "Mitigating bias in algorithmic hiring: Evaluating claims and practices," in *Proc. Conf. Fairness, Accountability, and Transparency (FAT\*)*, 2020, doi: 10.1145/3351095.3372828. | `mitigating-bias-in-algorithmic-hiring.md` | Động cơ, Định vị | Nhà cung cấp công cụ tuyển dụng AI tuyên bố giảm thiên kiến nhưng ít công bố cách kiểm chứng; lý do Smart ATS biến "giảm thiên kiến" thành thực nghiệm đo được. Bản chuyển đổi thiếu tên Barocas và Levy ở đầu file; trích đủ 4 tác giả như trên. |

Xem thêm #1 (Vaishampayan 2025) cho so sánh thiên kiến giữa LLM và người chấm.

## Đã loại

| Tài liệu | Lý do |
|---|---|
| Rasmi M., "Prompt injection and the security of LLM applications and agents," *Peer-Reviewed J. Comput. Sci. (PRJCS)*, vol. 1, no. 8, 2026, doi: 10.5281/zenodo.22720682. | Tạp chí mới (tập 1), phạm vi rất rộng, đăng cả bài kiểu hướng dẫn ("Getting Started With Kubernetes"), DOI là Zenodo tự lưu trữ; không có trên Scimago/Scopus. Đã xóa file toàn văn. Các bài gốc nó trích được chuyển sang mục "Còn thiếu". |

## Còn thiếu

Sắp theo mức ưu tiên. Mọi gợi ý phải tự xác minh trước khi thêm.

| Ưu tiên | Mảng | Cần cho | Gợi ý |
|---|---|---|---|
| Cao | Rubric có neo, chấm theo nhiều chiều | ADR-0006 (3 Axis Score, rubric 1–5) | H. Hashemi *et al.*, "LLM-Rubric," ACL 2024; S. Kim *et al.*, "Prometheus 2," EMNLP 2024. |
| Cao | Độ ổn định khi `temperature=0` | ADR-0006, Experiment 1 (metric độ ổn định) | B. Atil *et al.*, "Non-determinism of 'deterministic' LLM settings," arXiv:2408.04667 (preprint). |
| Cao | Ràng buộc JSON Schema | ADR-0006, SAD §7 | Z. R. Tam *et al.*, "Let me speak freely?," EMNLP 2024 Industry. Ép định dạng có thể giảm khả năng suy luận: kiểm tra thứ tự trường trong schema (lập luận và Evidence trước, điểm sau). |
| Trung bình | Tổng quan LLM-as-a-judge | Cơ sở lý thuyết | D. Li *et al.*, "From generation to judgment," EMNLP 2025; L. Zheng *et al.*, "Judging LLM-as-a-judge with MT-Bench and Chatbot Arena," NeurIPS 2023. |
| Trung bình | Prompt injection gián tiếp | Experiment 2, thẻ `<untrusted_document>` | Greshake *et al.*, AISec 2023; Hines *et al.* 2024 (spotlighting); OWASP Top 10 for LLM Applications. |
| Trung bình | Truy hồi và embedding | ADR-0005, Rediscovery, baseline Experiment 1 | BM25 (Robertson & Zaragoza 2009); Sentence-BERT (Reimers & Gurevych 2019); HNSW (Malkov & Yashunin 2020). |
| Trung bình | Metric đánh giá | Experiment 1 | NDCG (Järvelin & Kekäläinen 2002); weighted kappa (Cohen 1968). |
| Trung bình | Phương pháp audit thiên kiến gốc | Experiment 6 | Bertrand & Mullainathan 2004 (thí nghiệm đổi tên ứng viên). |
| Thấp | Multi-tenant và RLS | ADR-0001, Experiment 4 | Chong *et al.* 2006 (Multi-Tenant Data Architecture); PostgreSQL docs, *Row Security Policies*. |
| Thấp | Pháp lý | FR-C1.5 | Nghị định 13/2023/NĐ-CP; Luật Bảo vệ dữ liệu cá nhân 2025; EU AI Act (AI tuyển dụng thuộc nhóm rủi ro cao). |
