# 21 bộ đầu vào phục vụ báo cáo

Mỗi thư mục có đúng ba workbook để tải lên giao diện: `courses.xlsx` (học phần, nhóm và buổi yêu cầu), `rooms.xlsx` (phòng), `lecturers.xlsx` (giảng viên và chuyên môn). Không tải `thong_tin.json` lên giao diện.

- Bộ 01–20: đã chạy, kiểm chứng, duyệt và khóa trong CSDL demo. Kết quả nằm trong `outputs/bao_cao_20_mau/`.
- Bộ 21: `21_2026-2027_HK2/`, 480 buổi, đủ 15 khoa. Chọn **Học kỳ 2 - Năm học 2026 - 2027** trên giao diện rồi tải ba workbook của thư mục này để chạy khi báo cáo.
- `manifest.json` tổng hợp thông tin; `thong_tin.json` trong từng thư mục ghi ngày học kỳ, seed, số buổi và nguồn.

Các tên khoa, môn, mã môn và phòng được tham chiếu từ bộ SGU công khai đã đối chiếu. Các học kỳ quá khứ và phân công đều là **mô phỏng**, không phải lịch thật của các năm tương ứng. Giảng viên dùng tên hư cấu tự nhiên, mã MPGV; không sử dụng danh tính từ ảnh biểu mẫu nội bộ.

Ngày bắt đầu/kết thúc là mốc mô phỏng của 16 tuần. Tên và mã lớp đã dịch theo năm học. Hệ số 1, số tiết thực tế, công tác và hoạt động ngoài trường là dữ liệu kiểm thử, không thay cho quy định nội bộ.

Nguyện vọng không phải file thứ tư: chúng được lưu trong chức năng nguyện vọng của hệ thống. Bộ demo đã chuẩn bị nguyện vọng cho học kỳ tiếp theo, để thuật toán sử dụng ngay khi chạy.

Khởi động cả web và worker bằng `./start_report_demo.ps1` từ thư mục dự án. Tài khoản, mật khẩu và phạm vi phân quyền hiện có được giữ; các tài khoản giảng viên demo được liên kết với hồ sơ hư cấu cùng khoa có lịch mới.

Chi tiết phương pháp và giới hạn: `docs/bo_mau_bao_cao_20_hoc_ky.md`.
