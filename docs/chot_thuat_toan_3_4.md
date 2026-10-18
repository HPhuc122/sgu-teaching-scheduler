# Mốc chốt thuật toán — Bước 3.4 / tài liệu cho Chương 3

Dữ liệu và quy trình phân công SGU là mô phỏng do nhóm xây dựng, không phải
dữ liệu, biểu mẫu hoặc quy trình phân công nội bộ chính thức của trường.
Đây là mốc mã nguồn đang làm việc trên `quang`, chưa phải Git commit/tag đã phát hành.

## Bài toán, ràng buộc và mục tiêu

Mỗi yêu cầu buổi học được gán giảng viên, phòng, thứ và tiết bắt đầu, giữ nguyên
số tiết và tập tuần. `solution_audit.audit_solution()` kiểm tra đủ và đúng từng
buổi; thứ trong miền cho phép; tiết liên tiếp trong cùng ca; tuần trong học kỳ;
phòng sẵn sàng, đủ sức chứa, đúng loại; giảng viên đang công tác, đúng chuyên môn;
không vướng ngày nghỉ hoặc thời gian không khả dụng; không trùng phòng, giảng viên,
nhóm học phần hoặc lớp hành chính theo tuần/tiết, kể cả lịch cố định.

Hard Penalty không phải trọng số để đánh đổi với điểm mềm: ứng viên vi phạm bị
loại. Lịch khả thi được báo H=0; lượt không có lịch dùng null, không thay bằng 0.
`UNKNOWN` là chưa tìm được lịch, không chứng minh `INFEASIBLE`.

Với mỗi buổi `a`, `SoftScorer.penalty(a)` cộng:

- 5 điểm nếu ca bắt đầu có tên bắt đầu bằng `toi` (không phân biệt hoa/thường).
- `max(0, priority_chuyên_môn − 1)`.
- Với nguyện vọng `KhungGio` áp dụng cho ngày đó: priority ≤2 và khác ca mong muốn
  phạt `(3−priority)×4`; priority ≥3 và trùng ca cần tránh phạt `(priority−2)×4`.
  Nguyện vọng có ca trống hoặc ngày cụ thể khác ngày xếp không đóng góp.

`SoftScorer.score()` cộng trên các buổi; chưa nhân số tiết hoặc số tuần. Đây là
hàm điểm hiện có, không phải giờ giảng quy đổi. Chưa thêm cân bằng khối lượng,
khoảng trống hoặc di chuyển. Mở rộng các mục tiêu này sẽ thay bài toán đánh giá,
phải tách khỏi cải thiện tìm kiếm với mục tiêu hiện tại.

## Luồng thuật toán và lưu lịch

1. `schedule_queue.enqueue_schedule()` kiểm định dạng, đưa vào hàng đợi; worker
   `process_next_run()` gọi `auto_schedule.run_from_workbooks()` trong giao dịch.
2. Chuẩn bị demands, danh mục và snapshot nguyện vọng; `SoftScorer` chụp tiết,
   mức ưu tiên chuyên môn và nguyện vọng dùng chung cho toàn bộ lần tìm kiếm.
3. `quality_search.search_quality()` xem lịch chờ duyệt cũ là incumbent chỉ khi
   khớp đúng yêu cầu/số tiết/tuần, qua audit và được chấm theo snapshot hiện tại.
4. Tối đa ba khởi tạo với seed gốc/+1/+2. `auto_schedule.solve()` gọi
   `_greedy_seed()` trước, kiểm tra và giữ Greedy hợp lệ. Seed thực sự đi vào RNG
   để thay đổi thứ tự buổi và lựa chọn thời gian/phòng/giảng viên.
5. Ở khởi tạo đầu, dưới 500 buổi, chính sách CP budget-aware xem xét số buổi,
   thời gian còn lại, ước lượng dựng mô hình và dự trữ giải/audit/GD. Không đủ thì
   bỏ qua trước khi dựng (`SKIPPED_BUDGET`, `cp_status=NOT_CALLED`). Đủ thì CP-SAT
   có thể cải thiện hoặc cứu tìm kiếm. Chỉ nghiệm CP hợp lệ có điểm tốt hơn mới
   thay Greedy. Timeout giữ nghiệm khả thi đã có. Từ 500 buổi và ở lượt sau dùng
   nhánh constructive; không bỏ CP-SAT khỏi hệ thống.
