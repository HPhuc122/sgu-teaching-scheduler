# Đồng bộ kế hoạch và xuất Mẫu 1–5 trên nhánh quang1

## Phạm vi

Giữ nguyên ba workbook và thuật toán Greedy, CP-SAT, Multi-start, Great Deluge.
Phần nối nhập/lưu kế hoạch trong `auto_schedule.py` chỉ bổ sung kiểm tra nguồn;
không thay đổi thuật toán, mục tiêu hay dữ liệu benchmark.

## Đồng bộ an toàn

- Nút **Lưu kế hoạch trước** tạo bản xem trước bằng chính bộ kiểm tra/nhập hiện có
  trong savepoint rồi rollback; catalog và kế hoạch chưa được áp dụng. Chỉ bản xem
  trước và ba workbook tạm được lưu.
- Bản xem trước liệt kê thêm, cập nhật từng trường, bản ghi vắng trong Excel và
  lý do giữ lại. Bao gồm nhóm bị bỏ toàn bộ và liên kết lớp–nhóm không còn trong file.
- **Xác nhận áp dụng kế hoạch** mặc định giữ bản ghi vắng. Checkbox riêng cho phép
  xóa những bản ghi đủ điều kiện: có nguồn Excel được chứng minh bằng lần tạo,
  còn nguyên, không có lịch trong học kỳ. Không xóa catalog dùng chung.
- Dữ liệu từ trước migration có nguồn chưa xác định và không được tự nhận lại là
  thuộc Excel. Nhập lại dữ liệu trùng khóa không tạo bản sao hoặc quyền xóa mới.
- Bản ghi có sửa thủ công xung đột với Excel bị chặn ghi đè. Người dùng cần sửa
  Excel khớp dữ liệu muốn giữ hoặc chỉnh lại trên giao diện trước khi nhập.
  Giảng viên do bộ giải chọn được phân biệt với `fixed_lecturer` do người dùng gán;
  nhập lại file không cố định không xóa người đã được chọn khi phân công cố định
  không đổi. Phân công cố định vẫn được giữ trong đầu vào xếp lịch.
- Các thao tác xem trước/xác nhận yêu cầu quyền điều phối toàn hệ thống như luồng
  nhập ba file hiện tại; người dùng khoa không được dùng đường dẫn xác nhận để
  vượt quyền. Xem và xuất kế hoạch vẫn theo quyền khoa hiện có.
- Chặn nhập khi học kỳ đã khóa, đã có lịch hoặc có phiên xếp lịch đang hoạt động.
  Chặn đổi catalog dùng bởi lịch đã duyệt/học kỳ đã khóa/phiên chạy có lịch kể cả
  ở học kỳ khác. Luồng xếp lại lịch chờ duyệt vẫn theo cơ chế sẵn có.
- Xác nhận kiểm tra lại quyền, người tạo, thời hạn 30 phút, fingerprint dữ liệu,
  trạng thái học kỳ và danh sách xóa phía server trong transaction; không nhận
  danh sách ID xóa từ trình duyệt. Thay đổi sau xem trước yêu cầu xem trước lại.
- Dữ liệu và bản xem trước được khóa khi xác nhận. Thất bại rollback toàn bộ;
  bản xem trước chỉ bị xóa sau khi áp dụng thành công hoặc hủy. Các bản hết hạn
  được dọn khi tạo bản xem trước tiếp theo; chưa có tác vụ dọn định kỳ tự động.

## Migration và triển khai

Migration `0015_plan_import_preview_and_provenance` thêm hai bảng:

- `PlanImportState`: snapshot nguồn và giá trị Excel của các bản ghi được tạo
  qua luồng nhập. Không backfill nguồn cho dữ liệu cũ.
- `PendingPlanImport`: ba workbook tạm, người tạo, thời điểm, fingerprint và
  nội dung xem trước. Không thay đổi bảng dữ liệu kế hoạch/lịch hiện tại.

Migration được áp dụng trên database test. Chưa chạy `migrate` trên database thật.
Khi triển khai cần áp dụng migration trước khi sử dụng luồng nhập/xếp lịch mới.
Lệnh sinh migration ban đầu đã tạo tệp SQLite mặc định `backend/db.sqlite3`
rỗng (0 byte); tệp được giữ nguyên, không xóa hoặc reset. Không ghi dữ liệu nghiệp
vụ vào tệp này. Các kiểm tra cuối dùng SQLite trong bộ nhớ và database test riêng.

