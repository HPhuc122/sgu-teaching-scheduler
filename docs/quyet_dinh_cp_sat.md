# Bước 3.1.2: quyết định đầu tư cho CP-SAT

Từ bước 3.2, GD adaptive là mặc định ứng dụng; xem
[great_deluge_ngan_sach.md](great_deluge_ngan_sach.md). Các mô tả GD 3.000 bước
và số đo dưới đây là baseline của bước 3.1.2, được giữ để đối chứng.

Dữ liệu, nguyện vọng và quy trình SGU trong đồ án là mô phỏng. Triển khai trên
`quang`, giữ nguyên ràng buộc, `SoftScorer`, nội dung `audit_solution()`, mô hình
CP-SAT trong `_build_cp_model()`, `_greedy_seed()`, GD, toán tử, 3.000 bước GD,
giới hạn 5 giây mỗi lời gọi GD, số khởi tạo và quy trình lưu/duyệt lịch.

## Vấn đề và đối chứng

Chính sách bước 3.1 là `fixed-window`: khi có Greedy hợp lệ, dành tối đa 5 giây
cho mô hình + solver, chừa 1 giây giải. Nó chỉ kiểm tra thời gian còn lại tối
thiểu, chưa ước lượng xem mô hình có dựng xong trong cửa sổ này hay không.

Trong bộ 18 lượt trước, sáu lượt Greedy-first trên bo_01/bo_02 đều dựng dở mô
hình khoảng 4 giây, không gọi solver. Đây là dữ liệu về cấu hình/máy cụ thể,
không chứng minh CP-SAT nói chung kém hiệu quả.

`fixed-window` được giữ làm đối chứng qua `--cp-policy fixed-window`. Cả đối
chứng và chính sách mới đều dùng Greedy-first, cùng seed/dữ liệu, cùng số khởi
tạo và cùng công thức điểm. Kiểm tra an toàn và quy tắc chỉ thay Greedy khi
CP-SAT tốt hơn được dùng chung; đối chứng không phải checkout lịch sử nguyên byte.

## Ngân sách và quyết định mới

`quality_search.search_quality()` giữ cách chia thời gian cho tối đa ba khởi
tạo, không vay thời gian dành cho các lượt sau. Trong mỗi lượt có thời gian T:

- Dự trữ GD: `min(QUALITY_GD_RESERVE_SECONDS, 20% T)`, mặc định 1 giây.
- Dự trữ audit của driver: `min(QUALITY_AUDIT_RESERVE_SECONDS, 10% T)`, mặc định
  0,5 giây. GD phải dừng trước phần này; audit vẫn bắt buộc nếu vượt dự trữ.
- Deadline sinh nghiệm là mốc sớm hơn giữa 80% T và thời điểm sau khi đã trừ hai
  khoản dự trữ. Greedy dùng tối đa 25% thời gian sinh nghiệm còn lại ở lượt có
  thể gọi CP-SAT, sau đó được audit độc lập như trước.
- Khi trả S0 sớm, phần chưa dùng của sinh nghiệm được trả lại cho quỹ GD của
  lượt. Giới hạn GD hiện tại vẫn giữ nguyên; không thêm đường GD hoặc khởi tạo.

`auto_schedule.solve()` sau khi Greedy đã được kiểm tra:

1. Giữ ngưỡng cũ: từ 500 buổi hoặc lượt sau không dựng CP-SAT.
2. `estimate_cp_build()` lập ước lượng từ số buổi, prior cấu hình và các quan
   sát cùng số buổi, nhân hệ số dự phòng. Không coi timeout là thời gian dựng
   xong mô hình; đó là quan sát bị cắt, chỉ cho biết cận dưới.
3. Lấy số giây thực sự còn lại đến deadline sinh nghiệm, trừ dự trữ audit ứng
   viên CP-SAT (mặc định 0,5 giây, riêng với audit driver).
4. Nếu đã có Greedy, chỉ nhận CP-SAT khi đủ ước lượng dựng mô hình **cộng** thời
   gian giải tối thiểu (mặc định 1 giây). Thiếu thời gian: không tạo `CpModel`,
   `cp_decision=SKIPPED_BUDGET`, `cp_skip_reason=SKIPPED_BUDGET`,
   `cp_called=false`, `cp_status=NOT_CALLED`.
5. Nếu đủ, cấp thời gian CP là số nhỏ hơn giữa phần còn dùng được và
   `max(cửa_sổ_cũ, ước_lượng_dựng + thời_gian_giải_tối_thiểu)`. Nhờ vậy mô hình
   lớn vẫn có cơ hội chạy khi tổng ngân sách thực sự đủ, thay vì luôn bị cửa
   sổ 5 giây chặn. Solver còn chịu `cp_time_limit` và deadline chung.