6. Mỗi S0 qua audit; S0 khác nhau có lượt GD đầu, tối đa 3.000 vòng/5 giây trong
   ngân sách của lượt. Trùng fingerprint ghi nhận DUPLICATE, không lặp GD đầu.
7. GD Adaptive phân phối thời gian còn dư sau các lượt đầu, round-robin giữa các
   khởi tạo, luân phiên từ BEST/S0. Tối đa 9 quỹ đạo thêm, 2 giây/30.000 vòng mỗi
   quỹ đạo, seed mới; đây không phải khởi tạo thứ tư. Dừng quỹ đạo sau 6.000 vòng
   không cải thiện best; mỗi khởi tạo dừng sau hai quỹ đạo liên tiếp không cải thiện.
8. Giữ nguyên ba toán tử: đổi ngày/giờ, đổi phòng, đổi giảng viên. Mực nước cho
   phép một số bước trung gian bằng/xấu hơn; best được giữ riêng. Audit kết quả,
   đối chiếu hàm điểm, không thay best bằng nghiệm xấu hơn hoặc lỗi.
9. Xếp ứng viên theo điểm, audit lại khi chọn; nếu bị loại xét ứng viên tiếp theo.
   Chỉ sau đó thay lịch thuật toán chờ duyệt trong transaction; lịch cố định và
   quy trình duyệt/phân quyền giữ nguyên. Một chức năng **Xếp lịch chất lượng**,
   không có chế độ hoặc tùy chọn số lượt trên giao diện.

Điểm 0, chứng minh tối ưu trong mô hình hoặc hết ngân sách có thể dừng sớm.
Không khẳng định nghiệm tốt nhất trong các phương án đã xét là tối ưu toàn cục.

## Cấu hình ứng dụng và cấu hình thực nghiệm

| Tham số | Ứng dụng mặc định | Xác nhận 30 lượt bước 3.3 |
|---|---:|---:|
| `UCTP_QUALITY_BUDGET_SECONDS` | 60 giây | 15 giây qua tùy chọn benchmark |
| `UCTP_QUALITY_SEED` | 42 | 42,45,48,51,54 |
| Số khởi tạo tối đa | 3, không có lựa chọn UI | 3 |
| CP workers | 4 tại `search_quality()` | 1 |
| `UCTP_QUALITY_CP_BUILD_PROFILE` | Không nạp profile nếu chưa cấu hình | `analysis/cp_build_observations.json` |
| CP refinement / thời gian giải tối thiểu | 5 / 1 giây | 5 / 1 giây |
| Ước lượng dựng CP | 0,04 giây/buổi × hệ số 1,25; kết hợp profile nếu có | Cùng prior, cùng profile |
| Dự trữ GD mỗi lượt | 1 giây, co theo thời gian còn lại | 1 giây |
| `UCTP_QUALITY_AUDIT_RESERVE_SECONDS` | **0,5 giây (giữ nguyên)** | **0,5 giây** |
| GD thêm / thời gian / vòng | 9 / 2 giây / 30.000 | Cùng cấu hình |
| Stagnation / stale / min path | 6.000 / 2 / 0,1 giây | Cùng cấu hình |

Không được dùng bảng kết quả 15 giây/1 worker/profile nạp rõ làm số liệu đại diện
cho cấu hình ứng dụng 60 giây/4 worker/profile chưa cấu hình. Trong 30 lượt, cả
hai chính sách đều không gọi CP-SAT; chưa đánh giá lợi ích của CP-SAT khi thực sự chạy.

## Bằng chứng chất lượng: xác nhận GD bước 3.3

30 lượt = ba bộ × năm seed × Baseline/Adaptive; mỗi lượt SQLite riêng, workbook
nguyên byte giống bộ gốc, sidecar mô phỏng thêm nguyện vọng và mức ưu tiên chuyên
môn. Hai phía cùng Greedy-first, CP budget-aware, Multi-start, score và audit;
chỉ khác chính sách GD. Đảo thứ tự chạy theo bộ/seed. 30/30 audit sau lưu PASS,
điểm/fingerprint tính lại khớp; checksum database không đổi khi audit chỉ đọc.

