# Bước 3.1: sinh nghiệm Greedy-first

Từ bước 3.1.2, ứng dụng mặc định dùng quyết định CP-SAT theo ngân sách/ước lượng;
xem [quyet_dinh_cp_sat.md](quyet_dinh_cp_sat.md). Cửa sổ cố định mô tả dưới đây
được giữ làm đối chứng `fixed-window`, số liệu smoke lịch sử không thay đổi.

Triển khai trên `quang`. Dữ liệu và quy trình SGU là mô phỏng của đồ án.
Không sửa GD, toán tử lân cận, hàm điểm, nội dung `audit_solution()`, số khởi tạo,
schema, API, giao diện, phân quyền hoặc quy trình duyệt.

## Luồng và ngân sách

Trước đây, lượt dưới 500 buổi có sử dụng CP-SAT phải dựng xong mô hình rồi mới
gọi `_greedy_seed()`, thêm hint và chạy solver. Timeout khi dựng mô hình có thể
khiến lượt đó không có nghiệm dự phòng dù Greedy có khả năng tìm được lịch.

Hiện tại, `auto_schedule.solve()`:

1. `_prepare_generation()` và `_prepare_choices()` chuẩn bị cùng miền thời gian,
   phòng, chuyên môn, thời gian bận và lịch cố định cho cả hai thuật toán.
2. Sinh Greedy với thuật toán và seed như cũ. Ở lượt có thể dùng CP-SAT, Greedy
   dùng tối đa 25% thời gian sinh nghiệm còn lại để chừa cơ hội cứu bằng CP-SAT
   nếu thất bại. Lượt chỉ dùng heuristic giữ hạn thời gian sinh nghiệm của lượt.
3. Audit độc lập và chấm điểm theo `SoftScorer` chung trước khi giữ Greedy.
4. Dưới 500 buổi và ở lượt đầu, CP-SAT có thể cải thiện điểm của Greedy hoặc
   tìm lịch khi Greedy thất bại. Nếu Greedy có điểm 0 hoặc không đủ thời gian
   tối thiểu, trả ngay Greedy. Giới hạn 500 buổi và vai trò của các lượt sau giữ
   như trước bước 3.1; CP-SAT vẫn được chạy thật trên các bài kiểm thử nhỏ.
5. Khi đã có Greedy hợp lệ, dành mặc định tối đa 5 giây cho **cả dựng mô hình,
   hint và giải CP-SAT**. Dựng mô hình phải chừa 1 giây cho solver. Nếu chưa có
   Greedy hợp lệ, CP-SAT có thể dùng phần thời gian sinh nghiệm còn lại để cứu
   tính khả thi. Solver vẫn chịu giới hạn `cp_time_limit` và deadline chung.
6. Timeout khi dựng mô hình/hint hoặc CP-SAT trả `UNKNOWN` không làm mất Greedy
   đã audit. CP-SAT có nghiệm phải qua audit và đối chiếu hàm điểm; nghiệm kém
   hơn không thay thế Greedy. Nếu solver kết luận `INFEASIBLE` trong khi Greedy
   đã qua audit, giữ Greedy và ghi `cp_warning` để điều tra mâu thuẫn mô hình.
7. `quality_search.search_quality()` tiếp tục quy trình cũ: tối đa ba khởi tạo,
   GD, kiểm tra và chọn ứng viên khả thi có điểm thấp nhất, audit lại trước lưu.

Cấu hình quản trị qua biến môi trường, không có lựa chọn mới trên giao diện:

| Biến | Mặc định | Ý nghĩa |
| --- | ---: | --- |
| `UCTP_QUALITY_BUDGET_SECONDS` | 60 | Deadline tìm kiếm chung, bắt đầu trước đọc đầu vào |
| `UCTP_QUALITY_CP_REFINEMENT_SECONDS` | 5 | Cửa sổ CP-SAT khi có Greedy hợp lệ, gồm dựng mô hình |
| `UCTP_QUALITY_CP_MIN_SOLVE_SECONDS` | 1 | Thời gian dành lại cho solver sau dựng mô hình |

Các giá trị phải hữu hạn, dương và cửa sổ cải thiện không nhỏ hơn thời gian tối
thiểu cho solver. Các mốc 25%, 5 giây và 1 giây là lựa chọn điều phối cần kiểm
chứng thêm, chưa phải cấu hình đã được chứng minh tốt nhất. Deadline kiểm tra
theo các điểm hợp tác, không phải bộ ngắt cứng. Audit, giải phóng mô hình, chẩn
đoán khi thất bại, lưu database và I/O có thể làm thời gian toàn luồng vượt ngân
sách; không bỏ audit hoặc lưu lịch dở dang để ép đạt mốc thời gian.

