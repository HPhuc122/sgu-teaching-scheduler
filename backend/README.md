# Backend quản lý và phân công giảng dạy SGU

[Bản chốt dùng cho báo cáo và hướng dẫn tái hiện](../docs/ban_dong_bang_bao_cao_2026-10-13.md).

Đây là backend Django của hệ thống. Luồng chính: admin chọn học kỳ, tải ba file Học phần, Phòng học và Giảng viên, rồi chạy xếp lịch tự động. Hệ thống tạo lịch chờ duyệt, admin xem/duyệt và xuất Excel; giảng viên xem lịch đã duyệt và gửi nguyện vọng. Các API và màn hình nhập lịch từng buổi vẫn phục vụ điều chỉnh ngoại lệ.

## Chạy cục bộ

Từ thư mục gốc `D:\uctp_project`:

```powershell
& .\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
& .\.venv\Scripts\python.exe backend\manage.py migrate
& .\.venv\Scripts\python.exe backend\manage.py createsuperuser
& .\.venv\Scripts\python.exe backend\manage.py runserver
```

Mở **terminal thứ hai** và chạy worker xếp lịch (giữ tiến trình này hoạt động):

```powershell
& .\.venv\Scripts\python.exe backend\manage.py process_auto_schedule
```

Trong triển khai thực tế, chạy worker như một dịch vụ riêng có tự khởi động lại. Có thể dùng `process_auto_schedule --once` để xử lý tối đa một lần chạy. Nếu worker bị dừng khi một lần chạy mang trạng thái `RUNNING`, chỉ sau khi xác nhận worker cũ đã dừng, đưa lần chạy đó vào hàng đợi lại bằng `process_auto_schedule --recover-run <mã_lần_chạy>`.

Mặc định dùng SQLite để phát triển. Mở `http://127.0.0.1:8000/admin/` để đăng nhập và nhập danh mục. Tạo tài khoản giảng viên bằng Django Admin rồi liên kết ở trường `user` trong hồ sơ giảng viên. Giảng viên đăng nhập tại `http://127.0.0.1:8000/login/` và xem trang cá nhân ở `/portal/`. Chỉ tài khoản `is_staff=True` được gọi API quản trị. Chưa có dữ liệu giảng viên thật hoặc tài khoản mẫu được tạo sẵn.

## Xếp lịch tự động từ ba file Excel

Admin mở `/admin/auto-schedule/`, tải ba mẫu tại màn hình, điền dữ liệu và tải cả ba file lên trong một lần. Chọn học kỳ đã cấu hình số tuần/tiết học rồi nhấn **Chạy xếp lịch**. Yêu cầu được đưa vào hàng đợi; trang kết quả tự làm mới khi đang chờ hoặc đang chạy. Worker tự chọn giảng viên có chuyên môn, thứ/tiết và phòng phù hợp, rồi lưu kết quả chờ duyệt. Trang Rà soát lịch hiển thị mức đáp ứng từng nguyện vọng giảng viên của lần chạy để admin xem trước khi duyệt. Mỗi học kỳ chỉ có một lần chạy đang hoạt động. Ba file được giữ tạm trong cơ sở dữ liệu đến khi xử lý xong rồi xóa khỏi hàng đợi. Lỗi nhập liệu được liệt kê theo file, sheet và dòng ngay trên màn hình tải hoặc trang kết quả worker; một lần chạy lỗi không ghi danh mục/lịch dở dang. File Học phần có thêm sheet `Khoa`, `BoMon` và `BuoiHocYeuCau` để mô tả đủ số buổi, số tiết, tuần học và thứ cho phép của từng nhóm. File Phòng học và Giảng viên có sheet thời gian không khả dụng. [Quy cách ba file và giới hạn bộ giải](../docs/luong_xep_lich_tu_dong.md).