| Bộ | Buổi | Điểm TB B → A | Giảm của điểm TB | Thắng/hòa/thua | Thời gian TB B → A (s) |
|---|---:|---:|---:|---|---|
| bo_01 | 240 | 927,4 → 894,8 | 3,515% | 5/0/0 | 2,591 → 7,712 |
| bo_02 | 480 | 1947,8 → 1855,2 | 4,754% | 5/0/0 | 5,061 → 14,507 |
| bo_03 | 960 | 4159,2 → 4083,8 | 1,813% | 5/0/0 | 8,387 → 15,222 |

| Bộ | Seed | Baseline | Adaptive | Giảm điểm |
|---|---:|---:|---:|---:|
| bo_01 | 42 | 914 | 887 | 27 |
| bo_01 | 45 | 925 | 908 | 17 |
| bo_01 | 48 | 927 | 886 | 41 |
| bo_01 | 51 | 919 | 916 | 3 |
| bo_01 | 54 | 952 | 877 | 75 |
| bo_02 | 42 | 1937 | 1854 | 83 |
| bo_02 | 45 | 1969 | 1863 | 106 |
| bo_02 | 48 | 1922 | 1858 | 64 |
| bo_02 | 51 | 1979 | 1871 | 108 |
| bo_02 | 54 | 1932 | 1830 | 102 |
| bo_03 | 42 | 4053 | 4042 | 11 |
| bo_03 | 45 | 4258 | 4145 | 113 |
| bo_03 | 48 | 4189 | 4143 | 46 |
| bo_03 | 51 | 4151 | 4060 | 91 |
| bo_03 | 54 | 4145 | 4029 | 116 |

15/15 cặp có cùng fingerprint S0 và cùng kết quả GD đầu. Mỗi lượt thực sự có ba
S0 khác nhau. Vì giữ cố định Multi-start, đây là bằng chứng lợi ích pha GD bổ
sung, không phải phép đo riêng lợi ích Multi-start. Baseline 9.000 vòng/lượt;
Adaptive trung bình 83.987,2 / 76.776,4 / 36.426,4 vòng trên ba bộ. bo_01/02
dùng 12 quỹ đạo/lượt, bo_03 dùng 8–9. Toàn pha thêm dừng PATH_LIMIT ở bo_01/02,
BUDGET_EXHAUSTED ở bo_03; từng quỹ đạo chủ yếu STAGNATION hoặc TIME_LIMIT.

Đây là cải thiện nhất quán trên mẫu đã đo; không chứng minh luôn tốt hơn, nhanh
hơn, tính mới thuật toán hoặc tối ưu toàn cục. Chi tiết trung vị/min/max/các bộ
đếm nằm trong JSON bằng chứng được giữ cùng tài liệu.

## Deadline: phân tích đúng phạm vi số đo

`benchmark_auto_schedule.Command.handle()` đo `processing_seconds = enqueue_seconds
+ worker_seconds`, làm tròn mili giây. Không gồm migrations, áp dụng sidecar
trước enqueue, khởi động Python, chờ worker ngoài phép đo, audit độc lập sau lưu.
`run_from_workbooks()` chỉ bắt đầu deadline sau khi worker đã nhận việc, trước
đọc/chuẩn bị workbook. Enqueue nằm ngoài deadline này. GD kiểm tra thời gian hợp
tác; audit bắt buộc và transaction vẫn hoàn tất, không có cơ chế ngắt cứng I/O.

| Lượt cũ | Processing | Enqueue | Worker | Vượt processing | Vượt worker |
|---|---:|---:|---:|---:|---:|
| bo_02 / 45 | 15,013 | 0,207 | 14,806 | 0,013 | 0 |
| bo_03 / 42 | 15,220 | 0,242 | 14,978 | 0,220 | 0 |
| bo_03 / 45 | 15,166 | 0,264 | 14,902 | 0,166 | 0 |
| bo_03 / 48 | 15,233 | 0,233 | 15,000 | 0,233 | 0 theo độ chính xác log |
| bo_03 / 51 | 15,257 | 0,233 | 15,024 | 0,257 | 0,024 |
| bo_03 / 54 | 15,234 | 0,252 | 14,982 | 0,234 | 0 |

