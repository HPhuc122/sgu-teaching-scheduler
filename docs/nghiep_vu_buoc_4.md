# Bước 4 — Định mức, cân bằng tải và phân quyền đơn vị

Ngày kiểm chứng: 18/10/2026. Nhánh: `quang`. Chưa commit, push hoặc merge.

Dữ liệu, hệ số, định mức, vai trò và quy trình trong tài liệu này là **mô phỏng do nhóm xây dựng**, không đại diện quy định hoặc quy trình phân công nội bộ chính thức của SGU.

## 1. Phạm vi hoàn thành

| Nghiệp vụ | Đã triển khai | Điều kiện sử dụng |
|---|---|---|
| Định mức và quy đổi | Cấu hình theo giảng viên/học kỳ; hệ số theo loại học phần; báo cáo HTML/XLSX theo khoa, giảng viên, học kỳ và trạng thái | Người quản lý nhập hệ số và định mức mô phỏng rõ ràng |
| Cân bằng tải | Thành phần mục tiêu tùy chọn, dùng chung cho CP-SAT, GD, đánh giá ứng viên và tính lại sau lưu | `balance_weight > 0`, đủ định mức của giảng viên đủ chuyên môn và hệ số liên quan |
| Quyền theo đơn vị | Kiểm tra backend cho API, Django Admin, màn hình rà soát/sửa/duyệt, xuất lịch và báo cáo tải | Cấp `UnitRoleAssignment` tường minh; `is_staff` đơn lẻ không còn đủ quyền |

Giữ một chức năng **Xếp lịch chất lượng**. Luồng mặc định vẫn Greedy-first → CP budget-aware khi đủ điều kiện → tối đa ba khởi tạo → GD Adaptive → chọn nghiệm có điểm thấp nhất đã audit → lưu nguyên tử. Không sửa toán tử lân cận hoặc ràng buộc cứng. Thay đổi GD chỉ là gọi hàm delta dùng chung để tính đúng thành phần tải toàn cục.

## 2. Bảo vệ trạng thái local

Trước khi sửa, đã kiểm tra nhánh `quang` và toàn bộ tracked/untracked chưa commit. Sao lưu tại:

`outputs/source_backup_step4_20261018_145705/`

- `worktree.zip`: 235 file từ `git ls-files --cached --others --exclude-standard`, gồm source, tài liệu và dữ liệu mẫu untracked quan trọng.
- `tracked.patch`: diff nhị phân so với HEAD `25cf8074261ca51500e7e5e1d196753f7040c1f0`.
- `manifest.json`: trạng thái Git ban đầu, HEAD, nhánh và SHA-256 từng file/archive.
- Đã mở archive và xác minh SHA-256 cả 235 file cùng SHA-256 archive.

Không reset/stash/checkout đè, xóa dữ liệu hoặc cập nhật Git index. Archive source không chứa database/output/venv bị Git ignore. Database chính được đọc để tạo một bản sao kiểm thử migration riêng; không migrate hoặc ghi vào database chính.

## 3. Định nghĩa khối lượng

Với buổi `b`, `p_b` là số tiết mỗi buổi, `W_b` là tập tuần thực sự đã lưu:

```text
Tiết thực tế_i = Σ_b (p_b × |W_b|)
L_i = Σ_b (p_b × |W_b| × hệ_số_loại_học_phần_b)
Q_i = làm_tròn_2_chữ_số_định_mức(target_units_i × allocation_fraction_i)
Chênh lệch_i = L_i − Q_i
```

- `TeachingQuota`: định mức học kỳ và tỷ lệ phân bổ 0,01..1; định mức sau phân bổ tối thiểu 0,01. Đây là mục tiêu mềm, không biến thành trần tải cứng.
- `WorkloadPolicy.default_factor`: tùy chọn, **không có hệ số ngầm định**. `ConversionRule` theo `Course.kind` ưu tiên hơn hệ số mặc định.
- Hệ số được kiểm tra trong khoảng 0,01..10; định mức tối đa 100.000 đơn vị; trọng số cân bằng 0..100.
- Mặc định báo cáo cộng cả `ChoDuyet` và `DaDuyet`, có bộ lọc từng trạng thái. Tính từ `ScheduleEntry` và `ScheduleWeek`, không suy ra khối lượng từ tín chỉ.
- Thiếu hệ số: số tiết vẫn biết, nhưng tổng quy đổi và chênh lệch hiển thị **chưa xác định**. Thiếu định mức: hiện cảnh báo, không giả định bằng 0.
- Báo cáo là khối lượng **được xếp**, không phải xác nhận giảng viên đã thực giảng, chấm công hoặc quyết toán thù lao.
- Cấu hình của học kỳ đã khóa chỉ được đọc; chặn cả chuyển cấu hình từ học kỳ đã khóa sang học kỳ mở.

