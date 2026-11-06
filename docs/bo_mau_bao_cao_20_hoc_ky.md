# Bộ 20 kết quả theo quy trình biểu mẫu và một bộ chạy báo cáo

## Phạm vi

- 20 học kỳ mô phỏng liên tiếp từ HK3 năm học 2019–2020 đến HK1 năm học 2026–2027.
- Mỗi học kỳ có đủ 15 khoa, ba workbook đầu vào và các workbook đầu ra theo khoa: bộ Mẫu 1–5 và chi tiết thời khóa biểu đã duyệt.
- Quy mô luân phiên 240, 480 và 960 buổi. Tổng cộng 10.800 buổi yêu cầu cho 20 học kỳ.
- Bộ 21 là HK2 năm học 2026–2027, có 480 buổi; dành để tải ba file và chạy trực tiếp khi báo cáo. Bộ này không có kết quả trong CSDL trình diễn.

Đây là các **học kỳ mô phỏng**, không phải hồ sơ lịch sử của SGU. Danh mục khoa, môn, mã môn và phòng tham chiếu nguồn công khai đã lưu; ngày học kỳ, kế hoạch, phân công, hoạt động và nguyện vọng được tạo để kiểm thử. Hồ sơ giảng viên dùng tên hư cấu tự nhiên và mã MPGV, không chép danh tính trong ảnh biểu mẫu nội bộ. Khóa và mã lớp được dịch theo năm mô phỏng; không khẳng định chương trình đào tạo hiện tại đã được áp dụng ở những năm trước.

## Cấu trúc thư mục

- `samples/bao_cao_21_hoc_ky/`: 21 thư mục; mỗi thư mục có `courses.xlsx`, `rooms.xlsx`, `lecturers.xlsx` và `thong_tin.json` ghi ngày, seed, quy mô, nguồn và SHA-256.
- `outputs/bao_cao_20_mau/`: 20 thư mục kết quả. Mỗi thư mục có 15 file `Kxx_bieu_mau_1_5.xlsx`, 15 file `Kxx_thoi_khoa_bieu.xlsx`, kết quả kiểm chứng và nhật ký thuật toán.
- `outputs/bao_cao_20_mau/tong_hop.csv`: bảng tổng hợp để mở bằng Excel; `manifest.json` liên kết đầu vào và đầu ra.
- `outputs/bao_cao_20_mau/backup_truoc_thay_output.sqlite3`: CSDL trước khi thay dữ liệu.

## Quy trình tạo và kiểm chứng

1. Sao lưu SQLite bằng API backup, làm việc trong CSDL staging.
2. Bỏ lịch và kế hoạch cũ khỏi staging, giữ tài khoản và phân quyền.
3. Sinh workbook theo đúng hợp đồng nhập của ứng dụng hiện tại, có phân công cố định, LT/TH, công tác khác, mời/thỉnh giảng và hoạt động ngoài trường.
4. Lưu kế hoạch độc lập; tạo 30 nguyện vọng/học kỳ (ngày không thể dạy và khung giờ ưu tiên).
5. Gọi hàng đợi và worker thật với chính ba file đầu vào. Không tự dựng lịch hoặc thay kết quả thuật toán.
6. Kiểm tra lịch đã lưu: đủ từng buổi, đúng người dạy cố định, số tiết, tập tuần, điều kiện phòng, chuyên môn, thời gian không khả dụng, lớp và hoạt động; tính lại điểm bằng scorer.
7. Duyệt qua dịch vụ của hệ thống, kiểm tra đầy đủ toàn học kỳ và theo từng khoa, xuất workbook bằng bộ xuất của ứng dụng.
8. Khóa 20 học kỳ có kết quả. HK2 2026–2027 để mở và chưa có lịch/kế hoạch nhập sẵn.

Các sheet của Mẫu 1 cho học kỳ không được chọn có thể trống. Mẫu 3/4 ở một khoa có thể trống nếu khoa đó không phát sinh mời/thỉnh giảng; không thêm phân công giả chỉ để lấp mọi ô. Mỗi học kỳ có dữ liệu minh họa cho cả năm loại biểu mẫu trên toàn bộ 15 khoa.

Ngân sách tìm kiếm là 60 giây, tối đa ba khởi tạo; audit và xuất file nằm ngoài thời gian tìm kiếm. Seed khác nhau và các thay đổi ngày/tuần tạo thành những đầu vào khác nhau. Thực nghiệm này xác nhận quy trình với 20 trường hợp mô phỏng, không chứng minh thuật toán tối ưu toàn cục hoặc hiệu quả trên dữ liệu thật của trường.

## Tái tạo

```powershell
.venv/Scripts/python.exe analysis/prepare_report_examples.py --initialize --limit 20
```

Lệnh từ chối ghi đè CSDL staging đã tồn tại. Khi một lần chạy bị gián đoạn, bỏ `--initialize` để tiếp tục các bộ chưa hoàn tất. Bộ đã kiểm chứng được giữ nguyên. Tham số `--retry-index` chỉ dùng để kiểm tra lại một mẫu staging chưa duyệt; không áp dụng cho kết quả đã khóa.

## Chạy khi báo cáo

Khởi động cả web và worker bằng `./start_report_demo.ps1`. Giữ hai tiến trình hoạt động trong khi trình diễn; thông tin tiến trình và nhật ký nằm trong `outputs/bao_cao_20_mau/server/`.

1. Mở trang **Xếp lịch tự động**, chọn **Học kỳ 2 – Năm học 2026–2027**.
2. Tải đúng ba file trong `samples/bao_cao_21_hoc_ky/21_2026-2027_HK2/`.
3. Nhấn chạy; worker phải hoạt động. Xem kết quả chờ duyệt và mức đáp ứng nguyện vọng.
4. Kiểm tra kế hoạch, duyệt lịch, mở thời khóa biểu từng khoa rồi xuất bộ biểu mẫu.

Không tải file của học kỳ khác vào HK2. Các học kỳ 1–20 đã khóa để tránh thay kết quả minh họa trong lúc báo cáo. Có thể tạo học kỳ khác qua giao diện nếu cần thử thêm.
