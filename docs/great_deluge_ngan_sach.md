# Bước 3.2: Great Deluge dùng ngân sách còn dư

Nhánh `quang`. Dữ liệu, tiêu chí và quy trình SGU là mô phỏng, không phải quy
trình hoặc biểu mẫu nội bộ chính thức. Không khẳng định tối ưu toàn cục.

## Baseline và phạm vi thay đổi

`analysis/baselines/great_deluge_3_1_2.py` là bản chụp nguyên trạng trước bước
3.2, SHA256 `6814ca7b254c44f1c48fef4948e7b83fe857f60c93562073f1aed2e3b650cfe7`.
Không nhập bản chụp vào luồng ứng dụng. Test nạp bản chụp dưới package `school`
và đối chiếu điểm/fingerprint với GD được bổ sung bộ đếm.

Benchmark `--gd-policy baseline` dùng cùng engine có telemetry, nhưng giữ cấu
hình cũ: tối đa 3.000 vòng, 5 giây/quỹ đạo, một quỹ đạo cho mỗi S0 khác nhau
trong Multi-start, không có quỹ đạo bổ sung. Các bộ đếm không thay RNG, quy tắc
mực nước, hàm điểm, phép sinh/chấp nhận lân cận hay kiểm tra ràng buộc.
Instrumentation có chi phí nhỏ; cả hai chính sách đều dùng cùng engine được đo.

`--gd-policy adaptive` là mặc định trong ứng dụng. Giữ nguyên ba toán tử: đổi
giờ/ngày, đổi phòng, đổi giảng viên. Không bổ sung hoán đổi hoặc tiêu chí mới.
Giữ nguyên nội dung SoftScorer, audit_solution, lõi CP-SAT, Greedy-first và chính
sách CP-SAT budget-aware của bước 3.1.2. Không đổi schema, API, giao diện,
phân quyền hoặc duyệt lịch.

## Điều phối hai giai đoạn

1. Tối đa ba khởi tạo độc lập, seed gốc 42/43/44 nếu seed cấu hình là 42. Mỗi
   lượt giữ hạn thời gian riêng để không chiếm quỹ cho các lượt chưa thử.
2. Mỗi S0 khả thi phải qua audit và chấm bằng scorer snapshot chung. Với mỗi S0
   khác nhau, chạy lượt GD đầu như baseline: 3.000 vòng, tối đa 5 giây trong phần
   thời gian của lượt. Nếu trùng S0, ghi DUPLICATE và không lặp quỹ đạo đầu.
3. Chỉ sau khi các lượt sinh nghiệm/GD đầu đã được thử mới chạy pha bổ sung.
   Không sinh nghiệm Greedy/CP-SAT thứ tư. Điểm 0 hoặc chứng minh OPTIMAL vẫn
   cho phép dừng sớm như trước.
4. Lưu S0 bất biến bằng tuple và nghiệm tốt nhất đã audit riêng cho từng khởi
   tạo. Quỹ đạo bổ sung luân phiên từ BEST của khởi tạo và từ S0, với seed mới
   `seed_gốc + số_khởi_tạo + thứ_tự_bổ_sung`. RNG của GD là Random riêng; seed
   bổ sung không được đưa vào CP-SAT.
5. Chia vòng giữa các S0 đủ điều kiện. Mỗi quỹ đạo được tối đa 2 giây và không
   nhiều hơn `(thời_gian_còn_lại − dự_trữ_audit) / số_S0_còn_lượt_trong_vòng`.
   Chừa mặc định 0,5 giây cho audit cuối; không bắt đầu quỹ đạo dưới 0,1 giây.
   Bước 3.4 đã kiểm chứng riêng 0,8 giây nhưng giữ mặc định 0,5 giây;
   xem [quyết định và hạn chế deadline](chot_thuat_toan_3_4.md).
6. Quỹ đạo bổ sung có tối đa 30.000 vòng. Sau 6.000 vòng không giảm điểm tốt nhất
   trong quỹ đạo thì dừng STAGNATION; chấp nhận bước trung gian bằng/xấu hơn vẫn
   theo quy tắc nước cũ, nhưng không đặt lại bộ đếm trì trệ.