Mở `/workload/` để xem/xuất; cấu hình tại Django Admin hoặc API `/api/teaching-quotas/`, `/api/workload-policies/`, `/api/conversion-rules/`.

## 4. Thành phần cân bằng và phiên bản mục tiêu

Giữ toàn bộ điểm cũ là `S_v1`. Khi bật cân bằng:

```text
S_v2 = S_v1 + weight × Σ_i ceil(L_i² / Q_i)
```

Triển khai số nguyên: `l_i = 100 × L_i`, `q_i = 100 × Q_i`, thành phần mỗi người là `ceil(l_i² / (100 × q_i))`. Định mức hiệu dụng dùng làm tròn HALF_UP. Tải bao gồm lịch cố định và lịch ứng viên; lịch thuật toán đang chờ được thay thế không cộng hai lần.

Chi phí lồi tăng nhanh khi dồn tải vào một người. Với tổng khối lượng cố định, nó khuyến khích phân bổ theo định mức thay vì ép số tiết mọi người bằng nhau. Chuyên môn, ngày nghỉ, khoảng không khả dụng và các xung đột vẫn quyết định tập phương án khả thi. Hệ số, tập chuyên môn và lịch rảnh có thể khiến phân bổ lý tưởng không đạt được. Công thức chưa mô hình hóa số lớp nhận tối đa hoặc miễn giảm theo chức danh ngoài tỷ lệ phân bổ cấu hình.

`SoftScorer.score()` tính tổng; `move_delta()` tính lại đúng hai tải thay đổi; `accept_move()` cập nhật cache khi nhận phép biến đổi. CP-SAT dùng cùng lượng quy đổi và phép chia làm tròn lên. Nếu tải vượt miền số nguyên an toàn của CP, giữ phương án Greedy/audit theo luồng dự phòng hiện có.

`AlgorithmRun.objective_version` và `quality_snapshot` lưu trọng số, định mức hiệu dụng, hệ số, tải cố định và lượng quy đổi của từng yêu cầu buổi. Ba khởi tạo và mọi quỹ đạo dùng cùng scorer/snapshot. Công cụ audit sau lưu khôi phục snapshot để tính lại điểm, không đọc lại trọng số/định mức mới. Nguyện vọng tiếp tục dùng snapshot hiện có. Audit ràng buộc cứng `audit_solution()` giữ nguyên.

Mặc định `weight=0` → `soft_v1`, điểm cũ giữ nguyên. Bật `weight>0` → `soft_v2_workload`. Khi thiếu định mức/hệ số cần thiết, chạy mới báo lỗi cấu hình thay vì âm thầm dùng công thức khác; lịch cũ không bị thay bằng lịch lưu dở. Cần nhập danh mục giảng viên và cấu hình định mức trước khi bật cân bằng cho các giảng viên mới trong workbook.

**Không so sánh trực tiếp tổng điểm v2 với benchmark v1 trước đây.** Khi đánh giá v2, giữ cùng dữ liệu, cấu hình tải, snapshot, seed, ngân sách và phiên bản source; báo riêng điểm cũ và thành phần cân bằng. Chưa có thực nghiệm thống kê xác nhận trọng số phù hợp trên ba bộ SGU lớn.

## 5. Ma trận quyền mô phỏng

Các tài khoản nghiệp vụ phải active, có `is_staff=True` và grant hợp lệ; `superuser` active luôn là quản trị hệ thống. `can_manage=False` của các vai trò đơn vị chỉ cấp xem. Vai trò ADMIN có toàn quyền hệ thống.