Có thể tạo ba file giả lập với seed cố định và chạy thử trên SQLite riêng theo [hướng dẫn kiểm thử tải](../docs/du_lieu_gia_lap_va_kiem_thu.md). Dưới 500 buổi, CP-SAT chạy tối đa 30 giây; nếu bộ giải chưa tìm được nghiệm nhưng lịch khởi tạo hợp lệ, hệ thống trả `HEURISTIC`. Từ 500 buổi, hệ thống dùng trực tiếp lịch khởi tạo, kiểm tra độc lập các ràng buộc trước khi lưu và duyệt. Giới hạn luồng ba file là 6.000 dòng dữ liệu cộng gộp các sheet và 10 MB mỗi file.

## Nhập danh mục hoặc lịch riêng để điều chỉnh ngoại lệ

Các màn hình nhập riêng trong `/admin/` vẫn có thể dùng để sửa danh mục hoặc nhập một lịch đặc biệt. Chúng dùng mẫu cũ và không phải bước bắt buộc trước khi chạy luồng tự động. Mỗi file được xem trước và kiểm tra lại trong giao dịch khi xác nhận. Nhập lại cùng mã sẽ cập nhật, không tạo bản sao; mục vắng trong file không bị xóa. Giới hạn 1000 dòng dữ liệu và 2 MB/file. Mã phải là **ô văn bản** trong Excel để giữ số 0 đầu.

| Workbook | Sheet và cột theo thứ tự |
| --- | --- |
| Học phần `/admin/import-catalog/courses/` | `ChuongTrinh`: `ma_nganh_ctdt`, `ten_chuong_trinh`, `ma_khoa`, `chu_ky_ctdt` |
| | `HocPhan`: `ma_mon_hoc`, `ten_mon_hoc`, `so_tin_chi`, `ma_bo_mon_phu_trach`, `loai_mon` (`CHUNG`/`CHUYEN_NGANH`) |
| | `HocPhanChuongTrinh`: `ma_mon_hoc`, `ma_nganh_ctdt`, `chu_ky_ctdt`, `loai_trong_ctdt` (`BAT_BUOC`/`TU_CHON`) |
| | `NhomHocPhan`: `ma_mon_hoc`, `hoc_ky`, `nhom`, `to_th`, `si_so_du_kien`, `ten_lop` (nhiều lớp cách bằng `;`) |
| Phòng học `/admin/import-catalog/rooms/` | `PhongHoc`: `ma_phong`, `ma_toa_nha`, `ten_toa_nha`, `ten_phong`, `suc_chua`, `loai_phong`, `trang_thai` |
| Giảng viên `/admin/import-catalog/lecturers/` | `GiangVien`: `ma_vien_chuc`, `ho_ten`, `email`, `ma_khoa`, `ma_bo_mon`, `trang_thai` (`email` có thể trống) |
| | `GiangVienHocPhan`: `ma_vien_chuc`, `ma_mon_hoc` (thêm chuyên môn, không xóa liên kết cũ) |

Admin chọn học kỳ khi nhập workbook Học phần. Giá trị `hoc_ky` trong sheet `NhomHocPhan` phải khớp tên học kỳ đã chọn. Mã khoa và bộ môn cần tồn tại trước; `ma_bo_mon` là mã riêng của bộ môn, không phải khóa số nội bộ. Các giá trị loại môn, loại phòng, trạng thái và phân loại CTĐT là **quy ước hệ thống đề xuất**, chưa xác minh là quy ước SGU. Xem [đối chiếu nguồn SGU](../docs/doi_chieu_quy_trinh_sgu_2026.md).

## Nhập lịch ngoại lệ từ Excel

Admin mở `/admin/`, chọn **Chọn học kỳ và nhập file Excel** hoặc truy cập `/admin/import-schedule/`. Tải mẫu `.xlsx`, điền mỗi buổi dạy trên một dòng rồi xem trước. Các cột là `ma_mon_hoc`, `nhom`, `to_th`, `ma_vien_chuc`, `ma_phong`, `thu`, `tiet_bat_dau`, `so_tiet`, `tuan_hoc`, `dia_diem_khac`. Cặp mã môn + nhóm + tổ TH xác định nhóm đã mở trong học kỳ; không dùng mã lớp ghép giả định `841021.01`. `tuan_hoc` dùng dạng `1-10,12,14-16`; `thu` từ 2 đến 8. Có thể dùng `dia_diem_khac` thay cho `ma_phong`, nhưng không điền cả hai.

