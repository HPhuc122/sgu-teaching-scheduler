# SQLite bị khóa khi duyệt lịch

## Kết luận từ mã nguồn

`review_schedules` không bao toàn bộ HTTP request trong transaction. Kiểm tra bộ
lọc nằm trước lời gọi `approve_schedule_entries`; dựng context/render nằm sau.
Transaction duyệt nằm trong service, bao cả lô, và gọi tiếp các transaction lồng
trong `save_schedule_entry`.

Trước bản sửa, service đọc học kỳ, danh sách và điều kiện rồi mới ghi từng buổi.
Mỗi buổi còn ghi lại toàn bộ bản ghi lịch, đồng bộ kế hoạch, xóa và tạo lại tuần
học dù yêu cầu chỉ đổi trạng thái. Sau lần ghi đầu, các kiểm tra cho các buổi tiếp
theo vẫn nằm trong cùng transaction đang giữ quyền ghi.

SQLite mặc định dùng DEFERRED; `select_for_update()` không khóa hàng trên SQLite.
Nếu kết nối khác đã giữ quyền ghi, việc nâng transaction đọc thành ghi có thể
thất bại với `SQLITE_BUSY`. Cơ chế này đã tái hiện bằng hai kết nối độc lập tới
một file SQLite tạm trong regression test.

`process_next_run` gọi `run_from_workbooks`, hàm này có `@transaction.atomic`
bao cả nhập danh mục, lưu kế hoạch, tìm kiếm lịch, audit và lưu kết quả. Các lần
ghi trước tìm kiếm có thể giữ quyền ghi tới khi hàm hoàn tất, kể cả khi đang xếp
học kỳ khác trong cùng file SQLite. Worker còn dọn bản ghi hàng đợi ở mỗi lượt
poll. Đây là các nguồn tranh chấp có cơ sở từ code, không phải bằng chứng worker
đã giữ khóa trong lần lỗi người dùng gặp. Hai request Django đồng thời hoặc kết
nối khác cũng có thể gây tranh chấp. Không có log/trace kết nối ở thời điểm đó
để quy trách nhiệm cho một tiến trình cụ thể.

