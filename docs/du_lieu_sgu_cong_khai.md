# Bộ dữ liệu trình diễn từ nguồn công khai SGU

## Nguồn và phạm vi

- [Danh sách đơn vị SGU](https://www.sgu.edu.vn/danh-sach-cac-don-vi/): tên 15 khoa. Mã `SGU_DEMO_K*` do đề tài đặt, không phải mã khoa chính thức.
- [Sổ tay đăng ký môn học HK1 2026–2027](https://daotao.sgu.edu.vn/index.php/thong-bao/so-tay-dang-ki-mon-hoc/so-tay-dang-ki-mon-hoc-hk1-nh-2026-2027): liên kết 43 PDF theo ngành và một PDF môn chung. Các PDF là ảnh chụp lịch **đã công bố**, không phải dữ liệu đầu vào nội bộ để trường lập lịch.
- Mỗi PDF được lưu cùng URL và SHA-256 trong `outputs/sgu_public_sources/source_manifest.json`. Mỗi buổi đưa vào bộ trình diễn có PDF, trang, STT và giá trị tuần/lớp gốc trong `provenance.json` của bộ đó.

## Tạo ba workbook

Cài `backend/requirements.txt`, sau đó từ thư mục gốc chạy:

```powershell
& .\.venv\Scripts\python.exe analysis\sgu_public_demo.py --fetch --programs DCT --output-dir outputs\sgu_public_demo_DCT
& .\.venv\Scripts\python.exe analysis\sgu_public_demo.py --programs ALL --output-dir outputs\sgu_public_schoolwide
& .\.venv\Scripts\python.exe analysis\sgu_public_demo.py --programs COMMON --output-dir outputs\sgu_public_common
```

`--fetch` chỉ tải các liên kết PDF nằm trên trang SGU nêu trên. Các lần sau dùng tệp đã tải để có kết quả tái hiện. Mỗi thư mục kết quả có `courses.xlsx`, `rooms.xlsx`, `lecturers.xlsx` theo đúng mẫu nhập ba file của hệ thống và `provenance.json` giải thích nguồn, thống kê cùng giả định. Có thể chọn một hoặc nhiều mã ngành, ví dụ `--programs DCT,DKP`. `ALL` tạo bộ ngành toàn trường; `COMMON` tách riêng vì gộp vào một file với `ALL` vượt giới hạn 6.000 dòng của file Học phần. Hai bộ có thể chia sẻ học phần/phòng/giảng viên, nên không được nối workbook bằng cách ghép dòng đơn giản.

## Ranh giới dữ liệu thật và giả định

**Lấy trực tiếp từ PDF:** mã và tên học phần, nhóm, tổ thực hành, sĩ số công bố, tên và mã viên chức giảng viên, thứ, tiết, mã phòng, lớp và chuỗi tuần in trên lịch. Danh sách tên khoa lấy từ trang đơn vị SGU. Bản xuất `source_rows` cho phép tìm lại từng dòng.

**Chỉ dùng để mô phỏng bộ giải:** quan hệ ngành–khoa, mã bộ môn, chu kỳ chương trình, loại trong CTĐT, sức chứa/loại/trạng thái phòng, trạng thái và khoa giảng viên, quan hệ đủ chuyên môn, thứ được phép xếp, thời gian không khả dụng. Sức chứa phòng là sĩ số lớn nhất từng thấy tại mã phòng đó, **không phải** sức chứa chính thức. Quan hệ giảng viên–học phần chỉ suy từ việc họ đã dạy môn trên PDF. Dấu `*` ở PDF theo ngành bị mất vị trí tuần khi trích bảng; hệ thống mô phỏng tuần 1–N theo số dấu, không tuyên bố tái hiện chính xác tuần thật. PDF môn chung không ghi số tín chỉ và lớp hành chính, nên hai trường này có giá trị mô phỏng được nêu trong manifest.

Các dòng thiếu trường tối thiểu, sĩ số quá giới hạn dữ liệu của hệ thống hoặc trùng do hai PDF ngành công bố cùng một lớp được loại khỏi workbook thử bộ giải và ghi số lượng trong manifest. **Kết quả thuật toán là lịch đề xuất mới**, không thay thế thời khóa biểu SGU đã công bố. Không dùng workbook này để phân công giảng viên hay phòng học thật.

## Kết quả kiểm tra ban đầu

Bộ CNTT (`DCT`) đọc được 220 dòng lịch, trong đó 210 buổi dùng được; tạo 36 học phần, 106 nhóm, 39 giảng viên và 57 mã phòng. Trên SQLite kiểm thử riêng, hệ thống xếp được 210/210 buổi bằng `HEURISTIC`, không có xung đột cứng sau bước kiểm tra độc lập.

Bộ 43 ngành đọc 3.870 dòng, dựng 3.189 buổi khác nhau, 1.370 nhóm và 569 học phần. Ba workbook được bộ đọc hệ thống chấp nhận, nhưng lượt xếp lịch toàn trường trả `UNKNOWN` sau khoảng hai phút vì heuristic chưa tìm được lịch khởi tạo; **không được diễn giải là vô nghiệm**. Bộ môn chung riêng đọc 601 dòng và dựng 588 buổi; hệ thống xếp được 588/588 bằng `HEURISTIC`. Số liệu chi tiết và dòng bị loại xem trong `provenance.json` tương ứng. Cần thử nghiệm tiếp hoặc bổ sung dữ liệu nguồn lực xác thực trước khi đưa ra kết luận về tính khả thi ở toàn trường.
