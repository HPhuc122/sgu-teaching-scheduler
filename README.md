# Hệ thống quản lý và phân công giảng dạy SGU (đề tài nghiên cứu)

Mã nguồn phục vụ đề tài xây dựng hệ thống hỗ trợ phân công giảng dạy và xếp thời khóa biểu cho các khoa Trường Đại học Sài Gòn. Quản trị viên chọn học kỳ, tải ba tệp Excel học phần, phòng học và giảng viên, rồi chạy xếp lịch tự động. Kết quả được kiểm tra, rà soát, phê duyệt và xuất Excel; giảng viên có thể xem lịch và gửi nguyện vọng.

## Bắt đầu

Xem [hướng dẫn backend](backend/README.md) để cài đặt, chạy Django và worker xếp lịch. [Quy cách ba tệp Excel](docs/luong_xep_lich_tu_dong.md) mô tả dữ liệu đầu vào. [Bản chốt phục vụ báo cáo](docs/ban_dong_bang_bao_cao_2026-10-13.md) ghi phiên bản kiểm thử và giới hạn hiện tại.

## Phạm vi dữ liệu

`samples/` chứa dữ liệu **giả lập** với seed cố định để tái hiện kiểm thử. Dữ liệu ITC 2019 gốc trong `data/`, cơ sở dữ liệu SQLite, môi trường Python và các kết quả sinh ra trong `outputs/` không được đưa vào Git. Có thể tái tạo dữ liệu và kết quả theo [hướng dẫn kiểm thử](docs/du_lieu_gia_lap_va_kiem_thu.md).

Các quy trình nghiệp vụ và mẫu Excel xuất hiện tại là thiết kế của đề tài dựa trên nguồn công khai; chưa được xác nhận là biểu mẫu phân công nội bộ chính thức của trường.