## File thay đổi

| File (tính từ gốc repository) | Lý do |
| --- | --- |
| `backend/school/planning.py` | Bỏ tự xóa khi nhập, lưu nguồn, giữ phân công và dựng lại đầy đủ ba workbook |
| `backend/school/plan_sync.py` | Nguồn dữ liệu, so sánh, xem trước/rollback, xác nhận, bảo vệ thủ công và kiểm tra trạng thái |
| `backend/school/models.py` | Hai model cho nguồn nhập và bản xem trước |
| `backend/school/migrations/0015_plan_import_preview_and_provenance.py` | Migration tương ứng, không backfill hoặc xóa dữ liệu cũ |
| `backend/school/auto_schedule.py` | Ba dòng nối kiểm tra/lưu nguồn vào luồng nhập trước xếp lịch; không sửa bộ giải |
| `backend/school/auto_schedule_views.py` | Xem trước, xác nhận và hủy, kiểm tra người tạo và tham số |
| `backend/school/templates/school/auto_schedule.html` | Tổng hợp thay đổi, chi tiết có thể mở rộng và checkbox xác nhận xóa |
| `backend/school/planning_exports.py` | Sửa phạm vi Mẫu 2, tổng theo ID, tối ưu tổng hợp/style, giữ phép tính hiện có |
| `backend/school/planning_views.py` | Giữ phân trang; tải trước đơn vị giảng viên khi xuất công tác |
| `backend/school/templates/school/teaching_plans.html` | Giữ thay đổi phân trang của nhiệm vụ trước |
| `backend/school/static/school/css/ui.css` | Giữ style phân trang của nhiệm vụ trước |
| `backend/school/test_planning_pagination.py` | Giữ 9 test phân trang của nhiệm vụ trước |
| `backend/school/test_plan_sync.py` | 21 test đồng bộ, giao dịch, quyền và quy trình 240/480/960 |
| `backend/school/test_planning_exports.py` | 6 test Mẫu 1–5, số liệu thiếu, phân loại, công thức văn bản và truy vấn |
| `docs/quy_trinh_bieu_mau_2026.md` | Cập nhật mô tả quy trình nhập/xác nhận |
| `docs/dong_bo_ke_hoach_quang1.md` | Báo cáo này và hướng dẫn kiểm tra |

## Biểu mẫu

- Giữ các sheet `Mau1_HK1`, `Mau1_HK2`, `Mau1_HK3`, `Mau2`–`Mau5`; dữ liệu chưa
  gán học kỳ số vẫn ở `Mau1_HKChuaGan`, không đoán từ tên.
- Giữ công thức và nguyên tắc thiếu dữ liệu trong `quy_trinh_bieu_mau_2026.md`:
  số tiết kế hoạch là số tiết/buổi nhân số tuần; số tiết thực tế phải được khai báo;
  không tự nhân hệ số học phần, không tự bổ sung quy định SGU hay năm sinh.
- Mẫu 2 chỉ gồm giảng viên cơ hữu thuộc khoa, gồm công tác khi không có buổi dạy.
  Tổng công tác chỉ xuất một lần theo ID giảng viên, kể cả khi thiếu mã viên chức.
- Mẫu 3/4 giữ phân loại mời/thỉnh giảng theo nguồn và đơn vị; Mẫu 5 giữ dữ liệu
  hoạt động. Dữ liệu văn bản bắt đầu bằng ký tự công thức Excel được escape.
- Không phân trang khi xuất. Các bảng tra nhóm/giảng viên và style Excel được
  tái sử dụng để tránh quét lặp và tạo style cho từng ô.
- Dựng lại ba workbook từ kế hoạch có cả công tác khác, hoạt động ngoài trường
  và các khoảng không khả dụng; giảm truy vấn lặp cho metadata/lớp/giảng viên.

## Kiểm tra giao diện

1. Chọn học kỳ chưa có lịch, tải ba file, chọn lưu kế hoạch. Kiểm tra dữ liệu
   chưa đổi, danh sách thêm/cập nhật và các giá trị trước/sau chính xác.
