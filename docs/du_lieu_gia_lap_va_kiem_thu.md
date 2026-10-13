# Dữ liệu giả lập và kiểm thử tải

Các file trong `samples/synthetic_*` là dữ liệu **hư cấu**, tạo bằng seed cố định để thử hệ thống. Chúng tuân thủ ba mẫu Excel đề xuất hiện tại và không phải dữ liệu, biểu mẫu hay quy định chính thức của Đại học Sài Gòn.

## Sinh lại dữ liệu

Từ thư mục gốc dự án:

```powershell
& .\.venv\Scripts\python.exe backend\manage.py generate_sample_workbooks --output-dir samples\synthetic_80_seed42 --sessions 80 --semester-name "HK test 2026-2027" --seed 42
```

Lệnh tạo đúng `courses.xlsx`, `rooms.xlsx`, `lecturers.xlsx`. Thay `--sessions` bằng số từ 3 đến 2.500 và `--seed` để đổi phép phân bố nhóm/học phần. `--scenario constrained` giảm số phòng, giảng viên và chặn một phần sáng thứ Hai; `--scenario infeasible` tạo ba buổi cùng lớp hành chính chỉ được học thứ Hai, mỗi buổi 5 tiết, nên tổng 15 tiết vượt 13 tiết trong ngày. `--scenario varied_weeks` tạo hai buổi cho mỗi nhóm và dùng các tập tuần khác nhau (cả học kỳ, nửa đầu, nửa sau, tuần lẻ, tuần chẵn) để kiểm tra xung đột theo tuần. Bộ sinh giữ tối đa 6.000 dòng dữ liệu và 10 MB trong mỗi file. Mã giảng viên, phòng, khoa và học phần đều bắt đầu bằng `TEST_` hoặc `TEST.`; không có thông tin người thật. `CHUNG` được liên kết với nhiều chương trình, còn các môn khác liên kết với một chương trình. Đây là **giả định tạo dữ liệu thử**, không suy ra quy chế trường.

## Chạy trên SQLite tách biệt

Không dùng cơ sở dữ liệu phát triển `backend/db.sqlite3` cho bài thử tải. Ví dụ PowerShell:

```powershell
$env:UCTP_SQLITE_PATH = 'D:\uctp_project\samples\bench_80.sqlite3'
& .\.venv\Scripts\python.exe backend\manage.py migrate --noinput
$env:UCTP_BENCHMARK = '1'
& .\.venv\Scripts\python.exe backend\manage.py benchmark_auto_schedule --input-dir samples\synthetic_80_seed42 --semester-name "HK test 2026-2027" --weeks 16 --approve --report samples\bench_80_report.json
```

Lệnh benchmark từ chối chạy trên `backend/db.sqlite3` hoặc SQL Server. Nó đưa ba file vào hàng đợi, xử lý một lần chạy, kiểm tra đủ số buổi và không trùng nhóm/phòng/giảng viên/lớp hành chính theo tuần, rồi tùy chọn duyệt và đối chiếu số dòng Excel xuất ra. Mỗi bộ dữ liệu nên dùng một SQLite mới. Không nên lấy kết quả `HEURISTIC` làm bằng chứng tối ưu; `INFEASIBLE` là kết luận của CP-SAT, còn `UNKNOWN` chưa kết luận được.

## Kết quả trên máy thử ngày 12/10/2026

| Kịch bản | Trạng thái | Buổi được xếp | Worker | Duyệt | Dòng xuất |
| --- | --- | ---: | ---: | ---: | ---: |
| 80 buổi khả thi | `OPTIMAL` | 80/80 | 12,159 giây | 0,928 giây | 80 |
| 160 buổi khả thi | `HEURISTIC` | 160/160 | 36,549 giây | 2,341 giây | 160 |
| 320 buổi khả thi | `HEURISTIC` | 320/320 | 43,694 giây | 7,339 giây | 320 |
| 449 buổi khả thi, lượt kiểm tra cuối | `HEURISTIC` | 449/449 | 56,737 giây | 13,467 giây | 449 |
| 1.000 buổi khả thi, luồng mở rộng | `HEURISTIC` | 1.000/1.000 | 5,478 giây | 0,314 giây | 1.000 |
| 2.000 buổi khả thi, luồng mở rộng | `HEURISTIC` | 2.000/2.000 | 11,183 giây | 0,574 giây | 2.000 |
| 80 buổi vô nghiệm | `INFEASIBLE` | 0/80 | 2,960 giây | — | 0 |