6. Nếu **chưa có Greedy hợp lệ**, cho phép `RUN_RESCUE` dù ước lượng có thể
   vượt ngân sách, miễn còn tối thiểu thời gian cho solver và audit. Đây là thử
   cứu tính khả thi có kiểm soát, không bảo đảm sẽ dựng xong. Dựng/giải vẫn bị
   giới hạn; thất bại không bị diễn giải thành chứng minh vô nghiệm.
7. Audit và đối chiếu điểm của nghiệm CP-SAT. Chỉ thay Greedy khi điểm mềm
   **nhỏ hơn**. Bằng điểm giữ nguyên Greedy và trạng thái `HEURISTIC`; không
   gán nhãn `OPTIMAL` cho nghiệm heuristic chỉ vì solver tìm được nghiệm bằng điểm.
8. Timeout dựng mô hình/hint, solver trả `UNKNOWN`, bị ngắt hoặc lỗi runtime
   không làm mất Greedy hợp lệ. `UNKNOWN` chỉ là trạng thái solver khi đã gọi
   và thật sự nhận UNKNOWN; bị ngắt/lỗi được ghi riêng.

Deadline là cơ chế hợp tác, không phải ngắt cứng. Thời gian gọi OR-Tools, giải
phóng mô hình, audit, chẩn đoán, DB và I/O có thể vượt mốc dự kiến. Ưu tiên giữ
lịch hợp lệ, không bỏ audit để ép đáp ứng thời gian.

## Hồ sơ quan sát và cấu hình

`analysis/cp_build_observations.json` chứa sáu quan sát Model-first có nguồn và
SHA256 từ bộ 18 lượt bước 3.1.1: ba ở 240 buổi, ba ở 480 buổi. Chỉ một quan sát
240 buổi là dựng xong; năm còn lại là cận dưới do timeout. Không tạo số đo giả.

Hồ sơ được chỉ định rõ qua `UCTP_QUALITY_CP_BUILD_PROFILE` hoặc tùy chọn benchmark
`--cp-build-profile`; ứng dụng không tự quét `outputs/`. Nếu không chỉ định,
dùng prior 0,04 giây/buổi, hiệu chỉnh từ quan sát đã dựng xong 9,586401 giây/240
buổi. Hệ số dự phòng mặc định 1,25. Ước lượng:

`max(0,05 giây; số_buổi × prior; thời_gian_quan_sát_lớn_nhất_cùng_số_buổi) × hệ_số`

Hồ sơ này cho ước lượng 12,41078375 giây ở 240 buổi và 24 giây ở 480 buổi khi
dùng prior mặc định. Đây là **ước lượng điều phối**, không phải thời gian đo
được của mô hình hoàn chỉnh, đặc biệt ở 480 buổi chưa có quan sát hoàn chỉnh.
Số phòng, chuyên môn, miền thời gian, máy và phiên bản OR-Tools có thể làm prior
sai. Cần hiệu chỉnh nếu thay đổi cấu trúc bài toán hoặc môi trường.

| Biến môi trường | Mặc định | Ý nghĩa |
|---|---:|---|
| `UCTP_QUALITY_CP_BUILD_PROFILE` | không có | Hồ sơ JSON tùy chọn |
| `UCTP_QUALITY_CP_MODEL_SECONDS_PER_SESSION` | 0.04 | Prior thời gian dựng theo buổi |
| `UCTP_QUALITY_CP_ESTIMATE_SAFETY_FACTOR` | 1.25 | Hệ số dự phòng, tối thiểu 1 |
| `UCTP_QUALITY_CP_REFINEMENT_SECONDS` | 5 | Cửa sổ cũ; mốc cấp thời gian cơ sở của chính sách mới |
| `UCTP_QUALITY_CP_MIN_SOLVE_SECONDS` | 1 | Thời gian giải tối thiểu |
| `UCTP_QUALITY_GD_RESERVE_SECONDS` | 1 | GD dự trữ cho mỗi lượt |
| `UCTP_QUALITY_AUDIT_RESERVE_SECONDS` | 0.5 | Audit dự trữ, riêng cho ứng viên CP và driver |

Không có chế độ mới trên giao diện hoặc thay đổi schema/API.

## Telemetry và kiểm chứng việc dùng thời gian