| Vai trò | Phạm vi | Xem/xuất | Thêm/sửa/xóa danh mục đơn vị và định mức | Đề xuất/sửa lịch | Duyệt lịch | Tài khoản/quyền |
|---|---|---|---|---|---|---|
| ADMIN / superuser | Toàn hệ thống | Có | Có | Có | Có | Có |
| FACULTY | Khoa được cấp | Có trong khoa | Có khi `can_manage`; tuân thủ bảo vệ dữ liệu liên quan | Có khi `can_manage` | Không | Không |
| HEAD | Bộ môn được giao | Có trong bộ môn | Không | Thêm/sửa khi `can_manage`, không xóa | Không | Không |
| TRAINING | Toàn hệ thống hoặc khoa/bộ môn được cấp | Có trong phạm vi | Khi `can_manage`; thao tác gốc cấp khoa cần grant cấp khoa | Có khi `can_manage` | Có khi `can_manage` trong phạm vi | Không |
| Giảng viên thông thường | Hồ sơ đã liên kết của mình | Lịch đã duyệt, nguyện vọng và báo cáo tải của mình | Không | Gửi nguyện vọng theo luồng cũ | Không | Không |

Các quy tắc bổ sung:

- Nhập workbook và chạy pipeline tự động có thể tác động nhiều đơn vị, nên chỉ ADMIN hoặc TRAINING toàn hệ thống có quyền quản lý được thực hiện. TRAINING phạm vi nhỏ điều phối/duyệt lịch qua màn hình/API trong phạm vi, không được ngầm mở rộng quyền bằng workbook.
- Danh mục dùng chung (học kỳ, phòng, tòa, tiết, chính sách/hệ số tải) được đọc bởi vai trò đơn vị; chỉ quản trị/điều phối toàn hệ thống được ghi. Cán bộ khoa có thể quản lý định mức cá nhân trong khoa, không đổi trọng số chung.
- Lịch và liên kết hai phía phải thuộc phạm vi của cả học phần lẫn giảng viên/lớp liên quan; phân công chéo đơn vị cần điều phối có đủ phạm vi.
- Nhiều grant được hợp theo **từng hành động và loại dữ liệu**, không biến quyền xem từ vai trò HEAD thành quyền sửa danh mục của vai trò FACULTY ở khoa khác.
- API lọc queryset trước khi lấy ID, kiểm tra quan hệ trước ghi. Django Admin giới hạn queryset/FK, kiểm tra quyền từng đối tượng và cả cây dữ liệu liên quan trước xóa. URL/filter/ID cố ý sửa không vượt được phạm vi.
- Lớp hành chính cũ chưa có `department` chỉ dành cho điều phối toàn hệ thống. Không tự suy đoán đơn vị để cấp quyền. Admin đã có trường gán bộ môn cho lớp.
- Quyền Django model hoặc `is_staff` đơn lẻ không thay thế grant nghiệp vụ. Không tự chuyển mọi staff cũ thành ADMIN.

## 6. File, model và hàm chính của Bước 4

| Nhóm | File và điểm thay đổi |
|---|---|
| Schema | `backend/school/models.py`: `TeachingQuota`, `WorkloadPolicy`, `ConversionRule`, `UnitRoleAssignment`, `SemesterConfiguration.clean`, metadata mục tiêu `AlgorithmRun`, đơn vị của `Cohort`; migration `0012_workload_and_unit_roles.py` |
| Khối lượng | `backend/school/workload.py`: `save_configuration`, `workload_rows`, `BalanceObjective`; `workload_views.py:workload_report`; `templates/school/workload_report.html` |
| Mục tiêu | `soft_score.py:SoftScorer`; `auto_schedule.py:_build_cp_model`, `solve`, `run_from_workbooks`; `quality_search.py:search_quality`; `great_deluge.py:improve`/vòng cập nhật điểm |
| Quyền tập trung | `access.py`: `scoped`, `allowed_departments`, `check_write`, `check_delete`, `require_object`; `access_middleware.py:UnitAccessMiddleware`; `config/settings.py` gắn middleware |
| API và lưu/duyệt | `views.py:AdminViewSet`, ba viewset cấu hình, `portal`; `serializers.py`; `services.py:save_schedule_entry`, `approve_schedule_entries`; `schedule_queue.py:enqueue_schedule`; `auto_schedule.py:approve_algorithm_run` |
| Admin và báo cáo | `admin.py:SchoolModelAdmin`, admin cấu hình/quyền và lớp hành chính; `review_views.py`, `export_views.py`, `faculty_timetable.py`, `templatetags/school_ui.py`, `ui.py`, `templates/school/ui_shell.html` |
| Đường dẫn | `backend/config/urls.py`, `backend/school/urls.py` |
| Kiểm chứng | `test_workload_access.py`; điều chỉnh fixture/quyền và chữ ký mock trong `tests.py`, `test_ui.py`, `test_quality_search.py`, `test_gd_budget.py` |
| Thực nghiệm | `management/commands/benchmark_auto_schedule.py`: profile tải và fingerprint source; `analysis/compare_workload_objective.py`; `analysis/compare_quality_search.py:run_job`; `analysis/audit_quality_reports.py:audit_saved_report` |

