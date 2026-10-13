# Bản chốt hệ thống phục vụ báo cáo — 13/10/2026

## Phạm vi bản chốt

Hệ thống Django nhận ba workbook Học phần, Phòng học và Giảng viên cho một học kỳ; đưa yêu cầu vào hàng đợi; xếp lịch bằng CP-SAT khi dưới 500 buổi hoặc bằng heuristic từ 500 buổi; thử Great Deluge khi phù hợp; kiểm tra nghiệm độc lập; lưu lịch chờ duyệt. Admin rà soát, duyệt, xem thời khóa biểu theo khoa và xuất Excel phân công. Giảng viên xem hồ sơ, lịch đã duyệt và gửi nguyện vọng. Mẫu nhập/xuất là thiết kế của đề tài, chưa phải biểu mẫu nội bộ chính thức của Trường Đại học Sài Gòn.

## Cách chạy bản trình diễn

Từ thư mục gốc, dùng Python 3.13 và các gói trong `backend/requirements.txt`:

```powershell
& .\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
& .\.venv\Scripts\python.exe backend\manage.py migrate
& .\.venv\Scripts\python.exe backend\manage.py createsuperuser
& .\.venv\Scripts\python.exe backend\manage.py runserver
```

Ở terminal khác, chạy worker:

```powershell
& .\.venv\Scripts\python.exe backend\manage.py process_auto_schedule
```

Admin mở `/admin/auto-schedule/`, chọn học kỳ đã cấu hình tiết và số tuần, tải ba mẫu Excel trên trang, điền dữ liệu rồi tải lên. Không dùng các file mẫu hư cấu làm dữ liệu thật. Giảng viên cần tài khoản được liên kết với hồ sơ giảng viên để dùng `/portal/`. Hướng dẫn đầy đủ nằm ở `backend/README.md`.

## Cổng kiểm tra trước khi đóng băng

| Kiểm tra | Kết quả ngày 13/10/2026 |
| --- | --- |
| `manage.py check` | Không có lỗi cấu hình |
| `makemigrations --check --dry-run` | Không có migration còn thiếu |
| `manage.py test school` | 51/51 bài đạt |
| `unittest discover -s tests` | 7/7 bài đạt |
| 80 buổi cơ sở, seed 42 | `OPTIMAL`, xếp/duyệt/xuất đủ 80/80 |
| 1.000 buổi cơ sở, seed 42 | `HEURISTIC`, xếp/duyệt/xuất đủ 1.000/1.000 |
| 80 buổi, hai buổi mỗi nhóm, nhiều tập tuần | `OPTIMAL`, xếp/duyệt/xuất đủ 80/80 |
| 1.000 buổi, hai buổi mỗi nhóm, nhiều tập tuần | `HEURISTIC`, xếp/duyệt/xuất đủ 1.000/1.000 |
| 1.000 buổi có quá tải đã chứng minh | `INFEASIBLE`, không ghi lịch |
| Sai tên học kỳ khi nhập bộ 1.000 buổi | `ERROR`; benchmark trả mã lỗi khi có `--approve` |

Các báo cáo JSON nằm ở `outputs/freeze_smoke_80.json`, `outputs/freeze_smoke_1000_correct.json`, `outputs/freeze_varied_80_report.json`, `outputs/freeze_varied_1000_report.json`, `outputs/freeze_infeasible_1000_report.json` và `outputs/freeze_smoke_1000_bad_name.json`. Các file SQLite dùng để kiểm thử được tách khỏi cơ sở dữ liệu phát triển và không nằm trong gói chốt.

Ba bản HTML đã render bằng tài khoản giả lập của lượt 80 buổi nằm ở `outputs/screenshots/html/`: trạng thái xếp lịch của admin, màn hình rà soát và cổng giảng viên. Chúng là tư liệu để mở trong trình duyệt và chụp hình khi dàn trang báo cáo; không chứa dữ liệu giảng viên thật.

## Tái hiện kịch bản nhiều tập tuần

```powershell
& .\.venv\Scripts\python.exe backend\manage.py generate_sample_workbooks --output-dir outputs\freeze_varied_80 --sessions 80 --semester-name FREEZE_VARIED_80 --weeks 16 --seed 42 --scenario varied_weeks
```

Trước khi benchmark, đặt `UCTP_SQLITE_PATH` trỏ tới **một SQLite mới riêng** và chạy `migrate` trên chính cơ sở dữ liệu đó. Đặt `UCTP_BENCHMARK=1`, rồi chạy:

```powershell
& .\.venv\Scripts\python.exe backend\manage.py benchmark_auto_schedule --input-dir outputs\freeze_varied_80 --semester-name FREEZE_VARIED_80 --weeks 16 --approve --expect-status OPTIMAL --report outputs\freeze_varied_80_report.json
```

Với 1.000 buổi, đổi tên bộ và học kỳ thành `freeze_varied_1000` / `FREEZE_VARIED_1000`, đổi kỳ vọng thành `HEURISTIC`. Không dùng cùng một SQLite cho hai lần benchmark độc lập nếu muốn so sánh các lần chạy.

## Giới hạn cần giữ nguyên trong báo cáo

- Kết quả `HEURISTIC` là lịch hợp lệ đã qua kiểm tra, chưa được chứng minh tối ưu. `UNKNOWN` không chứng minh vô nghiệm.
- Great Deluge chỉ được tích hợp để thử cải thiện; các lượt benchmark nêu trên có điểm trước và sau bằng nhau. Không báo cáo rằng thuật toán này đã cải thiện điểm trong các lượt đó.
- Bộ giả lập cơ sở có một buổi cho mỗi nhóm và cùng tập tuần 1–16. Kịch bản `varied_weeks` bổ sung hai buổi mỗi nhóm và nhiều tập tuần, nhưng chưa mô phỏng hết quy trình đào tạo thực tế.
- Chưa thử kết nối SQL Server và chưa kiểm thử nhiều người dùng chạy đồng thời trên máy chủ đó.
- Chưa có biểu mẫu phân công giảng dạy nội bộ chính thức hoặc dữ liệu vận hành thật của trường; chưa xác nhận quy tắc giờ giảng quy đổi, định mức tải hay quy trình duyệt nội bộ.

## Tệp đóng băng

`outputs/release/uctp_thesis_freeze_2026-10-13.zip` là bản chụp mã nguồn, tài liệu, dữ liệu mẫu hư cấu và bằng chứng kiểm thử cần cho bản báo cáo. `manifest.json` liệt kê SHA-256 của từng tệp; tệp `.sha256` cạnh ZIP chứa mã băm của gói. Gói không chứa môi trường Python, SQLite, dữ liệu ITC gốc hoặc dữ liệu cá nhân thật. Bản này được tạo vì thư mục làm việc chưa có kho Git.