Năm lượt có worker ≤15 giây theo log: vượt processing xuất hiện khi cộng enqueue.
Lượt bo_03/51 có worker vượt 0,024 giây. Log cũ đo riêng generation, GD, audit
driver/selection nhưng chưa đo từ search return đến commit. Phần dư còn gồm
fingerprint, scorer, SQL, tạo đối tượng, commit, claim/finalize queue. Không có
bằng chứng để phân bổ chính xác 0,024 giây hoặc toàn bộ phần dư cho SQL hay GD.

Bước 3.4 bổ sung telemetry **chỉ trong lệnh benchmark**, không đổi luồng sản xuất:
`phase_seconds.before_search_seconds`, `search_including_audits_seconds`,
`finalization_after_search_seconds`, `finalization_sql_execute_seconds`,
`queue_and_worker_other_seconds`. Finalization gồm tạo đối tượng, ghi lịch/tuần
và commit của transaction gốc. SQL execute là phần con, chưa đo riêng commit;
không cộng hai số này. Audit driver trong trials là phần con của search, không
cộng lặp. Không suy ngược thời gian đo mới thành thời gian lưu của đợt cũ.

## Kiểm chứng dự trữ, quyết định chốt và kiểm thử

Đã chạy **12 lượt mới**: Adaptive với dự trữ 0,5/0,8 giây, bo_02/seed 45 và năm seed bo_03 (42,45,48,51,54); cùng ngân sách 15 giây, tối đa ba khởi tạo, một CP worker, cùng dữ liệu/profile/score/hard constraints. Thứ tự hai cấu hình xen kẽ. Cả 12 lịch audit sau lưu PASS, checksum database không đổi. Không lấy số liệu cũ đại diện cho cấu hình thử mới.

| Bộ | Seed | Điểm 0,5 → 0,8 | Δ điểm mới−cũ | Processing 0,5 → 0,8 (s) | Cùng S0/GD đầu |
|---|---:|---|---:|---|---|
| bo_02 | 45 | 1863 → 1891 | 28 | 15.345 → 15.044 | True |
| bo_03 | 42 | 4079 → 4053 | -26 | 16.277 → 16.172 | False |
| bo_03 | 45 | 4258 → 4145 | -113 | 16.396 → 15.028 | False |
| bo_03 | 48 | 4143 → 4143 | 0 | 15.244 → 14.943 | True |
| bo_03 | 51 | 4060 → 4060 | 0 | 15.232 → 14.940 | True |
| bo_03 | 54 | 4029 → 4064 | 35 | 15.223 → 14.932 | True |

| Dự trữ | Toàn luồng >15s | Worker >15s | Processing TB / max (s) |
|---|---:|---:|---|
| 0.5 | 6/6 | 3/6 | 15.620 / 16.396 |
| 0.8 | 3/6 | 1/6 | 15.177 / 16.172 |

Thời gian pha trung bình **trong đợt mới**, giây; SQL execute nằm trong tail:

| Dự trữ | Trước search | Search gồm audit | Audit driver (phần con) | Hoàn tất sau search, gồm commit | SQL execute (phần con) | Queue/worker khác |
|---|---:|---:|---:|---:|---:|---:|
| 0.5 | 5.306104 | 9.496299 | 0.941723 | 0.418353 | 0.031842 | 0.026802 |
| 0.8 | 5.030543 | 9.457196 | 0.985687 | 0.379728 | 0.028758 | 0.025129 |

Hai cặp khác GD đầu đã được kiểm tra: bo_03/42 có cùng S0 nhưng các lượt đầu dừng TIME_LIMIT, chạy 1.099/1.047/861 vòng ở 0,5s và 1.110/1.301/1.351 vòng ở 0,8s; điểm lượt thứ ba 4.079/4.053. Chuẩn bị đầu vào mất 9,071/9,013 giây. bo_03/45 cũng cùng S0 nhưng chuẩn bị mất 8,663/4,138 giây; GD đầu 0,5s chỉ đạt 1.203/1.484/1.582 vòng (TIME_LIMIT), còn 0,8s đều đạt 3.000 vòng. Đây là khác biệt thời gian/đường tìm kiếm đã quan sát, chưa có số đo để quy nguyên nhân cho tải CPU hay I/O cụ thể. Không dùng hai cặp này chứng minh tăng dự trữ làm chất lượng tốt hơn.

