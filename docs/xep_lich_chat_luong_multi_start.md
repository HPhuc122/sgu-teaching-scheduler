# Xếp lịch chất lượng bằng Multi-start

Quyết định dùng CP-SAT hiện theo [ngân sách và ước lượng thời gian dựng](quyet_dinh_cp_sat.md).
Số khởi tạo, GD và tiêu chí chọn lịch trong tài liệu này giữ nguyên.

Từ bước 3.2, [GD dùng ngân sách còn dư](great_deluge_ngan_sach.md) sau lượt GD
ban đầu của các khởi tạo. Vẫn tối đa ba S0; quỹ đạo GD bổ sung không phải khởi
tạo mới. Cấu hình GD 3.000 bước dưới đây tiếp tục là lượt đầu/baseline.

Triển khai trên nhánh `quang`. Dữ liệu, biểu mẫu và quy trình SGU trong đồ án là
mô phỏng, không phải quy trình phân công nội bộ chính thức. Kết quả cần gắn với
từng cấu hình trong [mốc chốt 3.4](chot_thuat_toan_3_4.md); không khẳng định tối ưu toàn cục hoặc tính mới.

## Luồng ứng dụng

Giao diện có một nút **Xếp lịch chất lượng**, dùng nguyên hàng đợi, endpoint và
quy trình duyệt. Không có chế độ hay lựa chọn số lượt cho người dùng. Không thay
đổi model, database schema hoặc migration.

`auto_schedule.run_from_workbooks()` lập deadline ngay trước đọc/chuẩn bị đầu vào,
chụp nguyện vọng rồi gọi `quality_search.search_quality()`:

1. `SoftScorer` chụp cấu hình tiết, chuyên môn và nguyện vọng một lần. Mọi lượt
   dùng cùng dữ liệu chấm điểm; không đọc lại nguyện vọng ở nhánh heuristic dự
   phòng. Ngày nghỉ cũng được truyền cùng snapshot cho bộ giải, GD và audit.
2. Nếu lịch thuật toán chờ duyệt cũ khớp **đúng tất cả buổi, số tiết và tuần**,
   audit và chấm lại lịch đó theo đầu vào hiện tại để làm phương án dự phòng.
   Đây không phải một lượt sinh nghiệm; log có `kind=incumbent`.
3. Chạy tối đa ba lượt với seed mặc định 42, 43, 44. Lượt đầu sinh và audit Greedy
   trước; dưới 500 buổi có thể dùng CP-SAT để cải thiện hoặc cứu tìm kiếm thất bại.
   Khi đã có Greedy hợp lệ, CP-SAT chỉ được nhận nếu đủ thời gian ước lượng dựng
   mô hình, giải và dự trữ audit/GD; cửa sổ cơ sở 5 giây có thể mở rộng khi mô
   hình lớn hơn và còn đủ ngân sách sinh nghiệm thực tế.
   Từ 500 buổi dùng heuristic. Lượt hai và ba dựng **nghiệm greedy mới**, không
   tiếp tục từ S0 hoặc nghiệm thắng của lượt trước.
4. Seed đi vào `Random(seed)` của `_greedy_seed()` để đổi thứ tự buổi và lựa
   chọn giờ/phòng/giảng viên, đồng thời đi vào `CpSolver.parameters.random_seed`
   khi dùng CP-SAT. Seed khác có khả năng sinh nghiệm khác, không bảo đảm khác
   khi miền nghiệm nhỏ. Dấu vân tay dùng mã tài nguyên và mã buổi, không dùng PK.
5. Mỗi S0 phải qua `audit_solution()` và có điểm trùng hàm điểm chung. Nếu có
   điểm dương, chưa được CP-SAT chứng minh tối ưu và còn thời gian, chạy GD
   tối đa 3.000 bước, tối đa 5 giây trong phần ngân sách còn lại của lượt đó.
6. Audit và tính lại điểm kết quả GD. Nếu thất bại hoặc điểm báo cáo sai, giữ S0
   đã audit; không làm mất ứng viên tốt của lượt khác. S0 trùng một lượt trước
   vẫn được ghi nhận nhưng không lặp lại GD trên cùng S0.
7. Xếp các ứng viên đã audit theo điểm và audit lại khi chọn cuối. Nếu ứng viên
   đứng đầu bị loại, xét ứng viên tiếp theo, gồm cả S0 và lịch cũ hợp lệ. Sau đó
   mới ghi lịch chờ duyệt trong transaction hiện có. Lượt thất bại không xóa
   lịch chờ duyệt cũ. Lượt thành công có thể thay bản ghi lịch cũ bằng lần chạy
   mới nhưng không làm tăng điểm nếu lịch cũ vẫn hợp lệ trên cùng đầu vào.