## Phép đo và trạng thái

`optimization_trials[].generation` ghi thời gian thực tế bằng đồng hồ monotonic:

| Trường | Phạm vi |
| --- | --- |
| `preparation_seconds` | Chuẩn bị miền, thời gian bận và lịch cố định trong `solve()` |
| `greedy_seconds` | Chỉ `_greedy_seed()` |
| `cp_model_seconds` | Dựng mô hình và thêm hint, bao gồm phần dựng bị timeout |
| `cp_solve_seconds` | Chỉ `CpSolver.Solve()`; bằng 0 nếu chưa gọi |
| `validation_seconds` | Audit và chấm điểm Greedy/CP-SAT trong `solve()` |

Các phép đo trên không lồng nhau. `generation_seconds` là thời gian toàn lời gọi
`solve()`, có thêm chuyển đổi kết quả, thiết lập solver và giải phóng mô hình;
không giả định tổng năm trường bằng chính xác thời gian này. `snapshot_seconds`
ghi chi phí tạo scorer chung ở lượt đầu. `input_preparation_seconds` trên bản ghi
đầu ghi một lần chi phí đọc workbook, chuẩn bị/import catalog và snapshot nguyện
vọng trước tìm kiếm. `audit_seconds`/`selection_audit_seconds` của driver là các
audit bổ sung sau sinh nghiệm/GD và khi chọn cuối, không nằm trong
`generation.validation_seconds`.

`generation.source` (`GREEDY`, `CP_SAT`, `NONE`) là nguồn **S0 trả về bởi solve**,
không giả định lịch sau GD giống S0. Bản ghi `selected=true` cho biết lượt sinh
ra lịch được chọn; xem thêm `paths`, `score_before/after` và fingerprint để biết
GD đã thay đổi lịch chưa. Trạng thái cuối của lịch từ Greedy vẫn là `HEURISTIC`.

`cp_called=false`, `cp_status=NOT_CALLED` cùng `cp_skip_reason` phân biệt bỏ qua
do ngân sách, kích thước, lượt sau, điểm 0 và timeout khi dựng mô hình/hint.
Chỉ ghi `cp_status=UNKNOWN` khi đã thật sự gọi solver và nhận trạng thái đó.
`UNKNOWN` của solver không chứng minh vô nghiệm hoặc tự chứng minh nguyên nhân
timeout. Nếu không có lịch và CP-SAT chưa chứng minh `INFEASIBLE`, kết quả tìm
kiếm vẫn là `UNKNOWN`. `greedy_status`, điểm Greedy/CP-SAT và lỗi audit được lưu
riêng; không gán điểm 0 cho lượt thất bại.

## Đối chứng nhỏ trước bộ lớn

`benchmark_auto_schedule --generation-policy model-first|greedy-first` chọn
riêng chính sách sinh nghiệm, độc lập với `--strategy legacy|single|multi-start`.
`model-first` giữ thứ tự dựng mô hình trước Greedy và ngân sách như trước bước
3.1, nhưng dùng chung các kiểm tra an toàn mới. Đây là đối chứng cơ chế, không
phải bản sao nguyên byte phiên bản lịch sử. Không dùng thay đổi số khởi tạo để
quy toàn bộ chênh lệch cho Greedy-first.

Từ gốc dự án, xem kế hoạch hai lượt, chưa gọi solver hoặc tạo database:

```powershell
& .\.venv\Scripts\python.exe analysis/compare_initial_generation.py --budget-seconds 5 --strategy single
```

Thực thi hai lượt trên `bo_01`, cùng seed 42, ngân sách 5 giây, một CP worker,
một khởi tạo, cùng workbook và sidecar tiêu chí mềm; mỗi lượt dùng SQLite mới:

```powershell
& .\.venv\Scripts\python.exe analysis/compare_initial_generation.py --budget-seconds 5 --strategy single --output-dir outputs/initial_generation_check_new --run
```

Script từ chối ghi đè; áp dụng migration hiện có vào DB thử nghiệm, không tạo
migration và không dùng DB ứng dụng. Raw JSON lưu hash dữ liệu, mã thuật toán,
thư viện và cấu hình. `summary.json` liệt kê kết quả từng lượt, không tự tạo dữ
liệu hoặc coi thất bại là điểm 0. Thêm `--input-dir samples/sgu_15_khoa_soft/bo_02`
để đổi bộ, `--repeats` để mở rộng khi đã thống nhất thời gian. Thứ tự hai chính
sách được đảo qua các lần lặp.

