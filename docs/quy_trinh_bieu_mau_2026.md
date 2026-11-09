# Điều chỉnh hệ thống theo cấu trúc biểu mẫu được cung cấp

## Nguồn và phạm vi

Bảy ảnh trong `docs/DACN_Biểu mẫu` thể hiện năm loại biểu mẫu. Ảnh 1–3 là Mẫu 1 cho HK1, HK2, HK3; ảnh 4–7 lần lượt là Mẫu 2–5. Việc khảo sát chỉ trích tên biểu mẫu và cấu trúc trường. Không sao chép mã viên chức, tên, năm sinh, nơi công tác hoặc dòng phân công cá nhân trong ảnh vào dữ liệu thử nghiệm.

Ảnh cung cấp căn cứ về cấu trúc kế hoạch và sản phẩm công việc. Ảnh không tự chứng minh thứ tự lập, thẩm quyền duyệt, công thức quy đổi hoặc quy trình ban hành trên toàn trường. Luồng dưới đây là thiết kế phần mềm dựa trên cấu trúc khảo sát; các giới hạn này dành cho tài liệu nghiên cứu, không hiển thị thành cảnh báo quy trình trên giao diện.

## Luồng đã triển khai

1. Chọn năm học, học kỳ và học kỳ số 1, 2 hoặc 3.
2. Tải ba workbook Học phần, Phòng học, Giảng viên. Chọn lưu kế hoạch để xem trước thêm/cập nhật/bản ghi vắng, rồi xác nhận áp dụng; có thể chạy xếp lịch ngay nếu không cần loại bỏ bản ghi cũ.
3. Kiểm tra danh mục, nhóm mở, buổi yêu cầu, phân công cố định, loại buổi, metadata kế hoạch, công tác khác và hoạt động ngoài trường.
4. Lưu `GroupTeachingPlan` và `TeachingAssignment` riêng với `ScheduleEntry`. Kế hoạch có thể tồn tại khi chưa có lịch phòng/thời gian hoặc khi chưa tìm được lịch khả thi.
5. Giữ giảng viên được chỉ định; các buổi còn trống được thuật toán chọn trong danh sách đủ chuyên môn. Lưu người được chọn vào phân công kế hoạch sau khi có nghiệm hợp lệ.
6. Xếp phòng, thứ và tiết; kiểm tra nguyện vọng và thời gian lớp tham gia hoạt động ngoài trường. Ràng buộc được áp dụng trong khởi tạo, CP-SAT, Great Deluge, audit độc lập, sửa lịch và duyệt lịch.
7. Rà soát kế hoạch và đối chiếu số tiết, người dạy, tuần, tình trạng duyệt với lịch. Xếp lại từ kế hoạch đã lưu phải giữ các khoảng phòng/giảng viên không khả dụng của đầu vào.
8. Xuất bộ biểu mẫu kế hoạch theo khoa và năm học hoặc học kỳ. HK1–HK3 có sheet riêng; Mẫu 2 tổng hợp cả giảng viên cơ hữu của khoa giảng dạy cho đơn vị khác mà người dùng có quyền xem.

## Quy cách bổ sung cho ba workbook

Các cột mới đặt sau các cột cũ. Workbook cũ thiếu các cột/sheet bổ sung vẫn được đọc. Tham khảo mẫu tải trực tiếp từ hệ thống để có đúng thứ tự.

### Học phần

- `LopHanhChinh`: `ten_lop`, `ma_bo_mon_quan_ly` xác định đơn vị quản lý lớp để phân quyền và lọc hoạt động ngoài trường theo khoa. Với dữ liệu cũ thiếu đơn vị quản lý lớp, hoạt động được hiển thị ở các khoa đang có nhóm học phần liên quan; không tự suy ra hoặc ghi đè đơn vị quản lý từ học phần môn chung.

- `BuoiHocYeuCau`: sau `thu_duoc_xep`, thêm `ma_vien_chuc_phan_cong`, `loai_buoi` (`LT`, `BT`, `TH`), `so_tiet_thuc_te`. Các trường này tùy chọn. Phân công cố định áp dụng cho từng buổi để hỗ trợ LT và TH do các giảng viên khác nhau phụ trách.
- `KeHoachMoNhom`: `ma_mon_hoc`, `nhom`, `to_th`, `hoc_ky_so`, `khoa`, `so_tiet_lt`, `so_tiet_bt`, `so_tiet_th`, `he_so_hp`, `ghi_chu`.
- `HoatDongNgoaiTruong`: `ma_hoat_dong`, `ten_lop`, `khoa`, `trinh_do`, `noi_dung`, `dia_diem`, `tu_ngay`, `den_ngay`, `so_sinh_vien`, `hoc_ky_so`. Ngày dùng ISO `YYYY-MM-DD`. Lớp phải có trong nhóm của workbook.

### Giảng viên