2. Xác nhận; nhập lại cùng ba file để kiểm tra không có bản sao.
3. Bỏ một buổi/nhóm, hoạt động hoặc công tác trong file. Kiểm tra mặc định giữ,
   chỉ xóa bản ghi được đánh dấu đủ điều kiện khi chọn checkbox.
4. Sửa một bản ghi trên giao diện rồi nhập file cũ: phải bị chặn ghi đè hoặc giữ
   khi vắng; dữ liệu cũ chưa rõ nguồn luôn được giữ khi vắng.
5. Thay đổi dữ liệu sau xem trước: xác nhận phải yêu cầu xem trước lại. Kiểm tra
   hủy, bản hết hạn, học kỳ khóa, phiên đang chạy và tài khoản khoa.
6. Phân công cố định trên giao diện, xếp từ kế hoạch, rà soát, duyệt, xuất Mẫu 1–5.
   Đối chiếu dữ liệu theo khoa, học kỳ và tổng số tiết, kể cả khi đang ở trang 20.

## Lệnh kiểm tra trước commit

Chạy từ gốc repository bằng PowerShell; biến SQLite chỉ áp dụng cho terminal này
để các lệnh kiểm tra không mở database nghiệp vụ. Test runner dùng database test.
Dùng terminal riêng cho các lệnh này; đóng terminal kiểm tra khi xong để không
vô tình dùng cấu hình `:memory:` khi khởi động máy chủ ứng dụng.

```powershell
$env:UCTP_DB_ENGINE = 'sqlite'
$env:UCTP_SQLITE_PATH = ':memory:'
& .\.venv\Scripts\python.exe backend\manage.py check
& .\.venv\Scripts\python.exe backend\manage.py makemigrations --check --dry-run
& .\.venv\Scripts\python.exe backend\manage.py test school --noinput
git diff --check
git status --short
```

## Kết quả thực tế ngày 09/11/2026

| Kiểm tra cuối | Kết quả |
| --- | --- |
| `manage.py check` | PASS: không có vấn đề (0 silenced) |
| `manage.py makemigrations --check --dry-run` | PASS: `No changes detected` |
| `manage.py test school --noinput` | PASS: 230 test, 87,423 giây, exit code 0 |
| `git diff --check` | PASS: không có lỗi whitespace |
| Diff trong `samples`, `analysis`, `scheduling` và các solver gốc | Không có thay đổi |

Trong lượt cuối, cả ba test quy trình dùng hàng đợi, bộ giải, audit, giao diện rà
soát và phê duyệt thật; không mock kết quả xếp lịch. Mỗi test có một phân công cố
định từ Excel và một phân công cố định thêm qua giao diện trước khi chạy.

| Buổi đầu vào | Buổi đã xếp/duyệt | Tổng tiết kế hoạch xuất qua các khoa | Kết quả |
| --- | --- | --- | --- |
| 240 | 240 | 960 | PASS |
| 480 | 480 | 1920 | PASS |
| 960 | 960 | 3840 | PASS |

Đây là fixture mô phỏng seed 7, hai tuần, không phải benchmark mới hoặc kết luận
về tối ưu. Các test quy trình dùng ngân sách 60 giây, một khởi tạo, không có lượt
GD bổ sung và ước lượng dựng CP bảo thủ để kiểm tra luồng heuristic. Các test
thuật toán sẵn có trong suite vẫn kiểm tra CP-SAT, Multi-start và Great Deluge.
Các test xuất riêng kiểm tra đủ cơ hữu, mời giảng, thỉnh giảng và hoạt động.

Các lượt phát triển đã phát hiện và sửa lỗi cấu hình CP trong test và điều kiện
bảo vệ liên kết lớp–nhóm quá chặt. Hai test trực tiếp cho bản sửa liên kết và
bỏ buổi trong nhóm còn lại cũng PASS trước khi chạy lại toàn suite cuối.

Chưa kiểm tra trực quan bằng trình duyệt hoặc xác nhận cạnh tranh ghi trên SQL
Server. Fingerprint của catalog dùng chung là bảo thủ: thay đổi catalog khác
cũng có thể làm bản xem trước hết hiệu lực, yêu cầu tạo lại.
Giữ quy tắc đầu vào hiện có là phải có ít nhất một buổi yêu cầu; không dùng
workbook rỗng để xóa toàn bộ học kỳ. Không suy diễn thêm quy định SGU từ ảnh mẫu.
