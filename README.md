# Hệ thống quản lý và phân công giảng dạy SGU (đề tài nghiên cứu)

Mã nguồn phục vụ đề tài xây dựng hệ thống hỗ trợ phân công giảng dạy và xếp thời khóa biểu cho các khoa Trường Đại học Sài Gòn. Quản trị viên chọn học kỳ, tải ba tệp Excel học phần, phòng học và giảng viên, rồi chạy xếp lịch tự động. Kết quả được kiểm tra, rà soát, phê duyệt và xuất Excel; giảng viên có thể xem lịch và gửi nguyện vọng.

## Bắt đầu

Xem [hướng dẫn backend](backend/README.md) để cài đặt, chạy Django và worker xếp lịch. [Quy cách ba tệp Excel](docs/luong_xep_lich_tu_dong.md) mô tả dữ liệu đầu vào. [Bản chốt phục vụ báo cáo](docs/ban_dong_bang_bao_cao_2026-10-13.md) ghi phiên bản kiểm thử và giới hạn hiện tại.

## Phạm vi dữ liệu

`samples/` chứa dữ liệu **giả lập** với seed cố định để tái hiện kiểm thử. Dữ liệu ITC 2019 gốc trong `data/`, cơ sở dữ liệu SQLite, môi trường Python và các kết quả sinh ra trong `outputs/` không được đưa vào Git. Có thể tái tạo dữ liệu và kết quả theo [hướng dẫn kiểm thử](docs/du_lieu_gia_lap_va_kiem_thu.md).

Để trình diễn bằng thông tin đã công bố của SGU, dùng [bộ chuyển đổi PDF công khai sang ba workbook](docs/du_lieu_sgu_cong_khai.md). Mỗi bộ có `provenance.json` phân biệt trường lấy từ nguồn và giả định phục vụ bộ giải. Giao diện web dùng phong cách tham khảo cổng đào tạo SGU với bố cục riêng cho admin và giảng viên.

Hệ thống đã bổ sung kế hoạch, phân công và bộ xuất Mẫu 1–5 theo cấu trúc các ảnh biểu mẫu được cung cấp; xem [phạm vi đối chiếu](docs/quy_trinh_bieu_mau_2026.md). Những trường không có căn cứ quy đổi không được tự suy diễn.

Bộ phục vụ báo cáo mới gồm [20 học kỳ có kết quả và một học kỳ dành để chạy trực tiếp](docs/bo_mau_bao_cao_20_hoc_ky.md). Đầu vào ở `samples/bao_cao_21_hoc_ky`, kết quả ở `outputs/bao_cao_20_mau`. Khởi động cả web và worker bằng `./start_report_demo.ps1`.