- `GiangVien`: sau `trang_thai`, thêm `nguon_giang_vien` (`CO_HUU` hoặc `THINH_GIANG`), `chuyen_nganh`, `hoc_vi_chuc_danh`, `don_vi_cong_tac`.
- `CongTacKhac`: `ma_vien_chuc`, `ma_cong_tac`, `noi_dung`, `loai` (`KHAC`, `CLC`), `so_tiet`.
- Phân công mời giảng được xác định theo từng khoa lập kế hoạch: người trong trường thuộc khoa khác là mời giảng; người có nguồn `THINH_GIANG` là thỉnh giảng. Một giảng viên có thể xuất hiện ở bảng cơ hữu của khoa mình và bảng mời giảng của khoa khác.

Workbook phòng giữ cấu trúc hiện có. Các bản ghi cùng khóa được cập nhật, không tạo bản sao. Nhập lại không tự xóa buổi, metadata, công tác, hoạt động hoặc liên kết lớp–nhóm vắng trong Excel. Bước xem trước liệt kê những bản ghi vắng, kể cả nhóm bị bỏ toàn bộ. Chỉ bản ghi có dấu vết do Excel tạo, còn nguyên so với lần nhập gần nhất, mới đủ điều kiện xóa khi người dùng đánh dấu đồng ý và xác nhận. Bản ghi chưa rõ nguồn, đã sửa thủ công và danh mục dùng chung được giữ lại. Dữ liệu cũ không được tự nhận là có nguồn Excel chỉ vì trùng khóa. Xem [cơ chế đồng bộ và kiểm tra trước commit](dong_bo_ke_hoach_quang1.md).

## Ý nghĩa số tiết và xuất biểu mẫu

- Tiết kế hoạch của một buổi = số tiết mỗi lần × số tuần được nhập.
- Tiết đã xếp = số tiết mỗi buổi lịch × số tuần đã lưu. Đối chiếu thêm giảng viên và tập tuần, không chỉ so tổng.
- Cột `Số tiết thực tế` trong cấu trúc biểu mẫu lấy từ giá trị được nhập rõ ràng; không suy diễn ý nghĩa quy đổi từ các con số trong ảnh. Khi thiếu thì để trống, không tự điền 0. Hệ số HP được lưu riêng, không mặc định nhân vào mọi phép tổng hợp.
- Tổng công tác của GV chỉ cộng khi có đầy đủ số tiết thực tế được khai báo cùng công tác khác/CLC; ô tổng được để trống nếu còn thiếu cơ sở số học.
- File kế hoạch có `Mau1_HK1`, `Mau1_HK2`, `Mau1_HK3`, `Mau2`, `Mau3`, `Mau4`, `Mau5`. Nếu thiếu học kỳ số, dữ liệu xuất riêng ở `Mau1_HKChuaGan` và trang kế hoạch yêu cầu bổ sung số học kỳ. Không đoán học kỳ số từ tên.
- Bố cục tái tạo các nhóm cột nhìn thấy trong ảnh, có một số cột bổ sung phục vụ đối chiếu. Đây không phải bản sao toàn bộ workbook nguồn hoặc các vùng chữ ký ngoài khung ảnh.
- Không thu thập năm sinh. Tên cột này trong biểu mẫu có thể giữ để thể hiện cấu trúc nhưng các giá trị để trống.

## Thời gian hoạt động ngoài trường

Quy ước kỹ thuật hiện hành: tuần 1 bắt đầu vào thứ Hai của tuần chứa ngày bắt đầu học kỳ. Mỗi ngày hoạt động chặn cả ngày của lớp được nhập. Một buổi định kỳ không được chọn thứ đó nếu có tuần yêu cầu giao với ngày bị chặn. Hệ thống không tự tách buổi định kỳ sang nhiều lịch bù. Đây là lựa chọn mô hình cần nêu trong báo cáo.

## Dữ liệu dùng thử

Lệnh `python backend/manage.py generate_planning_workbooks` tạo ba bộ ở `samples/ke_hoach_bieu_mau`, mỗi bộ có ba workbook, lần lượt 240, 480 và 960 buổi cho đủ 15 khoa. Tên khoa, học phần, mã môn, nhóm/lớp và mã phòng lấy từ các bộ SGU công khai đã đối chiếu. Họ tên giảng viên được đặt tự nhiên, có mã riêng `MPGV`, giữ nhất quán giữa ba bộ; toàn bộ hồ sơ nhân sự và phân công trong bộ mới là giả lập. Không dùng danh tính từ ảnh nội bộ. Hệ số 1 và các dữ liệu công tác/hoạt động là giá trị mô phỏng. Thông tin ngày và học kỳ cần chọn có trong `manifest.json`, nguồn và SHA-256 trong `hkN_nguon.json`. `--preserve-catalog` giữ thuộc tính học phần/phòng đang lưu để tương thích các lịch cũ đã duyệt.

Kế hoạch mới không tự được suy ra từ lịch cũ đã lưu. Muốn có kế hoạch trước thời khóa biểu, nhập dữ liệu đầu vào tương ứng. Những nhóm cũ chưa có hồ sơ buổi yêu cầu vẫn được báo thiếu căn cứ đối chiếu thay vì tự nhận đầy đủ.
