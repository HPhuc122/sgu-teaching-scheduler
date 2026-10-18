# Bộ thực nghiệm tiêu chí mềm — dữ liệu mô phỏng

Mỗi `bo_01`, `bo_02`, `bo_03` chứa ba workbook sao chép **nguyên byte** từ
`samples/sgu_15_khoa/` và một `experiment.json`. Không thay đổi bộ gốc, tên học kỳ,
schema workbook, dữ liệu cứng hoặc API nhập liệu.

`experiment.json` chứa mức ưu tiên chuyên môn 1–4 cho từng cặp giảng viên/học phần
và một nguyện vọng khung giờ sáng/chiều, mức 1–4, cho mỗi giảng viên. Seed sinh
tiêu chí lần lượt là 20261018–20261020. Các giá trị này hoàn toàn mô phỏng, không
đại diện nguyện vọng hay quy định nội bộ chính thức của SGU.

Sidecar chỉ được áp dụng khi gọi `benchmark_auto_schedule --experiment-file ...`
trên SQLite riêng. Tải ba workbook lên giao diện thông thường **không tự nhập**
sidecar. Cách này giữ nguyên nghiệp vụ và định dạng ba file của ứng dụng.

Hàm điểm giữ nguyên: phạt ca tối, mức ưu tiên chuyên môn và nguyện vọng khung giờ.
Các mức ưu tiên khác nhau giữa môn nhưng không có giảng viên thay thế có thể chỉ
đóng góp một hằng số; nguyện vọng sáng/chiều tạo thêm khả năng phân biệt các lịch.
Kết quả xác nhận GD và phạm vi diễn giải nằm trong
[tài liệu bước 3.4](../../docs/chot_thuat_toan_3_4.md); không suy rộng cho dữ liệu thực tế.

Kiểm tra bản sao và khả năng tái lập, không chạy solver:

```powershell
& .\.venv\Scripts\python.exe analysis/prepare_quality_experiments.py --verify
```

Để sinh bộ riêng khác, dùng `--output-dir` trỏ đến thư mục chưa tồn tại. Script
không ghi đè thư mục đã có. Xem thiết kế và lệnh thực nghiệm trong
`docs/xep_lich_chat_luong_multi_start.md`.