7. Mỗi khởi tạo dừng bổ sung sau hai quỹ đạo liên tiếp không cải thiện nghiệm
   tốt nhất của chính nó. Toàn pha dừng khi hết thời gian, không còn khởi tạo
   có cải thiện hữu ích, đạt điểm 0 hoặc đã thử tối đa chín quỹ đạo bổ sung.
8. Mỗi kết quả GD phải audit và đối chiếu điểm độc lập. Chỉ cập nhật BEST khi
   điểm thấp hơn; quỹ đạo tệ hơn/bị loại/lỗi/hết thời gian không ghi đè BEST.
   Mọi S0 và ứng viên đã audit vẫn có trong danh sách dự phòng. Chọn cuối theo
   điểm rồi audit lại; nếu bị loại, xét ứng viên hợp lệ tiếp theo trước khi lưu.

Với `strategy=legacy` của benchmark cũ, giữ một S0 và ba đường GD cũ; không thêm
quỹ đạo adaptive. Công cụ đối chứng GD mới dùng Multi-start ở cả hai phía để
không quy lợi ích do thay số khởi tạo cho thay đổi GD.

## Giới hạn và telemetry

Cấu hình quản trị, không có tùy chọn mới trên giao diện:

| Biến môi trường | Mặc định | Giới hạn |
|---|---:|---|
| UCTP_QUALITY_GD_EXTRA_PATHS | 9 | 0–30, tổng toàn pha bổ sung |
| UCTP_QUALITY_GD_EXTRA_PATH_SECONDS | 2 | >0 và ≤5 giây/quỹ đạo |
| UCTP_QUALITY_GD_EXTRA_ITERATIONS | 30000 | 1–1.000.000 |
| UCTP_QUALITY_GD_STAGNATION_ITERATIONS | 6000 | 1–1.000.000 |
| UCTP_QUALITY_GD_STALE_ROUNDS | 2 | 1–10 quỹ đạo liên tiếp không cải thiện BEST |
| UCTP_QUALITY_GD_MIN_PATH_SECONDS | 0.1 | >0 và ≤ thời gian/quỹ đạo |

`optimization_trials` vẫn có tối đa ba bản ghi `kind=start`. Mọi quỹ đạo nằm
trong `paths` của khởi tạo gốc, có `phase=initial/extra`, `anchor=S0/BEST`, seed,
điểm trước/sau, audit_passed, fingerprint, thời gian và lý do dừng. Các seed
khác nhau tạo đường RNG khác nhau, không bảo đảm lịch khác nhau.

Bộ đếm trong từng `paths`:

- `iterations`: vòng đã thực sự vào, kể cả vòng không sinh được phép biến đổi.
- `proposals`: đã tạo một ứng viên từ toán tử có lựa chọn; gồm đề xuất trùng
  trạng thái hiện tại, trước bước loại no-op/kiểm tra ràng buộc.
- `valid_moves`: ứng viên khác hiện tại và qua kiểm tra hợp lệ.
- `accepted_moves`: bước được quy tắc nước chấp nhận, gồm bước bằng hoặc xấu hơn.
- `score_improvements`: lần giảm điểm tốt nhất của quỹ đạo, không phải mọi bước
  giảm so với trạng thái trung gian.

`stop_reason`: ITERATION_LIMIT, TIME_LIMIT, SETUP_TIME_LIMIT, STAGNATION,
ZERO_SCORE, EMPTY_SOLUTION; quỹ đạo bị lỗi/audit loại ghi REJECTED và error.
`seconds` là thời gian engine; `audit_seconds` riêng; quỹ đạo bổ sung còn có
`wall_seconds`, `extra_sequence`, `start_best_before/after`, `improves_start_best`.
`extra_search_stop_reason` mô tả lý do dừng toàn pha, khác lý do từng quỹ đạo.

Các bản ghi khởi tạo cộng dồn `improvement_seconds`, `extra_gd_seconds`,
`gd_calls`, `gd_allocated_seconds`, `gd_unused_seconds`, audit và score_after.
`initial_round_seconds` giữ thời gian lượt đầu; `seconds` cộng thời gian xử lý
thực tế được tính cho khởi tạo đó, không cộng khoảng chờ khi khởi tạo khác chạy.
Tổng thời gian cấp cho các lời gọi GD có thể lớn hơn ngân sách thực dùng vì các
lời gọi trước trả lại thời gian chưa dùng. Không coi tổng hạn cấp là thời gian
đã tiêu thụ; dùng processing_seconds và improvement_seconds để đánh giá.

