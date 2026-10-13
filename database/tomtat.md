# CHUẨN BỊ VẤN ĐÁP — Dự án UCTP (Hệ thống hỗ trợ quản lý và phân công giảng dạy)

---

## 1. TÓM TẮT ĐỀ TÀI (nói trong 1-2 phút đầu)

Đề tài xây dựng hệ thống hỗ trợ **quản lý và phân công giảng dạy cấp khoa**, với phần lõi khoa học là một **thuật toán tối ưu hóa ràng buộc** giải bài toán xếp lịch giảng dạy (Time + Room + Teacher), được **thực nghiệm nghiêm túc trên bộ dữ liệu chuẩn quốc tế ITC 2019** trước khi tích hợp vào phần mềm.

Điểm khác biệt so với đồ án thông thường: không chỉ dừng ở quản lý danh mục + phân công thủ công có kiểm tra ràng buộc, mà có **một thuật toán tự động đề xuất** được đo lường, kiểm chứng, và **so sánh trực tiếp với kết quả thật của 6 đội thi từng tham gia cuộc thi ITC 2019**.

---

## 2. KIẾN TRÚC THUẬT TOÁN — Thuật toán Lai 3 Giai đoạn (3-Stage Hybrid Matheuristic)

Chia làm **2 pha phát triển**:

- **Pha A**: giải Room + Time + Distribution Constraints (đúng bài toán gốc ITC 2019, chưa có giảng viên) — dùng để so sánh công bằng với thế giới.
- **Pha B**: bổ sung biến Giảng viên (Teacher Assignment) — mở rộng bài toán, phục vụ mục tiêu thực tế của hệ thống.

### Stage 0 — Heuristic phân loại giảng viên
Tính 2 chỉ số cho mỗi giảng viên/lớp:
- $Deg(i) = |C_i|$ — số lớp giảng viên $i$ có thể dạy (bậc chuyên môn).
- $Bottleneck(c) = \dfrac{1}{|I_c|+\epsilon}$ — độ khan hiếm giảng viên của lớp $c$.

Phân 3 nhóm: **Đơn năng** (Deg ≤ 1), **Trung bình** (2-3), **Đa năng** (≥4). Dùng để hiểu cấu trúc khan hiếm, không trực tiếp là biến quyết định.

### Stage 1 — CP-SAT (ràng buộc cứng, đảm bảo Hard_Penalty = 0)
- Dùng Google OR-Tools CP-SAT, biến quyết định: lớp nào → giờ nào, phòng nào (Pha A), + giảng viên nào (Pha B).
- Xử lý đúng **19 loại ràng buộc phân bổ chuẩn ITC 2019** (SameTime, Precedence, WorkDay, MaxDayLoad, MaxBlock...).
- Kỹ thuật tối ưu hiệu năng: `Interval Variable + NoOverlap` (không so sánh tay từng cặp lớp — tránh bùng nổ tổ hợp).

### Stage 2 — Adaptive Iterated Local Search + Great Deluge (ràng buộc mềm)
- Xuất phát từ nghiệm khả thi của Stage 1, tối ưu Soft Penalty (Time + Room + Distribution + Teacher Preference).
- Cơ chế Great Deluge: chấp nhận cả nghiệm tạm xấu hơn miễn dưới 1 "mực nước" giảm dần theo thời gian — giúp thoát cực trị địa phương tốt hơn hill-climbing thuần.
- Cơ chế **Perturbation/Kick**: khi không cải thiện sau N vòng liên tiếp, chủ động xáo trộn để nhảy sang vùng tìm kiếm khác — đúng đúng phần "Iterated" trong tên thuật toán.
- Tối ưu hiệu năng bằng **Delta Objective**: chỉ tính phần thay đổi do 1-2 lớp vừa di chuyển, không tính lại toàn bộ mỗi vòng lặp — đã đối chiếu khớp tuyệt đối với cách tính lại từ đầu.

---

## 3. DỮ LIỆU THỰC NGHIỆM

- Bộ dữ liệu chuẩn quốc tế **ITC 2019** (International Timetabling Competition), 30 instance thực tế từ ~10 trường đại học.
- Instance chính dùng đánh giá: **muni-fi-fal17** — 535 lớp học phần, 36 phòng học (số liệu đã đối chiếu với 2 bài báo học thuật chính thức, không phải số tự đếm).
- Lý do chọn: có sẵn kết quả công bố của UniTime và nhiều đội thi để so sánh trực tiếp.

---

## 4. KẾT QUẢ ĐẠT ĐƯỢC