Phần sửa lưu lịch còn bổ sung ánh xạ PK sau `bulk_create` nếu backend không trả PK và thống nhất thứ tự khóa Semester → AlgorithmRun khi duyệt. Có kiểm thử mô phỏng PK thiếu và rollback khi insert tuần thất bại. Đây **không phải** bằng chứng đã kiểm thử SQL Server.

Danh sách trên là phần công việc Bước 4. Git status còn có nhiều file cải tiến thuật toán/tài liệu đã tồn tại từ các bước trước và được giữ nguyên trong backup; không coi toàn bộ diff từ HEAD là mới tạo ở Bước 4.

## 7. Kết quả kiểm chứng

- Toàn bộ **172 kiểm thử Django PASS**, gồm 38 kiểm thử tích hợp mới cho khối lượng/quyền; chạy trên SQLite test riêng.
- **7 kiểm thử thuật toán độc lập PASS**.
- `manage.py check`: không có lỗi.
- `makemigrations --check --dry-run`: không phát hiện thay đổi model chưa có migration.
- `git diff --check`: không có lỗi khoảng trắng của tracked diff; đã kiểm tra riêng các file mới.
- Kiểm thử gồm: số tiết/quy đổi/thiếu cấu hình, định mức khác nhau, delta so với tính tổng, CP-SAT thật và GD thật với mục tiêu v2, lưu snapshot/tính lại sau sửa cấu hình, hàng đợi/lưu/duyệt, lỗi lưu tuần rollback giữ lịch trước, thiếu PK bulk insert; truy cập ID/FK/URL/XLSX trái phạm vi, xóa cascade liên quan đơn vị khác, nhiều grant, tự nâng quyền, học kỳ khóa và rollback duyệt theo lô.
- Migration `0012` chạy trên **bản sao SQLite chính** `outputs/step4_migration_check_02/migration_copy.sqlite3`; đối chiếu giá trị và số lượng tất cả dòng cũ của **29 bảng** bằng SHA-256 theo các cột trước migration: giữ nguyên. `PRAGMA integrity_check=ok`, `foreign_key_check=[]`, SHA-256 database chính không đổi. Bản chính không có AlgorithmRun nên kiểm chứng chuyển run v1 thực hiện bằng test fixture; không suy diễn đã có run lịch sử trong database đó.
- Lần kiểm tra migration copy `_01` đã apply migration được nhưng công cụ hậu kiểm dùng sai tên bảng `school_algorithmrun`; đã sửa thành tên thật `LanChayThuatToan` và kiểm chứng hoàn chỉnh trên bản sao mới `_02`. Không sửa migration vì lỗi này.

### Smoke baseline riêng cho mục tiêu tải

Kết quả cuối: `outputs/workload_v2_smoke_02/`; bản JSON gọn có thể đưa Git: `docs/experiments/workload_v2_smoke.json`.

Cùng workbook và sidecar theo SHA-256, seed 42, 12 buổi, ngân sách 5 giây, tối đa ba khởi tạo, một CP worker, Greedy-first/CP budget-aware/GD Adaptive. Hệ số minh họa 1, định mức 40/80/120 luân phiên được cấu hình tường minh; chỉ khác trọng số cân bằng 0/1.