Sau smoke, so hai chính sách ở **cùng** `--strategy multi-start` trong thư mục
mới để kiểm tra tương tác, vẫn tối đa ba khởi tạo mỗi lượt. Cần phân tích riêng
điểm S0, thời gian sinh nghiệm, tỷ lệ khả thi, điểm sau GD, độ đa dạng và thời
gian toàn luồng. Cùng ngân sách cấu hình không có nghĩa hai cách tiêu thụ bằng
nhau; giữ số giây thực tế và trạng thái thất bại trong mẫu thống kê.

Smoke đơn lẻ chỉ kiểm tra luồng dự phòng, chưa chứng minh chất lượng hay hiệu
năng ổn định trên ba bộ dữ liệu. Bộ nhỏ cũng chưa đo hiệu năng CP-SAT nếu hai
lượt đều dừng trước khi gọi solver. Không khẳng định tối ưu toàn cục.

## Kiểm chứng ngày 18/10/2026

- `backend/manage.py check`: không có lỗi.
- `backend/manage.py test school --noinput`: 111 bài qua (17 bài mới cho sinh nghiệm).
- `python -m unittest discover -s tests`: 7 bài qua.
- `backend/manage.py makemigrations --check --dry-run`: `No changes detected`.
- `git diff --check`: không có lỗi whitespace.

Đã chạy hai cặp smoke, mỗi cặp hai lượt single-start trên `bo_01` (240 buổi),
seed 42, ngân sách 5 giây, một CP worker, sidecar nguyện vọng/chuyên môn mô phỏng.
Cặp đầu ở `outputs/initial_generation_smoke_01` dùng để kiểm tra ban đầu. Cặp
xác nhận ở `outputs/initial_generation_smoke_02` chạy sau khi bổ sung bảo vệ
timeout lúc thêm hint; hash mã trong hai báo cáo khớp nhau và khớp phiên bản
`auto_schedule.py` cuối. Không chạy lại bộ 45 hoặc 180 lượt.

Số đo dưới đây lấy từ cặp xác nhận `_02`, đơn vị giây:

| Giai đoạn | Model-first | Greedy-first |
| --- | ---: | ---: |
| Đọc/chuẩn bị đầu vào trước tìm kiếm | 1.375178 | 1.447434 |
| Snapshot scorer dùng chung | 0.005165 | 0.005151 |
| Chuẩn bị miền trong solve | 0.019777 | 0.020632 |
| Greedy | 0 (chưa gọi) | 0.025227 |
| Dựng mô hình CP-SAT, bị dừng | 2.876961 | 1.772594 |
| Thực thi CP-SAT | 0 (chưa gọi) | 0 (chưa gọi) |
| Audit/chấm điểm trong solve | 0 (chưa có nghiệm) | 0.018419 |
| Toàn lời gọi sinh nghiệm | 2.965628 | 1.880192 |
| GD giữ nguyên | 0 (không có S0) | 0.230859 |
| Audit sau sinh nghiệm/GD của driver | 0 | 0.040058 |
| Audit khi chọn cuối | Không có ứng viên | 0.147878 |
| Toàn luồng enqueue + worker | 6.617 | 3.947 |

Model-first trả `UNKNOWN`, không có lịch; không phải `INFEASIBLE` hay CP-SAT
trả `UNKNOWN`. Cả hai báo cáo đều ghi `cp_status=NOT_CALLED`,
`cp_skip_reason=MODEL_BUILD_TIMEOUT`. Greedy-first giữ được S0 đã audit với điểm
1066, sau GD cũ còn 998; lịch cuối có 240/240 buổi, H=0, trạng thái `HEURISTIC`.
Chênh lệch thời gian dựng còn bao gồm việc Greedy-first chừa một giây cho solver;
không coi đây là bằng chứng thao tác dựng cùng mô hình đã được tăng tốc.

Thời gian toàn luồng Model-first vượt 5 giây còn bao gồm đọc đầu vào, enqueue,
chẩn đoán 240 yêu cầu khi không có lịch, xử lý queue/DB và I/O. Các chi phí sau
tìm kiếm không bị dừng cứng bởi deadline; log hiện tại không tách riêng từng
chi phí này để quy chính xác phần vượt cho từng loại. Thời gian tạo DB/migration
và áp dụng sidecar được tách khỏi `processing_seconds`.

Kết quả chỉ xác nhận cơ chế giữ Greedy khi timeout dựng mô hình trong cặp đo
này. Không có so sánh điểm mềm ghép cặp vì Model-first không có lịch. Không đo
được hiệu năng CP-SAT từ smoke này; các nhánh CP-SAT có nghiệm/không có nghiệm
được kiểm tra trong test. Cần thêm nhiều seed và bo_02/bo_03 trước khi kết luận
hiệu năng ổn định, ưu thế chất lượng hoặc hiệu quả của các mốc ngân sách mới.