### Pha A (Room + Time + Distribution)
- Stage 1: **OPTIMAL, Hard_Penalty = 0** trên toàn bộ 535 lớp, đủ 19 loại ràng buộc.
- Stage 2: Soft Penalty giảm từ **4751 → 3924** (giảm 17,4%) nhờ cơ chế Great Deluge + Kick.
- **So sánh với 6 đội thi thật của ITC 2019 trên cùng instance**:

| Đội / nguồn | Soft Penalty | So với kết quả của mình (3924) |
|---|---|---|
| Holm | 2837 | Kém hơn 38,3% |
| UniTime (Müller) | 3180 | Kém hơn 23,4% |
| Kết quả tốt nhất công bố | 3506 | Kém hơn 11,9% |
| Rappos | 3794 | Kém hơn 3,4% |
| Trung bình các đội | 3789,5 | Kém hơn 3,5% |
| **Lemos** | **4161** | **Tốt hơn 5,7%** |
| **Gashi** | **4712** | **Tốt hơn 16,7%** |
| **Er-rhaimini** | **4820** | **Tốt hơn 18,6%** |

→ **Vượt qua 3/6 đội thi thật**, chỉ kém đội gần nhất (Rappos) đúng 3,4% — kết quả cạnh tranh tốt cho lần triển khai đầu, **chưa tinh chỉnh sâu tham số**.

### Pha B (bổ sung Teacher)
- Sinh dữ liệu giảng viên tổng hợp (synthetic) có kiểm soát — vì **ITC 2019 gốc không có khái niệm phân công giảng viên** (đã xác minh qua tài liệu chính thức).
- 535/535 lớp được gán giảng viên hợp lệ (qua 2 lớp "vá" đảm bảo khả thi khi kịch bản khan hiếm quá gắt).
- Stage 2 mở rộng: thêm Teacher Preference Penalty + toán tử Lecturer-Reassign — cải thiện thêm 20-26% trên các test.

---

## 5. CÁC QUYẾT ĐỊNH THIẾT KẾ QUAN TRỌNG (và lý do — cố vấn rất hay hỏi "vì sao")

| Quyết định | Lý do |
|---|---|
| Bỏ Student Sectioning | Mục tiêu hệ thống là phân công giảng dạy, việc sinh viên đăng ký học phần là hệ thống khác, không thuộc phạm vi |
| Tách Pha A / Pha B thay vì giải chung 1 lần | Giảm rủi ro: kiểm chứng được tầng lõi (so sánh thế giới) trước khi thêm độ phức tạp giảng viên |
| Chọn UniTime + kết quả các đội thi làm chuẩn so sánh | UniTime là hệ thống sinh ra chính bộ dữ liệu ITC 2019, có kết quả công bố chính thức, đáng tin cậy nhất hiện có |
| Sinh giảng viên tổng hợp (synthetic) thay vì tìm bộ dữ liệu có sẵn | Đã khảo sát: không có benchmark chuẩn nào (kể cả Socha, ITC 2007) có khái niệm giảng viên — đây là khoảng trống nghiên cứu thật, có cơ sở từ chính module Instructor Scheduling của UniTime |
| Dùng "Cách Gộp Chung" thay vì Sequential Fixing cho gán giảng viên | Thực nghiệm cho thấy Sequential Fixing **thất bại** (không tìm được nghiệm) ở cả 2 test, trong khi tốc độ không nhanh hơn — nên chọn cách vừa đúng vừa không chậm hơn |
| MaxBlock chỉ xử lý xấp xỉ (không xử lý đầy đủ) | Chính tài liệu MIP gốc của ITC 2019 cũng thừa nhận loại ràng buộc này "không thể biểu diễn đầy đủ chỉ bằng ràng buộc theo cặp" — đây là giới hạn đã biết, không phải thiếu sót |

---

## 6. KHÓ KHĂN KỸ THUẬT ĐÃ VƯỢT QUA (thể hiện chiều sâu hiểu vấn đề, không chỉ chạy code)

Quá trình debug Stage 1 phát hiện và sửa đúng **4 nguyên nhân** gây `INFEASIBLE` giả trên instance thật, đều là hiểu sai ban đầu về luật ITC 2019, không phải lỗi cú pháp:

1. Tưởng nhầm "sức chứa phòng ≥ sĩ số" là ràng buộc cứng — thực tế đây là ràng buộc **mềm** (đã phản ánh qua penalty có sẵn trong dữ liệu).
2. Bỏ sót yếu tố "tuần học" (weeks bitmask) khi kiểm tra trùng phòng — nhiều lớp thực tế xen kẽ tuần chẵn/lẻ để dùng chung phòng hợp lệ.
3. Một số lớp **không cần phòng** (hợp lệ theo luật, ví dụ lớp online) nhưng code cũ ép buộc phải chọn phòng.
4. Ràng buộc Precedence chỉ so giờ-trong-ngày, bỏ qua lớp học ngày nào trong tuần.