| Chỉ tiêu | weight=0 / soft_v1 | weight=1 / soft_v2_workload |
|---|---:|---:|
| Lịch audit hợp lệ | 12/12 buổi | 12/12 buổi |
| Hard Penalty | 0 | 0 |
| Thời gian enqueue + worker | 2,554s | 2,857s |
| Audit độc lập sau lưu (ngoài worker) | 0,046750s | 0,041683s |
| Tổng điểm theo **hai định nghĩa riêng** | 1 | 204 |
| Thành phần điểm cũ | 1 | 12 |
| Σ ceil(L²/Q), tính mô tả cùng công thức tải | 502 | 192 |
| Số giảng viên có phân công | 5 | 12 |
| Số tiết lớn nhất của một giảng viên | 96 | 64 |

Không lấy `204 − 1` làm mức cải thiện/chênh lệch chất lượng giữa hai mục tiêu. Kết quả thể hiện đánh đổi: thành phần cân bằng thấp hơn nhưng điểm sở thích/chuyên môn cũ tăng. Tổng tiết vẫn 384 ở cả hai lịch. Hai audit mở DB chỉ đọc và xác nhận fingerprint lịch cùng điểm tính lại; DB không thay đổi.

Smoke `_01` trước đó cũng audit PASS 2/2, nhưng dùng `_02` làm mốc cuối vì fingerprint benchmark đã bổ sung module `workload.py`. Các lần smoke dùng thư mục mới, không ghi đè. Chưa chạy lại 45/180 lượt, chưa chứng minh trọng số 1 tốt nhất hoặc hiệu quả trên ba bộ lớn.

### Lệnh tái kiểm tra

Từ thư mục gốc, sau khi kích hoạt môi trường Python của dự án:

```powershell
& .\.venv\Scripts\python.exe -B backend\manage.py test school --noinput
& .\.venv\Scripts\python.exe -B -m unittest discover -s tests
& .\.venv\Scripts\python.exe -B backend\manage.py check
& .\.venv\Scripts\python.exe -B backend\manage.py makemigrations --check --dry-run

# Dry-run; thư mục phải chưa tồn tại.
& .\.venv\Scripts\python.exe -B analysis\compare_workload_objective.py --output-dir outputs/workload_review_03
# Đúng hai lượt nhỏ; tự tạo workbook/sidecar/profile và SQLite riêng.
& .\.venv\Scripts\python.exe -B analysis\compare_workload_objective.py --output-dir outputs/workload_review_03 --run
```

## 8. Migration và triển khai SQLite an toàn

Cần migration **0012**. Đã tạo và kiểm chứng trên test DB/bản sao; **chưa áp dụng database chính**. Code mới chưa thể chạy đầy đủ trên schema chính cũ cho đến khi triển khai migration.

1. Dừng nhận tác vụ mới và chờ worker đang chạy hoàn tất; bảo toàn uploaded files, lịch và báo cáo cũ.
2. Sao lưu SQLite bằng SQLite backup khi có kết nối hoạt động, hoặc copy database sau khi dừng mọi tiến trình dùng DB; giữ bản backup riêng và kiểm tra khả năng đọc. Không chỉ copy file `.sqlite3` đang ở WAL mà bỏ qua nội dung WAL.
3. Xác nhận `UCTP_DB_ENGINE` là SQLite và `UCTP_SQLITE_PATH` trỏ đúng database dự định triển khai; xem `manage.py migrate --plan` trước.
4. Sau review, vận hành áp dụng `& .\.venv\Scripts\python.exe backend\manage.py migrate --noinput` với môi trường đã xác nhận. Lệnh này là hướng dẫn triển khai, **chưa chạy trên bản chính trong phiên này**.
5. Quản trị active cấp vai trò/phạm vi tường minh qua `/admin/school/unitroleassignment/`; tài khoản nghiệp vụ cần `is_staff=True`. Giữ một superuser hoạt động để không tự khóa quyền quản trị. Không gán ADMIN hàng loạt cho staff.
6. Gán đơn vị lớp hành chính cũ sau khi kiểm tra dữ liệu. Cấu hình định mức và hệ số mô phỏng, kiểm tra báo cáo; chỉ bật cân bằng khi đủ dữ liệu. Giữ weight=0 nếu chưa thống nhất tiêu chí.
7. Chạy smoke trên bản sao trước; sau triển khai kiểm tra đọc báo cáo, quyền và lịch cũ. Khi cần quay lại, dừng app/worker và phục hồi **cặp source/schema tương thích** từ backup; không downgrade migration hoặc phục hồi DB trong lúc worker đang ghi.