Nguồn kỹ thuật: [giao dịch SQLite](https://www.sqlite.org/lang_transaction.html),
[Django 5.2: SQLite, khóa và transaction](https://docs.djangoproject.com/en/5.2/ref/databases/#sqlite-notes).

## Bản sửa giới hạn ở duyệt qua màn hình rà soát

- Chỉ trên SQLite, service lấy quyền ghi trước khi đọc snapshot duyệt bằng một
  `UPDATE id = id` trên học kỳ. Giá trị học kỳ không đổi. Cách này tránh bước nâng
  snapshot đọc thành ghi giữa chừng và sử dụng busy timeout hiện có. Các backend
  khác tiếp tục dùng `select_for_update()`.
- Giữ transaction toàn bộ lô và đầy đủ kiểm tra quyền, học kỳ khóa, trạng thái,
  ngày nghỉ, phân công cố định, hoạt động ngoài trường, giảng viên/phòng, tuần
  học và xung đột. Tái sử dụng bộ kiểm tra hiện tại với chế độ nội bộ chỉ kiểm tra.
- Khi mọi buổi hợp lệ, cập nhật một lần các trường `status`, `approved_by`,
  `approved_at`, với điều kiện trạng thái cũ là `ChoDuyet`. Số dòng phải khớp lô.
  Giữ giới hạn 1–100 ID không trùng như trước.
- Không ghi lại trường thời khóa biểu hoặc xóa/tạo lại `ScheduleWeek`. Vẫn đồng
  bộ giảng viên kế hoạch, chỉ ghi những bản ghi thực sự khác, trong cùng transaction.
- Khi gặp `SQLITE_BUSY`/`SQLITE_LOCKED`, view chỉ bắt lỗi sau khi service đã thoát
  transaction và rollback. Trả HTTP 503, `Retry-After: 2` và yêu cầu tải lại trang
  để thử lại; không tự gửi lại POST hoặc retry một phần lô. Có log kèm stack trace,
  mã học kỳ và số buổi. Các `OperationalError` không phải lỗi SQLite bận vẫn được
  phát ra, không che giấu lỗi khác.

Không thay đổi worker, thuật toán, timeout toàn cục, journal mode/WAL hoặc schema.
Không áp dụng migration, không mở ứng dụng trên database thật để tái hiện.

## Regression tests

`backend/school/test_review_approval.py` bổ sung 13 test:

- Chỉ ghi trạng thái duyệt, cùng dấu thời gian, giữ ID/nội dung tuần và trường
  lịch; đồng bộ giảng viên kế hoạch; một UPDATE trạng thái cho cả lô.
- Rollback toàn bộ khi buổi cuối không hợp lệ hoặc lỗi xảy ra sau cập nhật trạng thái.
- Không duyệt lại, không duyệt một phần lô trộn trạng thái; từ chối rỗng, trùng ID,
  quá giới hạn; duyệt đúng lô 100 buổi.
- Lỗi khóa sau ghi được rollback trước render; không che `OperationalError` khác.
- Trên file SQLite tạm: tái hiện lỗi DEFERRED đọc rồi ghi; trả 503 với writer thật
  đang giữ khóa; duyệt được sau giải phóng; lấy quyền ghi trước snapshot; hai người
  duyệt đồng thời có đúng một thành công, bên còn lại bị từ chối trạng thái cũ.

Các test file dùng `TransactionTestCase`, bản sao từ database test và connection
được tạo riêng trong từng thread. Không sao chép hoặc ghi `backend/db.sqlite3` thật.
Không dùng chỉ database shared-cache trong bộ nhớ để kết luận về khóa file SQLite.

## Giới hạn kiểm chứng

Tái hiện được cơ chế khóa thật và tranh chấp hai người duyệt trên file tạm. Chưa
tái hiện nguyên trạng sự cố HK1 2027–2028 với server và worker của người dùng chạy
đồng thời; chưa thể xác định tiến trình đã giữ khóa khi đó. Chưa kiểm thử SQL Server.

Worker giữ transaction dài vẫn có thể khiến yêu cầu chờ quá timeout. Bản sửa này
không loại bỏ giới hạn một writer của SQLite; khi đó duyệt thất bại an toàn với
503 thay vì cập nhật dở dang. Phạm vi chỉ là đường duyệt lô của màn hình rà soát,
không thay đổi cách duyệt toàn lần chạy ở `/admin/auto-schedule/` hoặc sửa lịch.

## Lệnh kiểm tra

Chạy trong terminal riêng từ gốc repository, dùng cấu hình test để không mở DB thật:

```powershell
$env:UCTP_DB_ENGINE = 'sqlite'
$env:UCTP_SQLITE_PATH = ':memory:'
& .\.venv\Scripts\python.exe backend\manage.py check
& .\.venv\Scripts\python.exe backend\manage.py makemigrations --check --dry-run
& .\.venv\Scripts\python.exe backend\manage.py test school --noinput
git diff --check
Get-FileHash backend\db.sqlite3 -Algorithm SHA256
```

Đóng terminal kiểm tra sau khi xong để không dùng nhầm `:memory:` khi chạy ứng dụng.

## Kết quả thực tế ngày 09/11/2026

| Kiểm tra | Kết quả |
| --- | --- |
| Regression test mới | PASS: 13 test, 1,901 giây |
| Toàn bộ Django suite (`manage.py test --noinput`, từ `backend`) | PASS: 243 test, 90,586 giây, exit code 0 |
| `manage.py check` | PASS: 0 issues |
| `makemigrations --check --dry-run` | PASS: `No changes detected` |
| `git diff --check` | PASS |
| SHA-256 `backend/db.sqlite3` trước và sau kiểm tra | Không đổi |

Hash đối chiếu: `9D2444E6D157FB59135098E4482C23E8684423A4ADAF5079EFE2DBD4C69E33F4`.
Kích thước database thật: 2.011.136 byte. Không sinh migration mới trong nhiệm vụ
này; migration 0015 và các thay đổi chưa commit của nhiệm vụ trước được giữ nguyên.
Chưa commit, push, merge hoặc chuyển nhánh.