**Quyết định chốt: giữ mặc định dự trữ 0,5 giây và GD Adaptive đã được xác nhận.** Thử 0,8 giây chưa giải quyết chắc chắn vượt toàn luồng; bo_02/45 tăng 28 điểm (1,503%) và một số lượt bo_03 thay đổi điểm theo thời gian thực dùng. Một lần đo mỗi cấu hình/cặp, biến động thời gian quan sát được và telemetry mới không cho phép suy ra tác động nhân quả thuần của 0,3 giây dự trữ. Chưa đủ bằng chứng rằng đổi mặc định vừa giữ chất lượng vừa đạt giới hạn 15 giây, nên không ép cấu hình mới vào bản chốt.

0,8 giây vẫn có thể cấu hình bởi quản trị, được regression test riêng; không thay lõi Greedy, CP-SAT, Multi-start, GD, ràng buộc hay score. Nếu 15 giây là SLA toàn luồng bắt buộc thì **chưa sẵn sàng chốt SLA**: cần một yêu cầu riêng về ngân sách từ enqueue, thời gian commit/queue, tải và bách phân vị thay vì tăng hằng số cho đến khi một smoke đạt. Không bỏ audit hoặc cắt ngang transaction.

**Sẵn sàng chốt phiên bản thuật toán cho phạm vi đồ án mô phỏng**, với deadline hợp tác và các hạn chế đã ghi; không tuyên bố sẵn sàng vận hành chính thức hoặc bảo đảm tối ưu/SLA cứng.

Kiểm tra sau cấu hình cuối: **134 Django tests PASS**, **7 kiểm thử thuật toán PASS**, Django system check 0 lỗi, `makemigrations --check --dry-run`: No changes detected. Có một regression mới cho dự trữ 0,8 giây: không mở quỹ đạo khi thời gian còn lại dành cho hoàn tất, vẫn giữ nghiệm hợp lệ; kiểm tra benchmark đối chiếu tổng pha với worker và SQL là phần con của tail. Test hàng đợi thực xác nhận mặc định Greedy-first/CP budget-aware/Adaptive, tối đa ba khởi tạo.

Nguồn: [JSON xác nhận 30 lượt](experiments/gd_confirmation_15.json), [JSON kiểm chứng dự trữ 12 lượt](experiments/audit_reserve_15.json), [báo cáo raw đợt mới](../outputs/audit_reserve_confirm_15/report.md). Raw kết quả cũ và mới đều giữ nguyên, không chạy lại/chọn lại seed để thay thế một lượt bất lợi.

## File nên commit và artifact cần giữ riêng

Chưa thực hiện `git add`, commit, push hoặc merge. Trước bước 3.4 đã có nhiều
file sửa/untracked từ các bước trước; không coi toàn bộ Git diff là thay đổi
mới của bước này. Đề xuất chia thành các nhóm review sau, trên nhánh `quang`:

| Nhóm | Đường dẫn nên đưa vào commit | Lý do |
|---|---|---|
| Lõi đã kiểm chứng | `backend/config/settings.py`, `backend/school/auto_schedule.py`, `quality_search.py`, `great_deluge.py`, `search_budget.py`, `soft_score.py` | Cấu hình, sinh nghiệm, điều phối, hàm điểm dùng chung; giữ CP-SAT/audit hiện có |
| Regression | `backend/school/tests.py`, `test_quality_search.py`, `test_gd_budget.py` | Kiểm tra Multi-start, audit/fallback, CP admission, GD và budget |
| Tên chức năng từ bước trước | `backend/school/templates/school/auto_schedule.html`, `ui_shell.html` | Một chức năng Xếp lịch chất lượng; bước 3.4 không sửa UI |
| Công cụ thực nghiệm | `backend/school/quality_experiment.py`, `management/commands/benchmark_auto_schedule.py`; `analysis/compare_quality_search.py`, `compare_initial_generation.py`, `compare_cp_policy.py`, `compare_gd_policy.py`, `compare_audit_reserve.py`, `audit_quality_reports.py`, `prepare_quality_experiments.py`, `cp_build_observations.json`, `baselines/great_deluge_3_1_2.py` | Tái lập đối chứng, dữ liệu mềm, audit độc lập và baseline cố định |
| Tài liệu và bằng chứng nhỏ | `backend/README.md`, `docs/luong_xep_lich_tu_dong.md`, `docs/xep_lich_chat_luong_multi_start.md`, `sinh_nghiem_greedy_first.md`, `quyet_dinh_cp_sat.md`, `great_deluge_ngan_sach.md`, tài liệu này, `docs/experiments/*.json` | Chương 3, cấu hình, giới hạn, kết quả có provenance/checksum |
| Mẫu mô phỏng tái lập | `samples/sgu_15_khoa_soft/README.md` và ba thư mục bo_01/02/03 | Tổng khoảng 0,52 MiB, không phải dữ liệu lớn; workbook nguyên byte + sidecar để chạy ngay. Có thể tái tạo bằng script thay vì lưu bản sao nếu thống nhất cách đóng gói |