Các benchmark SQLite cũ không tự migrate. Công cụ audit mới có đọc trường schema 0012, nên muốn audit DB benchmark cũ phải dùng source tương ứng hoặc migrate **bản sao** của DB đó.

## 9. Git và đề xuất commit

Chưa `git add`, commit, push hoặc merge. Nhánh vẫn `quang`.

Nên review và đưa vào commit tổng hợp:

- Source trong `backend/config`, `backend/school` đã liệt kê, **kèm** các module chất lượng còn untracked từ bước trước (`quality_search.py`, `search_budget.py`, `soft_score.py`, `quality_experiment.py`) và migration `0012`.
- Toàn bộ test liên quan, script benchmark/audit/chuẩn bị thí nghiệm và baseline GD đóng băng cần thiết để tái lập; kiểm tra dependency import trước khi chọn file.
- README, các tài liệu thuật toán bước trước, tài liệu này và `docs/experiments/*.json` đã lược bỏ DB/path riêng/tài khoản.
- `samples/sgu_15_khoa_soft/` là dữ liệu SGU mô phỏng có sidecar để tái lập benchmark; có thể commit nếu nhóm muốn đóng gói fixture, sau khi review provenance và kích thước. Dữ liệu gốc giữ nguyên.

Không đưa vào commit: `backend/db.sqlite3`, mọi database/bản sao benchmark, `outputs/` (kể cả backup), log, môi trường ảo, cache, file secrets. `.gitignore` hiện đã loại các nhóm này. `analysis/ui_browser.cjs`, `analysis/ui_preview.py` là công cụ preview có trước Bước 4; chỉ chọn nếu cần cho quy trình UI, không mặc định coi là dependency thuật toán.

Đề xuất thông điệp commit sau review:

```text
feat: finalize quality scheduling with simulated workload and unit permissions

Add per-semester quotas, configurable conversion and optional workload objective.
Enforce unit scopes across API, admin, review, approval and exports.
Include quality-search implementation, migration, regression tests and experiment docs.
```

**Sẵn sàng để người dùng review và chọn file commit trên quang.** Vận hành bản chính còn cần backup/migration/cấp vai trò/cấu hình theo quy trình trên. Chưa coi là sẵn sàng triển khai diện rộng hoặc tương thích SQL Server đã được chứng minh.

## 10. Hạn chế cần ghi vào báo cáo đồ án

- Mục tiêu v2 là mở rộng nghiệp vụ và thay đổi bài toán đánh giá; thành công của GD Adaptive trong benchmark v1 không tự chứng minh hiệu quả với v2. Cần baseline mới, đo riêng các thành phần và kiểm tra đánh đổi theo nhiều seed.
- Chỉ smoke nhỏ và test tự động đã chạy; chưa có bằng chứng tối ưu toàn cục, tính mới thuật toán hoặc trọng số tối ưu.
- Định mức là mềm; không bảo đảm mọi người đạt định mức hay phần tải bằng nhau. Tính khả thi chuyên môn/lịch rảnh được ưu tiên tuyệt đối.
- Snapshot tải không phải snapshot toàn bộ lịch sử danh mục. Thay đổi mã học phần, chuyên môn hoặc lịch cố định sau chạy vẫn cần audit theo ngữ cảnh phù hợp; không bảo đảm tái lập vô hạn sau mọi thay đổi danh mục.
- API và custom screen đã có regression phạm vi; đây không thay thế một đợt kiểm thử bảo mật độc lập hoặc thử tải đồng thời nhiều người. SQLite không cung cấp khóa hàng như SQL Server.
- SQL Server chưa được kiểm chứng trực tiếp; migration có unique constraint điều kiện và các đường bulk insert/transaction cần kiểm tra trên database SQL Server riêng trước chuyển đổi.
- Ngân sách tìm kiếm là deadline hợp tác; audit/lưu/cập nhật trạng thái và chờ hàng đợi không có hard SLA 15 giây. Bước 4 không sửa kiến trúc deadline/worker, không ép dừng process.