`generation` lưu `sessions`, `cp_policy`, `cp_decision`, nguồn nghiệm, trạng thái
solver, thời gian thực tế từng pha, `cp_model_complete`, ước lượng và nguồn
ước lượng, số quan sát bị cắt, thời gian còn lại/có thể dùng/cần có, dự trữ audit,
thời gian cấp CP, deadline dựng và giải. Đây là deadline monotonic nội bộ.

Driver lưu `budget`, `generation_unused_seconds`,
`gd_available_after_generation_seconds`, `gd_allocated_seconds`, `gd_calls`,
`improvement_seconds`, `gd_unused_seconds`, các audit sau GD và audit khi chọn.
Không cộng các pha con thêm lần nữa vào `generation_seconds`.

Có thêm thời gian dành được cho GD không đồng nghĩa GD đã sử dụng hết. Nếu GD
chạy đủ 3.000 bước trước hạn, nó vẫn kết thúc như trước. Bước này không tăng số
bước, số đường GD hoặc số khởi tạo để cố tiêu thụ ngân sách. Báo cáo phải phân
biệt thời gian cấp, dùng thực tế, điểm giảm và phần bỏ trống; không coi phần
thời gian kết thúc sớm là cải thiện chất lượng lịch.

## Kiểm thử và lệnh smoke

Các kiểm thử bao phủ bỏ qua trước dựng mô hình, CP thực sự chạy khi đủ thời gian,
nghiệm tốt hơn/kém hơn/bằng Greedy, quan sát bị cắt, dự trữ các pha, timeout
dựng/hint, UNKNOWN hoặc ngắt solver, cứu tính khả thi khi không có Greedy và
thời gian trả lại cho GD với tham số GD giữ nguyên.

Xem kế hoạch bốn lượt, chưa chạy solver:

```powershell
& .\.venv\Scripts\python.exe analysis/compare_cp_policy.py --budget-seconds 15 --seed 42 --repeats 1 --strategy single
```

Thực thi với thư mục mới; dùng cùng cấu hình môi trường như báo cáo hoặc đặt rõ
các biến trong bảng trên. Mặc định script dùng hồ sơ quan sát kèm dự án:

```powershell
& .\.venv\Scripts\python.exe -u analysis/compare_cp_policy.py --budget-seconds 15 --seed 42 --repeats 1 --strategy single --output-dir outputs/cp_admission_check_new --run
```

Mặc định hai bộ bo_01/bo_02 × hai chính sách, tổng ngân sách tìm kiếm 60 giây,
chưa gồm tạo DB và I/O. Đảo thứ tự chính sách giữa hai bộ. Mỗi lượt dùng SQLite
mới, từ chối ghi đè, không dùng DB ứng dụng. Giữ hash dữ liệu/profile/mã/cấu hình
và thư viện giữa các cặp. `fixed-window` và `budget-aware` chỉ là lựa chọn cho
benchmark; giao diện vẫn có một chức năng Xếp lịch chất lượng.

`compare_initial_generation.py` mặc định `--cp-policy fixed-window` để tiếp tục
đối chứng riêng thứ tự Model-first/Greedy-first như bước trước. Dùng công cụ
`compare_cp_policy.py` khi muốn so riêng quyết định đầu tư CP-SAT.

## Kết quả kiểm chứng nhỏ ngày 18/10/2026

121 kiểm thử Django và 7 kiểm thử thuật toán qua; system check sạch, không có
thay đổi migration. Bốn lượt smoke được lưu riêng tại
`outputs/cp_admission_smoke_01/`; xem
[báo cáo và số đo từng pha](../outputs/cp_admission_smoke_01/report.md).

Ở bo_01, thời gian sinh nghiệm cũ/mới là 4,143503/0,097247 giây; toàn luồng
6,071/2,036 giây; điểm cả hai cùng 1066 → 998. Ở bo_02, sinh nghiệm
4,224757/0,133083 giây; toàn luồng 7,681/3,795 giây; cùng điểm 2056 → 2014.
Chính sách mới đều SKIPPED_BUDGET trước dựng mô hình; bốn lượt đều NOT_CALLED.
Audit độc lập sau lưu: 4/4 PASS, database không đổi.

GD đều được cấp 5 giây, thực dùng khoảng 0,24–0,54 giây với tham số giữ nguyên.
Quỹ thời gian khả dụng cho GD tăng, nhưng không có thêm lời gọi/bước GD để dùng
hết phần dư và không có điểm tốt hơn. Lợi ích được kiểm chứng trong smoke này
là giảm dựng mô hình vô ích và giảm thời gian chờ; không gọi đó là cải thiện
chất lượng hoặc bằng chứng CP-SAT kém hiệu quả trên mọi trường hợp.
