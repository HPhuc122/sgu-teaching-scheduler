# Bộ dữ liệu giả lập

Mỗi thư mục `synthetic_*` chứa ba file `courses.xlsx`, `rooms.xlsx`, `lecturers.xlsx` theo mẫu nhập tự động của hệ thống. Dữ liệu hoàn toàn hư cấu, tái tạo được bằng lệnh `generate_sample_workbooks` với seed 42; không phải dữ liệu hay biểu mẫu chính thức của Đại học Sài Gòn.

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