Đây là **một lần đo trên SQLite cục bộ** cho mỗi kích thước, không phải kiểm thử đồng thời hoặc cam kết hiệu năng. Các kết quả đến 449 buổi thuộc luồng CP-SAT cũ; từ 500 buổi hệ thống dùng lịch khởi tạo đã kiểm tra ràng buộc cứng, kiểm tra lại độc lập trước khi ghi và thử cải thiện bằng Great Deluge. Vì vậy các số thời gian không phải so sánh trực tiếp cùng một thuật toán. Cỡ 449 có 999 dòng trong file Học phần, sát giới hạn cũ. Lượt 449 trước khi thêm lớp kiểm tra cuối cũng đạt 449/449 (worker 63,613 giây, duyệt 16,581 giây); cả hai báo cáo JSON nằm trong `samples/bench_*_report.json`.

Sau khi bổ sung báo lỗi nhập liệu theo file/sheet/dòng, luồng hợp lệ được thử lại trên SQLite riêng: 80/80 buổi `OPTIMAL` và 1.000/1.000 buổi `HEURISTIC`, đều duyệt và xuất đủ dòng. Báo cáo nằm ở `samples/bench_80_validation_report.json` và `samples/bench_1000_validation_report.json`.

## Kiểm tra nhiều seed và nguồn lực hạn chế

Các lượt sau dùng SQLite tách biệt, 16 tuần, và kiểm tra toàn bộ xung đột nhóm, lớp, phòng, giảng viên; lượt khả thi còn duyệt và đối chiếu số dòng Excel xuất:

| Buổi | Kịch bản | Seed | Kết quả | Worker | Duyệt |
| ---: | --- | ---: | --- | ---: | ---: |
| 1.000 | feasible | 7 | 1.000/1.000 `HEURISTIC` | 5,360 giây | 0,306 giây |
| 1.000 | feasible | 17 | 1.000/1.000 `HEURISTIC` | 5,312 giây | 0,295 giây |
| 2.000 | feasible | 7 | 2.000/2.000 `HEURISTIC` | 10,968 giây | 0,669 giây |
| 1.000 | constrained | 7 | 1.000/1.000 `HEURISTIC` | 5,237 giây | 0,306 giây |
| 1.000 | constrained | 17 | 1.000/1.000 `HEURISTIC` | 5,237 giây | 0,297 giây |
| 1.000 | constrained | 42 | 1.000/1.000 `HEURISTIC` | 5,232 giây | 0,311 giây |
| 2.000 | constrained | 7 | 2.000/2.000 `HEURISTIC` | 10,522 giây | 0,594 giây |
| 1.000 | infeasible | 42 | 0/1.000 `INFEASIBLE`, không ghi lịch | 12,876 giây | — |

Với cỡ từ 500 buổi, nhánh heuristic thông thường trả `UNKNOWN` nếu chưa tìm được lịch; nó không tự chứng minh vô nghiệm. Riêng lượt `infeasible` trên có chứng cứ giới hạn tiết theo lớp và ngày, nên hệ thống trả `INFEASIBLE` và chỉ rõ ba dòng gây quá tải. Đây vẫn là một tập tình huống giả lập, chưa chứng minh hệ thống ổn định với dữ liệu và quy định thực tế của trường.

Lệnh `benchmark_auto_schedule` hỗ trợ `--expect-status` để kiểm tra trạng thái mong đợi. Nếu dùng `--approve` mà lần chạy không tạo lịch, lệnh trả mã lỗi thay vì báo thành công. Kết quả và số dòng chẩn đoán vẫn được ghi vào file `--report` để điều tra. Tên học kỳ trong `--semester-name` phải khớp chính xác cột `hoc_ky` của sheet `NhomHocPhan` trong file Học phần.

Kịch bản `varied_weeks` được bổ sung cho bản chốt báo cáo: 80 buổi thuộc 40 nhóm và 1.000 buổi thuộc 500 nhóm, mỗi nhóm có hai buổi yêu cầu. Các buổi sử dụng nhiều tập tuần khác nhau. Hai lượt kiểm tra đã xếp, duyệt và xuất đủ 80/80 (`OPTIMAL`) và 1.000/1.000 (`HEURISTIC`) buổi; xem các báo cáo `outputs/freeze_varied_80_report.json` và `outputs/freeze_varied_1000_report.json`. Kết quả này mở rộng phạm vi thử nghiệm so với sáu bộ cơ sở nhưng vẫn chưa đại diện cho dữ liệu thực tế của trường.

## Nguồn tham khảo lịch sử

[Đồ án quản lý phân công giảng dạy Khoa CNTT SGU](https://doc.edu.vn/tai-lieu/do-an-xay-dung-he-thong-quan-ly-phan-cong-giang-day-khoa-cntt-dai-hoc-sai-gon-7494/) mô tả giảng viên cơ hữu, thỉnh giảng, giảng viên khoa khác, cũng như danh mục và báo cáo quản lý. Tài liệu này phản ánh khảo sát cũ, chỉ dùng để tạo **tình huống thử và danh sách câu hỏi cần xác minh**. Mô hình hiện tại chưa có trường phân loại giảng viên thỉnh giảng/đơn vị ngoài trường; không nên tự thêm quy tắc định mức hoặc biểu mẫu xuất dựa riêng vào đồ án này.