Các mã môn, nhóm, giảng viên, phòng và cấu hình tiết **phải tồn tại trong danh mục** trước khi nhập; giảng viên phải được gắn chuyên môn dạy học phần. Bản xem trước kiểm tra từng dòng và xung đột với lịch đang lưu cũng như giữa các dòng Excel. Nếu có lỗi, hệ thống không cho xác nhận; sửa file rồi tải lại. Khi xác nhận, toàn bộ file được kiểm tra lại và lưu trong một giao dịch, trạng thái `ChoDuyet`, nguồn `Excel`. Giới hạn 500 dòng và 2 MB mỗi lần. Mẫu này là định dạng nhập của hệ thống dựa trên các trường đã đối chiếu từ thời khóa biểu công khai SGU, **chưa phải biểu mẫu phân công nội bộ đã xác minh**.

## Rà soát và duyệt lịch

Tài khoản quản trị mở `/admin/review-schedules/` từ trang `/admin/`. Chọn học kỳ, lọc theo môn, nhóm, giảng viên, phòng hoặc trạng thái, rồi mở từng buổi để sửa giảng viên, phòng/địa điểm, thứ, tiết và tuần. Màn hình hiển thị tối đa 50 buổi mỗi trang; có thể chọn các buổi `ChoDuyet` trên trang hiện tại để duyệt cùng lúc (tối đa 100 buổi mỗi lần qua dịch vụ). Trước khi ghi, hệ thống kiểm tra lại học kỳ, chuyên môn giảng viên, trạng thái phòng và xung đột lịch. Nếu một buổi không hợp lệ, cả lượt duyệt không được lưu. Học kỳ đã khóa không thể sửa hoặc duyệt.

Khi duyệt, hệ thống lưu tài khoản người duyệt và thời điểm duyệt. Sửa nội dung một buổi đã duyệt sẽ chuyển buổi đó về `ChoDuyet`, xóa thông tin duyệt cũ; giảng viên chỉ nhìn thấy lại sau khi được duyệt lần nữa. Các lịch `DaDuyet` đã tồn tại trước migration có thể không có người duyệt hoặc thời điểm duyệt vì hệ thống không suy đoán dữ liệu lịch sử. Đây là **quy trình phần mềm đề xuất**, chưa được xác nhận là quy trình nội bộ chính thức của SGU.

## Xuất Excel phân công giảng dạy

Admin mở `/admin/export-assignments/`, chọn học kỳ và **khoa quản lý giảng viên**, xem trước rồi tải file `.xlsx`. File chỉ gồm buổi `DaDuyet` của giảng viên thuộc khoa đã chọn, kể cả khi môn học do khoa khác phụ trách. Sheet `PhanCong` ghi mỗi buổi trên một dòng với các trường tương ứng thời khóa biểu công khai SGU: mã/tên môn, tín chỉ, sĩ số dự kiến, giảng viên và mã viên chức, nhóm, tổ TH, thứ, tiết, phòng/địa điểm, lớp và tuần học. Sheet `TongHopGV` cộng số dòng phân công và tổng tiết theo lịch của mỗi giảng viên; `ThongTin` ghi học kỳ, phạm vi và giới hạn của mẫu. **Tổng tiết theo lịch** bằng số tiết mỗi buổi nhân số tuần được xếp, chưa phải giờ giảng quy đổi. File là mẫu xuất đề xuất, chưa phải biểu mẫu phân công nội bộ chính thức của SGU.

Trước khi tải, trang xuất đối chiếu **toàn học kỳ** với `ma_buoi` trong các file Học phần của lần chạy mới nhất cho từng nhóm. Trang chỉ rõ buổi yêu cầu đã duyệt, còn chờ, bị thiếu hoặc trùng mã; đồng thời nêu các nhóm chưa có danh sách buổi yêu cầu và mọi buổi còn chờ duyệt. Buổi thiếu giảng viên chưa thể quy về khoa, nên kiểm tra phải xét toàn học kỳ. Vẫn có thể tải file để rà soát khi chưa đủ, nhưng sheet `ThongTin` ghi rõ **chưa xác nhận đầy đủ**; lịch cũ không có mã buổi yêu cầu không được tự nhận là hoàn chỉnh.