Về hiệu năng: phát hiện và sửa lỗi bùng nổ tổ hợp ở bước xây mô hình CP-SAT (từ ~600.000 ràng buộc tay xuống còn vài chục nghìn biến nhờ `Interval + NoOverlap`), và tối ưu Stage 2 bằng kỹ thuật Delta Objective để đủ nhanh cho instance 535 lớp.

---

## 7. HẠN CHẾ ĐÃ BIẾT (chủ động nói trước — thể hiện trung thực khoa học)

- `MaxBlock` chỉ xử lý xấp xỉ theo cặp (điều kiện cần, chưa chắc đủ với chuỗi 3+ lớp nối tiếp).
- Dữ liệu giảng viên và nguyện vọng giờ dạy là **tổng hợp (synthetic)**, không phải dữ liệu thật — vì ITC 2019 không có sẵn.
- Tham số `decay_rate` của Great Deluge nhạy với quy mô instance — cần tinh chỉnh riêng, chưa có công thức tự động chọn tham số tối ưu.
- Web + CSDL mới ở giai đoạn thiết kế (đã có schema SQL Server + cấu trúc thư mục Django), chưa triển khai code thật.

---

## 8. HƯỚNG PHÁT TRIỂN TIẾP THEO

- Thiết kế CSDL (SQL Server) đã hoàn thành: các bảng chính Khoa/BoMon/GiangVien/HocPhan/LopHocPhan/PhongHoc/PhanCong/CauHinhTiet..., có quy tắc nghiệp vụ ưu tiên xếp Ca 1-2 trước Ca 3 mã hóa trực tiếp vào dữ liệu.
- `CauHinhTiet` (giờ từng tiết học) tham khảo khung giờ thật của Trường Đại học Sài Gòn.
- Kiến trúc web: Django + DRF (backend) — React (frontend), tích hợp lại đúng code thuật toán đã thực nghiệm qua lớp "adapter" chuyển đổi dữ liệu CSDL ↔ cấu trúc dữ liệu thuật toán.

---

## 9. CÂU HỎI DỰ KIẾN TỪ CỐ VẤN + GỢI Ý TRẢ LỜI

**Q: Vì sao không dùng thuật toán di truyền (GA) hay thuật toán khác phổ biến hơn?**
→ CP-SAT đảm bảo tìm được nghiệm khả thi có chứng minh (hoặc chứng minh vô nghiệm) cho ràng buộc cứng — GA không có tính chất này, dễ tốn thời gian mà vẫn không chắc khả thi. Kết hợp CP-SAT (khả thi) + metaheuristic (tối ưu mềm) là hướng tiếp cận matheuristic kinh điển, tận dụng ưu điểm cả 2.

**Q: Làm sao biết kết quả đáng tin, không phải chỉ chạy ra số đẹp?**
→ Đối chiếu Delta Objective với tính lại từ đầu khớp tuyệt đối ở mọi bước; so sánh trực tiếp với 6 kết quả công bố chính thức của ITC 2019, không tự đặt ra thước đo riêng.

**Q: Vì sao Pha B (giảng viên) lại là dữ liệu tự sinh, có đáng tin không?**
→ Vì bản thân ITC 2019 không có biến giảng viên (đã kiểm chứng qua tài liệu chính thức) — đây là khoảng trống nghiên cứu thật, có cơ sở khoa học từ module Instructor Scheduling thật của UniTime, không phải tự nghĩ ra tùy tiện.

**Q: Thuật toán có chạy được với dữ liệu lớn hơn/thực tế của trường không?**
→ Đã kiểm chứng khả năng mở rộng: từ instance nhỏ (150 lớp) tới 535 lớp đều chạy ổn định trong thời gian hợp lý (vài phút), nhờ các kỹ thuật tối ưu hiệu năng (Interval+NoOverlap, Delta Objective).

**Q: Điểm mới/đóng góp khoa học cụ thể là gì (đừng nói chung chung)?**
→ (1) Kết hợp CP-SAT + AILS/Great Deluge có Kick cho bài toán timetabling, kiểm chứng trên benchmark thật; (2) Mở rộng ITC 2019 sang bài toán Faculty Assignment có cơ sở khoa học rõ ràng; (3) Baseline định lượng đầu tiên cho bài toán mở rộng đó, so sánh minh bạch với 6 kết quả công bố thật.
