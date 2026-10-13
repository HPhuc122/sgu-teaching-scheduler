# Nguồn SGU trong NotebookLM và đối chiếu ban đầu

Notebook được người dùng chia sẻ: https://notebook.google.com/notebook/7eb71405-14f9-4a6d-9fec-b339a3e3e1a6?authuser=6

Truy cập ngày 12/10/2026. Notebook có 10 nguồn. Danh sách dưới đây là tên nguồn hiển thị trong NotebookLM; nội dung mới được kiểm tra trực tiếp đối với nguồn thời khóa biểu. Không coi phần tóm tắt tự động của NotebookLM là quy định chính thức.

| Nguồn trong notebook | Mức liên quan đến hệ thống |
| --- | --- |
| Biểu mẫu - Khoa Giáo dục – Trường Đại học Sài Gòn | Có thể chứa biểu mẫu cần đối chiếu |
| Biểu mẫu - Nghiên cứu khoa học - Phòng Quản lý Khoa học - Trường Đại học Sài Gòn | Ngoài phạm vi xếp lịch chính |
| Các biểu mẫu khác - Đại học Sài Gòn | Cần kiểm tra |
| Chương trình đào tạo ngành Quốc tế học - Khoa Văn hoá và Du lịch | Tham khảo cấu trúc học phần |
| Chương trình đào tạo ngành Sư phạm Toán | Tham khảo cấu trúc học phần |
| Lễ công bố viên chức phụ trách Khoa Giáo dục Chính trị | Ngoài phạm vi xếp lịch chính |
| Mẫu in X5110AB.006 - Quản lý kế hoạch giảng dạy - Thời khóa biểu đăng ký môn học | Đã kiểm tra; mẫu đầu ra thời khóa biểu |
| Quy trình, Biểu mẫu - Phòng Đào tạo - Trường Đại học Sài Gòn | Cần kiểm tra để xác định quy trình chính thức |
| Quyết định 3183/QĐ-ĐHSG ngày 14/11/2025 sửa đổi Quy chế đào tạo | Cần kiểm tra điều khoản liên quan |
| Tài liệu Khoa Toán - Ứng dụng | Cần xác định loại tài liệu |

## Quan sát trực tiếp từ mẫu X5110AB.006

- Mẫu hiển thị tiêu đề `Quản lý kế hoạch giảng dạy`, học kỳ, năm học, `Thời khóa biểu đăng ký môn học`, ngày bắt đầu học kỳ, ngày in và số trang. Bản trong notebook là học kỳ 1 năm học 2025–2026, bốn trang.
- Thứ tự cột: `STT`, `Mã MH`, `Tên môn học`, `Số TC`, `Sỉ số`, `Họ và tên`, `Mã viên chức`, `Nhóm`, `Tổ TH`, `Thứ`, `Tiết BĐ`, `Số tiết`, `Mã phòng`, `Tên lớp`, `Tuần học`.
- Một môn/nhóm có nhiều dòng buổi học với thứ, tiết, phòng hoặc tổ thực hành khác nhau. Một số ô lặp được để trống khi in tiếp dòng; dữ liệu nội bộ cần giữ liên kết đầy đủ thay vì lưu ô trống.
- `Tuần học` là chuỗi theo vị trí tuần. Dấu `-` thể hiện tuần không học; ký tự số thể hiện tuần học theo cách in của mẫu. Chuỗi quan sát được dài 19 vị trí, ví dụ `123456789012345----` hoặc `----------1--------`. Cần lưu tập tuần hoặc bitset có độ dài theo học kỳ, sau đó định dạng chuỗi in theo mẫu.
- `Tên lớp` có thể chứa nhiều mã lớp trong cùng ô. Cần xác định quy tắc liên kết lớp hành chính với lớp học phần.
- Đây là **mẫu thời khóa biểu đăng ký môn học**, chưa chứng minh là biểu mẫu **phân công giảng dạy hoàn chỉnh** mà người dùng yêu cầu xuất. Cần nhận mẫu phân công riêng trước khi chốt định dạng xuất.

## Sai khác với lược đồ nghiên cứu hiện có

- `GiangVien` có khóa `MaGV` nội bộ nhưng chưa có trường mã viên chức để xuất đúng mẫu.
- `LopHocPhan` có mã lớp học phần nhưng chưa tách rõ `Nhóm`, `Tổ TH` và `Tên lớp` của mẫu.
- Bản lược đồ nghiên cứu cũ dùng `PhanCong.TuanHocBitmask` với mặc định 16 tuần. Bản lược đồ SGU hiện lưu tuần theo `PhanCongTuan`, lấy giới hạn từ `HocKy.SoTuan`.
- Mã phòng in trên mẫu cần được giữ riêng với khóa phòng nội bộ.
- Quy tắc giờ bắt đầu/kết thúc trong `CauHinhTiet` hiện ghi rõ một số mốc là ước lượng; cần đối chiếu biểu giờ chính thức trước khi dùng thực tế.
- Thuật toán ITC2019 dùng dữ liệu giảng viên giả lập ở Pha B. Không được tự tạo giảng viên để vá nghiệm khi chạy trên dữ liệu thật; cần báo lớp chưa thể phân công và nguyên nhân.