## Thời khóa biểu giảng viên theo khoa

Admin mở `/admin/faculty-timetable/`, chọn học kỳ, khoa quản lý giảng viên và tuần học. Có thể lọc một giảng viên; nếu không lọc, màn hình hiển thị tối đa 10 giảng viên mỗi trang và có nút chuyển trang. Lưới theo thứ và tiết chỉ hiển thị lịch `DaDuyet` của tuần đã chọn; một buổi nhiều tiết được đánh dấu từ tiết bắt đầu đến tiết kết thúc. Mỗi buổi có liên kết xem/sửa lịch ở màn hình rà soát. Giảng viên thường không có quyền mở màn hình của khoa.

## API hiện có

| Đường dẫn | Quyền | Tác dụng |
| --- | --- | --- |
| `/api/faculties/`, `/api/departments/` | Admin | Khoa, bộ môn |
| `/api/lecturers/`, `/api/courses/`, `/api/qualifications/` | Admin | Giảng viên, học phần, chuyên môn được phép dạy |
| `/api/programs/`, `/api/course-programs/` | Admin | Chương trình đào tạo và liên kết học phần |
| `/api/semesters/`, `/api/periods/`, `/api/buildings/`, `/api/rooms/` | Admin | Học kỳ, tiết, tòa và phòng |
| `/api/course-groups/`, `/api/cohorts/`, `/api/group-cohorts/` | Admin | Nhóm học phần, lớp hành chính và liên kết |
| `/api/schedules/` | Admin | Tạo/sửa/xem buổi dạy; lọc `?semester=<id>&lecturer=<id>` |
| `/api/me/` | Giảng viên | Hồ sơ cá nhân |
| `/api/me/schedule/` | Giảng viên | Lịch đã duyệt; lọc `?semester=<id>` |
| `/api/me/preferences/` | Giảng viên | Xem và gửi nguyện vọng theo học kỳ |

Trang `/portal/` cung cấp giao diện đầu tiên cho giảng viên; `/admin/` quản lý danh mục và liên kết đến màn hình rà soát lịch. Quản trị viên cũng có thể tạo/sửa buổi dạy qua API `/api/schedules/`.

Mỗi buổi trong `/api/schedules/` nhận `group`, `lecturer`, `room` hoặc `other_location`, `day`, `start_period`, `period_count`, `status` và danh sách `weeks`. Nếu trùng tài nguyên, API trả **409** cùng loại xung đột, mã buổi hiện có và các tuần giao nhau. Dữ liệu sai hoặc vượt giới hạn học kỳ trả **400**. API dùng xác thực phiên Django và CSRF cho thao tác ghi.

## SQL Server

Tạo **CSDL trống** trước. Đặt các biến môi trường `UCTP_DB_ENGINE=mssql`, `UCTP_DB_NAME`, `UCTP_DB_HOST`, `UCTP_DB_USER`, `UCTP_DB_PASSWORD`, tùy chọn `UCTP_DB_PORT`, `UCTP_ODBC_DRIVER`, `UCTP_SECRET_KEY`, rồi chạy `migrate`. Trình điều khiển mặc định là ODBC Driver 17. Backend SQL Server chưa được kiểm thử trực tiếp vì phiên làm việc này không có kết nối máy chủ.

Migration Django trong `school/migrations` là nguồn triển khai cho backend. [schema.sql](../database/schema.sql) là bản thiết kế tham chiếu của giai đoạn nghiên cứu; **không chạy đồng thời hai cách tạo bảng trên cùng CSDL**.

## Kiểm thử

```powershell
& .\.venv\Scripts\python.exe backend\manage.py test school
& .\.venv\Scripts\python.exe -m unittest discover -s tests
```

Luồng viết lịch khóa bản ghi học kỳ trong giao dịch trước khi kiểm tra xung đột. Cần chạy kiểm thử đồng thời trên SQL Server thật trước khi dùng nhiều người, đặc biệt với cấu hình cách ly giao dịch của máy chủ.
