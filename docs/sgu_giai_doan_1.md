# Nền dữ liệu và kiểm tra lịch SGU giai đoạn 1

**Ghi chép lịch sử:** Tài liệu này mô tả trạng thái nghiên cứu ban đầu, không phải trạng thái hệ thống tại bản chốt 13/10/2026. Xem [tài liệu bản chốt](ban_dong_bang_bao_cao_2026-10-13.md) và [README backend](../backend/README.md) để biết luồng đã tích hợp.

Giai đoạn này chuẩn bị dữ liệu cho hệ thống phân công và xuất thời khóa biểu, dựa trên mẫu thời khóa biểu công khai X5110AB.006 của Phòng Đào tạo SGU. Mẫu bảng phân công giảng dạy nội bộ chưa được xác minh nên chưa có thiết kế trình bày cuối cùng cho báo cáo đó.

## Ánh xạ cột mẫu

| Cột SGU | Dữ liệu hệ thống |
| --- | --- |
| Mã MH, Tên môn học, Số TC | `HocPhan.MaHocPhanCode`, `TenHocPhan`, `SoTinChi` |
| Sỉ số | `LopHocPhan.SiSoToiDa` ở giai đoạn lập kế hoạch; sau đăng ký cần bổ sung sĩ số thực tế riêng |
| Họ và tên, Mã viên chức | `GiangVien.HoTen`, `MaVienChuc` |
| Nhóm, Tổ TH | `LopHocPhan.Nhom`, `ToTH` |
| Thứ, Tiết BĐ, Số tiết | `PhanCong.Thu`, `MaTietBatDau`, `SoTiet` |
| Mã phòng | `PhongHoc.MaPhongCode`, hoặc `PhanCong.DiaDiemKhac` cho địa điểm không nằm trong danh mục phòng |
| Tên lớp | Một hoặc nhiều `LopHanhChinh.TenLop` liên kết qua `LopHocPhanLopHanhChinh` |
| Tuần học | Các dòng `PhanCongTuan`; hàm xuất sẽ định dạng theo phiên bản báo cáo |

## Quy tắc kiểm tra đã cài

`scheduling.validation` kiểm tra tuần không vượt số tuần học kỳ, thứ 2–8, tiết học không vượt tiết cuối ngày, và xung đột khi **cùng học kỳ, cùng thứ, giao nhau về tiết và có ít nhất một tuần chung**. Khi đó báo riêng trùng giảng viên, phòng, lớp hành chính và nhóm học phần. Buổi học liền tiết hoặc chỉ học ở các tuần khác nhau được phép.

Hàm này dùng cho kiểm tra một thay đổi thủ công (`conflicts_for_candidate`) hoặc toàn bộ phương án (`detect_conflicts`). Khi nối vào API, cần đọc/khóa lịch liên quan và kiểm tra trong cùng giao dịch ghi CSDL để hai thao tác đồng thời không vượt qua kiểm tra.

## Giới hạn và bước tích hợp

- `database/schema.sql` là script **tạo CSDL mới**, chưa phải migration cho CSDL đang có dữ liệu. Cần migration riêng nếu đã triển khai bản cũ.
- CSDL có trigger chặn tuần lớn hơn `HocKy.SoTuan`; một buổi được xem là hợp lệ để công bố chỉ khi có ít nhất một dòng `PhanCongTuan`. Quy tắc này phải được kiểm tra ở tầng nghiệp vụ trước khi duyệt.
- Chưa thể xác nhận dịch vụ SQL Server trong môi trường hiện tại, nên script DDL chưa được thực thi trên máy chủ. Bộ kiểm tra Python được kiểm thử bằng `python -m unittest discover -s tests -v`.
- Bộ kiểm tra đã được nối vào API Django tại `backend/`. Thuật toán ITC2019 và bộ xuất biểu mẫu vẫn chưa nối vào backend. Giao diện giảng viên ban đầu có tại `/portal/`; giao diện xếp lịch riêng cho quản trị viên chưa có.
- Các hàm trong `stage_b_teacher.py` sinh giảng viên giả chỉ dành cho benchmark ITC2019. Tích hợp thực tế phải báo thiếu nguồn lực thay vì tạo người dạy không có thật.
