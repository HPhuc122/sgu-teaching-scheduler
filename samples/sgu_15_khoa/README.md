# Ba bộ Excel mô phỏng 15 khoa SGU

Mỗi thư mục `bo_01`, `bo_02`, `bo_03` có đúng ba tệp để tải lên trang **Xếp lịch tự động**: `courses.xlsx`, `rooms.xlsx`, `lecturers.xlsx`. Ba bộ độc lập, lần lượt chứa 240, 480 và 960 buổi yêu cầu. Chọn đúng học kỳ trước khi tải:

| Thư mục | Học kỳ trong giao diện | Số buổi |
| --- | --- | ---: |
| `bo_01` | `SGU DEMO 15 khoa - BO_01` | 240 |
| `bo_02` | `SGU DEMO 15 khoa - BO_02` | 480 |
| `bo_03` | `SGU DEMO 15 khoa - BO_03` | 960 |

Sau khi chạy thành công, quản trị viên xem kết quả chờ duyệt, duyệt lịch rồi mới xem tại **Thời khóa biểu khoa**. Ba học kỳ `SGU DEMO` không được tạo sẵn trên giao diện nữa. Nếu muốn thử một bộ, dùng nút **+ Tạo học kỳ mới** và nhập đúng tên học kỳ trong bảng với 16 tuần trước khi tải file. Không tải trực tiếp vào học kỳ HK1 2026–2027 đang có lịch, vì các nhóm học phần đã duyệt có thể trùng.

Kiểm thử ngày 13/10/2026 trên ba cơ sở dữ liệu SQLite tách biệt: bộ giải xếp đủ lần lượt 240/240, 480/480, 960/960 buổi; bộ kiểm tra độc lập không thấy trùng phòng, giảng viên, nhóm hoặc lớp theo tuần và tiết. Mỗi kết quả có giảng viên thuộc đủ 15 khoa. Trạng thái thuật toán là `HEURISTIC`, tức có lịch hợp lệ nhưng chưa chứng minh tối ưu. Bộ 240 còn được thử duyệt 240/240 buổi thành công. Lần chạy trên máy khác có thể khác về thời gian hoặc phương án.

Tên 15 khoa theo [danh sách đơn vị của SGU](https://www.sgu.edu.vn/danh-sach-cac-don-vi/). Học phần, nhóm, giảng viên được trích và lấy mẫu từ [sổ tay đăng ký môn học HK1 2026–2027](https://daotao.sgu.edu.vn/index.php/thong-bao/so-tay-dang-ki-mon-hoc/so-tay-dang-ki-mon-hoc-hk1-nh-2026-2027). Ánh xạ ngành và học phần chung sang khoa là **suy luận để mô phỏng**, không phải phân công chính thức. Sức chứa, loại phòng, quyền dạy và tuần học là giả định có ghi chi tiết trong `bo_XX_provenance.json`. Kết quả xếp lịch là phương án thử nghiệm, không phải lịch đã công bố của SGU.

Tạo lại các file bằng `python analysis/sgu_public_demo.py --fetch`, sau đó chạy `python analysis/prepare_sgu_15_faculty_packs.py`. Các tệp JSON bên ngoài ba thư mục là siêu dữ liệu nguồn; chúng không cần tải lên giao diện.