Dừng sớm khi có điểm 0, chứng minh `OPTIMAL` của mô hình hiện tại hoặc chứng minh
`INFEASIBLE`. Chưa tìm được nghiệm do greedy/thời gian là `UNKNOWN`. `OPTIMAL`
chỉ có ý nghĩa trong mô hình và hàm điểm hiện tại; tìm kiếm heuristic/GD không
có chứng minh tối ưu toàn cục.

Hàm điểm nằm trong `soft_score.py`; CP-SAT và GD dùng chung các thành phần:
`5 × buổi tối + max(0, priority_chuyên_môn - 1) + phạt KhungGio`.
Ngữ nghĩa cũ về ngày của nguyện vọng và trọng số theo buổi được giữ nguyên;
chưa bổ sung công bằng tải, khoảng trống hoặc chi phí di chuyển.

## Ngân sách và nhật ký

Quản trị vận hành cấu hình bằng biến môi trường, sau đó khởi động lại worker:

```powershell
$env:UCTP_QUALITY_BUDGET_SECONDS = '60'
$env:UCTP_QUALITY_SEED = '42'
```

Mặc định 60 giây. Chia thời gian còn lại cho các lượt chưa chạy; cấp 80% phần
của mỗi lượt cho sinh nghiệm, phần còn lại cho GD/audit. CP-SAT bị giới hạn bởi
cả 30 giây lẫn deadline của lượt; không mặc định chạy 30 giây nhân ba. Deadline
được kiểm tra trong dựng mô hình, greedy và cả chuẩn bị GD. Không mở lượt mới
khi hết ngân sách. Không có vòng thử lại riêng để buộc đủ ba nghiệm khác nhau.

Đây là **deadline hợp tác**, không phải giới hạn cứng của tiến trình: một truy
vấn DB, thao tác đọc Excel, lệnh OR-Tools đang kết thúc hoặc audit/lưu bắt buộc
có thể hoàn tất sau deadline. Chẩn đoán khi thất bại cũng có chi phí riêng. Tổng
thời gian worker phải được đo thực tế, không suy từ ngân sách. Không bỏ audit
để ép trả kết quả đúng giây. Muốn SLA cứng cần lớp quản lý worker/timeout I/O
riêng, ngoài thay đổi này.

Không thêm trường database: dùng `AlgorithmRun.optimization_trials` hiện có.
Mỗi `kind=start` ghi seed, trạng thái bộ giải, outcome, điểm trước/sau, dấu vân
tay ban đầu/kết quả, thời gian sinh nghiệm/GD/audit và `seconds` thực tế.
`selection_audit_seconds` là chi phí audit cuối bổ sung, không nằm trong
`seconds` của lượt. `selected_score`/`selected_fingerprint` mô tả ứng viên được
chọn thực tế nếu cần quay về S0. `kind=stop` ghi ngừng do hết ngân sách; các
record này không được tính là lượt sinh nghiệm.

`objective_before` là điểm S0 của **ứng viên thắng**, không nhất thiết là điểm
lượt đầu. Nếu lịch cũ thắng, nó là điểm lịch cũ được chấm lại. `objective` là
điểm cuối được công nhận. Lịch có điểm thấp nhưng không qua hard audit không
được công nhận. Snapshot mềm dùng chung suốt lần chạy; audit độc lập vẫn có
thể loại ứng viên nếu quyền dạy hoặc lịch cố định đã thay đổi.

## Dữ liệu và thiết kế thực nghiệm

`samples/sgu_15_khoa_soft/` chứa bản sao nguyên byte của ba bộ gốc và sidecar
`experiment.json`: nguyện vọng sáng/chiều và mức ưu tiên chuyên môn mô phỏng,
có seed và SHA-256 của các workbook. Không thay đổi schema Excel/API để nhập
tiêu chí thử nghiệm. Benchmark nhập sidecar trước khi chụp nguyện vọng; chi phí
chuẩn bị dữ liệu này được báo riêng và giống nhau giữa các phương pháp.

Ba cấu hình CLI, chỉ dành cho benchmark trên SQLite tách biệt:

| Cấu hình | Cơ chế |
| --- | --- |
| `legacy` | Một S0, tối đa ba đường GD từ cùng S0, giữ giới hạn GD chung 9 giây. |
| `single` | Một khởi tạo trong cùng ngân sách tổng. |
| `multi-start` | Tối đa ba khởi tạo, chia sẻ cùng ngân sách tổng. |