`analysis/ui_browser.cjs`, `analysis/ui_preview.py` là công cụ preview UI có sẵn,
để riêng khỏi commit thuật toán. Không đưa `.venv`, `__pycache__`, `.env`, database
thật hoặc benchmark, log, screenshot tạm, ZIP release và toàn bộ `outputs/` vào Git.
`.gitignore` hiện đã bỏ qua `outputs/` và `*.sqlite3`; không dùng `git add -f`.
Giữ raw JSON/SQLite ở kho artifact hoặc thư mục riêng để đối chứng, chỉ commit
bản tổng hợp nhỏ có checksum. Không cần migration, schema, API hoặc thay quy trình duyệt.

## Giới hạn cần ghi trong Chương 3

- Ba bộ mô phỏng, năm seed/bộ, một mức ngân sách và một môi trường. Chưa kiểm
  chứng độ nhạy theo tải máy/phân bố miền lựa chọn/dữ liệu thực tế.
- Seed khác có khả năng tạo nghiệm khác; không bảo đảm độc lập thống kê hoặc
  luôn tạo lịch khác. Năm seed không phải năm dữ liệu độc lập.
- CP-SAT không chạy trong xác nhận 30 lượt: không suy ra CP-SAT kém hiệu quả trên
  mọi trường hợp. Profile có quan sát dựng mô hình bị cắt là cận dưới thời gian,
  không phải số đo mô hình hoàn tất hay bảo đảm thời gian trên máy khác.
- Ngân sách là deadline hợp tác của tìm kiếm. Không bảo đảm SLA toàn luồng cứng,
  không bỏ audit khi hết thời gian. Nhánh không có nghiệm còn có chi phí diagnose.
- Chưa thêm mục tiêu cân bằng giờ giảng; tổng tiết trên lịch không đồng nhất giờ
  quy đổi. Các trọng số mềm là lựa chọn của mô hình mô phỏng.
- Chỉ đo SQLite trên máy hiện tại; SQL Server và cạnh tranh đa người dùng phải
  được kiểm thử riêng trước triển khai thực tế.
- Mọi ứng viên được xét theo một snapshot, nhưng tài nguyên có thể thay đổi sau
  khi xếp; kiểm tra trước duyệt vẫn cần giữ. Không khẳng định tối ưu toàn cục.

## Lệnh tái lập

```powershell
& .\.venv\Scripts\python.exe backend/manage.py test school --noinput
& .\.venv\Scripts\python.exe -m unittest discover -s tests
& .\.venv\Scripts\python.exe backend/manage.py check
& .\.venv\Scripts\python.exe backend/manage.py makemigrations --check --dry-run
& .\.venv\Scripts\python.exe analysis/prepare_quality_experiments.py --verify
# Dry-run 12 lượt; thêm --run để thực thi. Luôn dùng thư mục mới.
& .\.venv\Scripts\python.exe analysis/compare_audit_reserve.py --output-dir outputs/audit_reserve_check_next
```

Tái lập đúng xác nhận 30 lượt phải đặt rõ dự trữ **0,5 giây**, một CP worker,
profile và toàn bộ cấu hình GD như trong `docs/experiments/gd_confirmation_15.json`;
xem [báo cáo raw 3.3](../outputs/gd_adaptive_confirm_15/report.md) cho lệnh đầy đủ.
Không dùng mặc định môi trường chưa kiểm tra làm điều kiện thực nghiệm.