## Việc còn phải xác minh với biểu mẫu gốc

1. Mẫu phân công giảng dạy chính thức: cột, nhóm dòng, chữ ký/phê duyệt, định dạng Excel/PDF và đơn vị xuất theo khoa/bộ môn/học kỳ.
2. Dữ liệu nguồn thật của giảng viên, học phần, nhóm, tổ thực hành, phòng, thời gian và lớp hành chính.
3. Quy định về định mức dạy, ưu tiên nguyện vọng, ca học, số tuần, lịch nghỉ và quyền điều chỉnh sau khi duyệt.

## Nguồn công khai chính thức tìm bổ sung

Các nguồn dưới đây nằm trên website Phòng Đào tạo hoặc Phòng Tổ chức Cán bộ của Trường Đại học Sài Gòn và được kiểm tra ngày 12/10/2026:

| Nguồn | Vai trò sử dụng |
| --- | --- |
| [Sổ tay đăng ký môn học HK1 năm học 2026–2027](https://daotao.sgu.edu.vn/index.php/thong-bao/so-tay-dang-ki-mon-hoc/so-tay-dang-ki-mon-hoc-hk1-nh-2026-2027) | Trang chính thức liên kết thời khóa biểu theo ngành |
| [Thời khóa biểu Công nghệ thông tin HK1 2026–2027](https://daotao.sgu.edu.vn/images/pdf/sotaydkmh/261/DCT.pdf) | Mẫu X5110AB.006, dữ liệu đầu ra mới cho khoa CNTT; 9 trang |
| [Thời khóa biểu Kỹ thuật phần mềm HK1 2026–2027](https://daotao.sgu.edu.vn/images/pdf/sotaydkmh/261/DKP.pdf) | Mẫu X5110AB.006, dữ liệu đầu ra mới cho ngành gần với đồ án; 9 trang |
| [Thời khóa biểu đăng ký môn học HK1 2025–2026](https://daotao.sgu.edu.vn/images/pdf/sotaydkmh/251/DVA.pdf) | Mẫu X5110AB.006 ở kỳ đã công bố với chuỗi tuần dạng số và dấu gạch |
| [Thời khóa biểu môn học mẫu X5010B.001](https://daotao.sgu.edu.vn/web/images/pdf/sotaydkmh/HK242/monchung.pdf) | Mẫu báo cáo theo một môn học, có mã viên chức, nhóm, tổ thực hành, phòng và thời gian học |
| [Biên chế năm học 2026–2027](https://daotao.sgu.edu.vn/images/pdf/bien-che-nam-hoc/BienCheNamHoc_2026-2027.pdf) | Mốc thời gian năm học, cần đọc trực tiếp khi cấu hình học kỳ |
| [Quyết định sửa đổi Quy chế đào tạo](https://daotao.sgu.edu.vn/index.php/van-ban/quy-che-quy-dinh/quy-che-dao-tao-dai-hoc/quyet-dinh-ve-viec-sua-doi-bo-sung-mot-so-dieu-cua-quy-che-dao-tao-trinh-do-dai-hoc-truong-dai-hoc-sai-gon) | Nguồn quy định; cần đọc văn bản đính kèm trước khi mã hóa ràng buộc nghiệp vụ |
| [Thủ tục công nhận hoàn thành tập sự](https://tccb.sgu.edu.vn/quanly/web/quy_trinh/118) | Xác nhận trường có sử dụng bảng phân công công tác giảng dạy trong hồ sơ viên chức, nhưng trang không cung cấp chính mẫu bảng đó |

**Lưu ý phiên bản:** Các PDF HK1 2026–2027 hiển thị `Tuần học` bằng dấu `*` ở nhiều dòng, còn PDF 2025–2026 hiển thị dãy chữ số và dấu `-`. Vì vậy không được cố định một cách in tuần học duy nhất trong cơ sở dữ liệu; cần lưu tuần dưới dạng dữ liệu có cấu trúc và chọn bộ định dạng theo loại báo cáo/phiên bản mẫu.

**Giới hạn nguồn:** Chưa tìm thấy bản công khai chính thức của bảng *phân công giảng dạy hoàn chỉnh* theo khoa trên website trường. Các mẫu X5110AB.006 và X5010B.001 là mẫu thời khóa biểu, có thể dùng để thiết kế dữ liệu và báo cáo tương ứng, nhưng không nên đổi tên chúng thành biểu mẫu phân công giảng dạy.
