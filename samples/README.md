# Bộ dữ liệu giả lập

Bộ trình diễn theo biểu mẫu nằm ở [ke_hoach_bieu_mau](ke_hoach_bieu_mau/README.md): ba học kỳ, đủ 15 khoa, 240/480/960 buổi. Bộ này dùng học phần SGU có nguồn và hồ sơ giảng viên hư cấu với họ tên tự nhiên. Các bộ `synthetic_*` dưới đây dành cho kiểm thử kỹ thuật.

Mỗi thư mục `synthetic_*` chứa ba file `courses.xlsx`, `rooms.xlsx`, `lecturers.xlsx` theo mẫu nhập tự động của hệ thống. Dữ liệu hoàn toàn hư cấu, tái tạo được bằng lệnh `generate_sample_workbooks` với seed 42; không phải dữ liệu hay biểu mẫu chính thức của Đại học Sài Gòn. Ở sheet `BuoiHocYeuCau`, `ma_vien_chuc_phan_cong` là tùy chọn: mã được điền sẽ giữ giảng viên đó, còn ô trống cho phép thuật toán chọn giảng viên đủ chuyên môn.

| Thư mục | Số buổi | Mục đích |
| --- | ---: | --- |
| `synthetic_80_seed42` | 80 | Kiểm tra toàn luồng nhỏ |
| `synthetic_160_seed42` | 160 | Kiểm tra giới hạn CP-SAT 30 giây và lịch khởi tạo |
| `synthetic_320_seed42` | 320 | Kiểm tra tải lớn |
| `synthetic_449_seed42` | 449 | Sát giới hạn nhập cũ của file Học phần |
| `synthetic_1000_seed42` | 1.000 | Thử luồng mở rộng ba file, 16 tuần |
| `synthetic_2000_seed42` | 2.000 | Thử luồng mở rộng nhiều khoa, 16 tuần |
| `synthetic_80_infeasible_seed42` | 80 | Kiểm tra báo cáo vô nghiệm |

Các thư mục `synthetic_1000_feasible_seed7`, `synthetic_1000_feasible_seed17`, `synthetic_2000_feasible_seed7` đổi seed so với bộ cơ sở. Các thư mục có `constrained` dùng ít phòng và giảng viên hơn, đồng thời chặn sáng thứ Hai ở một phần nguồn lực. `synthetic_1000_infeasible_seed42` kiểm tra quá tải 15 tiết của cùng lớp trong một ngày chỉ có 13 tiết. Báo cáo tương ứng nằm trong các file `bench_*_report.json`.

Các file `bench_*_report.json` ghi kết quả từng lần thử trên SQLite tách biệt; `bench_449_final_report.json` là lượt chạy sau khi thêm lớp kiểm tra cuối. Xem [hướng dẫn và giới hạn kiểm thử](../docs/du_lieu_gia_lap_va_kiem_thu.md).