`legacy` tái hiện cấu trúc tìm kiếm trước thay đổi tại HEAD `25cf807`, nhưng dùng
cùng hàm điểm, snapshot, audit và deadline đã sửa để so sánh công bằng. Nó không
phải chạy nguyên byte phiên bản lịch sử. Giới hạn nội bộ khác nhau có thể làm
các cấu hình dùng ít hơn ngân sách được cấp; luôn báo thời gian thực tế, không
coi cùng ngân sách là cùng số giây đã dùng. Chạy đối chiếu phiên bản lịch sử
nguyên trạng cần checkout riêng và ghi rõ thiếu sót về snapshot/deadline.

Mỗi bộ dữ liệu × ngân sách × seed dùng ba SQLite mới độc lập. Giữ cùng hash
workbook/sidecar, cấu hình tiết, số worker, phiên bản thư viện và máy. Seed tìm
kiếm mỗi lần lặp tăng 3 để các bộ seed Multi-start không chồng lấn. Luân phiên
thứ tự phương pháp. Mặc định thực nghiệm dùng một CP worker để giảm biến động;
ứng dụng giữ bốn worker. Điều này không bảo đảm tái lập tuyệt đối giữa máy và
phiên bản OR-Tools.

Đo và lưu từng lần chạy: H=0 khi có lịch đã kiểm tra, điểm mềm trước/sau, số buổi,
trạng thái, thời gian enqueue/worker/toàn luồng, số nghiệm đầu và nghiệm cuối
khác nhau. Không có lịch thì H/điểm mềm là null, không gán 0. Tổng hợp tỷ lệ khả
thi trên **tất cả** lần chạy; điểm mềm chỉ trên các lần khả thi và nên so thêm
theo cặp seed mà cả hai phương pháp đều khả thi. Báo trung vị, trung bình,
min/max; giữ raw JSON để phân tích thêm độ phân tán. Không loại `UNKNOWN` hoặc
`ERROR` ra khỏi mẫu tính tỷ lệ khả thi.

## Lệnh chạy

Từ gốc dự án, xem kế hoạch trước; lệnh mặc định không chạy solver và không ghi
báo cáo/database:

```powershell
& .\.venv\Scripts\python.exe analysis/compare_quality_search.py --repeats 10 --budgets 15 30
```

Kế hoạch này có 180 lần chạy, tổng ngân sách tìm kiếm danh nghĩa 4.050 giây,
**chưa gồm** tạo DB và các chi phí bổ sung. Đây là phép tính kế hoạch, không phải
số liệu hiệu năng. Chỉ thực thi sau khi đã thông báo/chấp thuận thời gian:

```powershell
& .\.venv\Scripts\python.exe analysis/compare_quality_search.py --repeats 10 --budgets 15 30 --run
```

Script tự tạo SQLite mới, áp dụng migration hiện có, gọi benchmark tuần tự và
ghi `outputs/quality_comparison/summary.json` từ các raw JSON thực tế. Nó từ chối
ghi đè DB/báo cáo đã có. Không gọi `makemigrations`, không chạm DB phát triển.
Để tổng hợp lại mà không chạy solver, dùng cùng tham số kèm `--summarize-only`.
Không có raw JSON đủ ba phương pháp thì không tự tạo summary thay thế.

Ví dụ chạy riêng một cấu hình (có thể mất thời gian, không phải lệnh kiểm tra):

```powershell
$env:UCTP_DB_ENGINE = 'sqlite'
$env:UCTP_BENCHMARK = '1'
$env:UCTP_SQLITE_PATH = 'D:\sgu-teaching-scheduler\outputs\quality_bo01_new.sqlite3'
& .\.venv\Scripts\python.exe backend/manage.py migrate --noinput
& .\.venv\Scripts\python.exe backend/manage.py benchmark_auto_schedule `
  --input-dir samples/sgu_15_khoa_soft/bo_01 `
  --semester-name 'SGU DEMO 15 khoa - BO_01' --weeks 16 `
  --experiment-file samples/sgu_15_khoa_soft/bo_01/experiment.json `
  --strategy multi-start --budget-seconds 30 --search-seed 42 --cp-workers 1 `
  --report outputs/quality_bo01_new.json
```

Tạo thư mục `outputs` trước nếu chưa có. Có thể thêm `--approve` để kiểm tra
duyệt/xuất; benchmark đã bỏ giả định mã khoa phải bắt đầu bằng `TEST_`. Không
trộn thời gian duyệt/xuất vào thời gian tìm kiếm. Bộ dữ liệu này vẫn chưa kiểm
chứng đầy đủ nguồn lực hạn chế, khoảng trống lịch hoặc dữ liệu vận hành thực tế.