Deadline vẫn là cơ chế hợp tác. Một phép kiểm tra lân cận, audit bắt buộc, giải
phóng dữ liệu và lưu DB có thể hoàn tất sau mốc; không bỏ audit để ép đúng giờ.
Chín đường × 30.000 là trần số vòng bổ sung, không phải cam kết sẽ chạy hết.

## Luồng thực tế và kiểm thử

`schedule_queue.process_next_run()` gọi `auto_schedule.run_from_workbooks()`,
rồi `quality_search.search_quality()` với mặc định Greedy-first, CP budget-aware
và GD adaptive. Kiểm thử qua hàng đợi thật, không patch benchmark, kiểm tra cả
ba chính sách và telemetry thực tế. Giao diện vẫn chỉ Xếp lịch chất lượng.

Kiểm thử bao phủ bản chụp baseline, bộ đếm và audit nghiệm thật, giới hạn thời
gian/vòng, trì trệ, chia quỹ, cả ba khởi tạo trước pha bổ sung, seed khác nhau,
luân phiên S0/BEST, không ghi đè điểm tốt bằng điểm xấu, lỗi/timeout/audit loại
và dự phòng khi audit cuối loại ứng viên tốt nhất.

Các kiểm thử hợp đồng GD cũ gọi rõ `gd_policy=baseline`; kiểm thử adaptive và
luồng production được kiểm tra riêng. Không dùng mock để tạo số liệu benchmark.

## Đối chứng nhỏ

Từ gốc dự án, xem kế hoạch bốn lượt chưa chạy solver:

```powershell
& .\.venv\Scripts\python.exe analysis/compare_gd_policy.py --budget-seconds 15 --seed 42 --repeats 1
```

Thực thi bo_01/bo_02, mỗi bộ GD baseline/adaptive, cùng ba khởi tạo, scorer,
Greedy-first, CP budget-aware, sidecar nguyện vọng và audit:

```powershell
& .\.venv\Scripts\python.exe -u analysis/compare_gd_policy.py --budget-seconds 15 --seed 42 --repeats 1 --output-dir outputs/gd_budget_check_new --run
```

Mặc định một CP worker, tổng ngân sách tìm kiếm 60 giây, chưa gồm DB/I/O. Đảo
thứ tự chính sách giữa hai bộ, SQLite mới từng lượt, từ chối ghi đè. Hash dữ
liệu, hồ sơ CP, sáu file thuật toán, cấu hình và môi trường phải khớp trong cặp.
Script còn ghi việc các S0 và quỹ đạo đầu có giống nhau không để phân biệt lợi
ích do pha GD bổ sung. Các công cụ benchmark bước trước dùng GD baseline theo
mặc định của run_job(), giữ nguyên đối chứng trước khi có bước 3.2.

## Kết quả smoke ngày 18/10/2026

133 kiểm thử Django và 7 kiểm thử thuật toán PASS; system check và kiểm tra
migration sạch. Đã chạy đúng bốn lượt bo_01/bo_02, seed gốc 42, ba khởi tạo,
15 giây/lượt. Báo cáo đầy đủ và bộ đếm nằm tại
[outputs/gd_budget_smoke_01/report.md](../outputs/gd_budget_smoke_01/report.md).

bo_01: baseline 3 đường/9.000 vòng, 914 điểm, toàn luồng 2,563 giây; adaptive
12 đường/75.701 vòng, 887 điểm, 7,167 giây. bo_02: baseline 3 đường/9.000 vòng,
1937 điểm, 4,948 giây; adaptive 12 đường/75.598 vòng, 1854 điểm, 13,953 giây.
GD bổ sung thực dùng 4,432961 và 8,615682 giây. S0 và GD đầu giống nhau trong
mỗi cặp, nên lợi ích quan sát được đến từ pha bổ sung; cả bốn lịch audit sau
lưu PASS và H=0. Các đường bổ sung dừng STAGNATION, toàn pha dừng PATH_LIMIT.

Mẫu này chứng minh sử dụng thêm ngân sách và giảm điểm trong hai cặp cụ thể,
chưa đủ khẳng định ổn định trên nhiều seed, bo_03 hoặc dữ liệu vận hành.
