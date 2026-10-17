# Thiết kế lại giao diện SGU Teaching Scheduler

## Phạm vi và kết quả audit

- Xác thực: `/login/`, `/admin/login/`, đăng xuất POST, đổi mật khẩu và xác nhận đổi mật khẩu của Admin.
- Tổng quan: `/admin/`, trang ứng dụng `school` và `auth`.
- Danh mục: danh sách, bộ lọc, tìm kiếm, thêm, sửa, xem chỉ đọc, lịch sử, xác nhận xóa đơn và hàng loạt của 13 model School và Users/Groups.
- Nghiệp vụ: xếp lịch tự động, kết quả/hàng đợi, rà soát/duyệt, sửa buổi dạy, thời khóa biểu khoa, xuất phân công, ba loại nhập danh mục và nhập lịch ngoại lệ.
- Giảng viên: cổng lịch dạy/nguyện vọng và thông báo chưa liên kết hồ sơ.
- API `/api/`: giữ nguyên giao diện và hợp đồng DRF; đây là API kỹ thuật, không phải màn hình tác nghiệp.

Vấn đề ban đầu: 11 trang tự khai báo CSS cùng một partial ghi đè bằng `!important`; Admin và nghiệp vụ dùng hai layout khác nhau; sidebar thiếu danh mục và không kiểm tra quyền model; theme tối không đổi hết màu bảng/form; chưa có dashboard thống kê; form model còn nhãn tiếng Anh và chưa chia nhóm; widget quyền quá rộng; bảng và thông báo chưa có quy ước dùng chung.

## Design system

Template Django và static CSS/JavaScript thuần, không thêm dependency frontend. Nền sáng, sidebar navy, hành động xanh dương, điểm nhấn teal; font hệ thống hỗ trợ tiếng Việt. Token màu, khoảng cách, bo góc và focus dùng chung. Giao diện tối dùng cùng token và đồng bộ `data-theme` của Admin. Bảng rộng cuộn trong khung; điều hướng chuyển thành drawer trên tablet/điện thoại. Giữ widget, tên field, POST, CSRF và xác nhận xóa của Django.

## Giới hạn nghiệp vụ

Chỉ trình bày trạng thái thực từ backend. Không dựng phần trăm tiến độ. Luồng xếp lịch vẫn gửi ba file một lần; kiểm tra và tham số mô tả đúng khả năng backend. Không sửa bộ giải, model, migration, URL, API hoặc cơ chế cấp quyền. Dashboard chỉ đọc số liệu thật và giới hạn theo quyền truy cập model.

## Kiểm thử

Đã kiểm tra ngày 17/10/2026 trên Windows, Django 5.2.18, SQLite và Edge headless:

| Kiểm tra | Kết quả |
| --- | --- |
| `python backend/manage.py check` | Không có lỗi |
| `python backend/manage.py test school --noinput` | 66/66 bài qua; gồm 54 bài có sẵn và 12 bài hồi quy giao diện |
| `python -m unittest discover -s tests` | 7/7 bài qua |
| `python backend/manage.py makemigrations --check --dry-run` | `No changes detected` |
| `git diff --check` và `node --check` | Qua |
| Trình duyệt sau thay đổi | 240 lượt trang: 60 URL × 4 kích thước; không tràn viewport, lỗi JavaScript hoặc lỗi tải static |
| Trình duyệt trước thay đổi | 120 lượt trang desktop/mobile từ template/Admin tại Git HEAD |

Kích thước kiểm tra: desktop 1440×1000, laptop 1280×800, tablet 768×1024 và mobile 390×844. Đã mở các danh sách, form thêm/sửa của cả 13 model School, Users/Groups; các trang nghiệp vụ, app index, đổi mật khẩu và hai trang đăng nhập. Bộ kiểm thử Django còn mở lịch sử, xác nhận xóa, trang popup, hồ sơ chưa liên kết và trang đăng xuất.

Các kiểm tra tương tác trên trình duyệt gồm: thu gọn sidebar; mở drawer, đóng bằng Escape và trả focus; đổi theme và giữ lựa chọn khi tải lại; tìm quyền bằng tiếng Việt, chọn một quyền và lưu nhóm với đúng quyền đó; chọn/bỏ chọn các buổi chờ duyệt; hiện tên file thực đã chọn; tải Excel qua endpoint thật; báo lỗi workbook hỏng và validation form Admin. Đã xem ảnh sáng/tối, desktop/mobile để rà soát khả năng đọc, bố cục form, bảng và widget quyền.

`analysis/ui_preview.py` tạo **database riêng** `outputs/ui-qa/visual-test.sqlite3`, dùng workbook giả lập có nhãn rõ ràng, chạy bộ giải thật cho 12 buổi và gọi dịch vụ duyệt thật. Dữ liệu này chỉ phục vụ kiểm thử; không được chèn vào database ứng dụng. Các thao tác tạo/sửa/xóa trong test dùng database kiểm thử riêng của Django.

## Màn hình và hành vi đã hoàn thiện

- Dashboard: thống kê thật theo quyền, truy cập nhanh, lịch sử chạy gần đây và trạng thái chưa có dữ liệu.
- Sidebar/topbar: nhóm nghiệp vụ và danh mục, kiểm tra quyền model, tài khoản chỉ có quyền thêm được dẫn tới form thêm; trạng thái trang hiện tại, thu gọn và drawer mobile; tài khoản, đổi mật khẩu khi được phép, đăng xuất POST, theme sáng/tối.
- Django Admin: chung giao diện cho danh sách, tìm kiếm, bộ lọc, phân trang, thêm/sửa/xem, lịch sử, popup và xác nhận xóa. Form của 13 model chia nhóm thông tin, nhãn tiếng Việt, các nút Lưu/Lưu và thêm mới/Hủy rõ ràng; giữ các trường chỉ đọc theo quy tắc hiện có.
- Trạng thái/loại dữ liệu dùng dropdown nhãn tiếng Việt nhưng gửi nguyên mã cũ; giữ được mã ngoài danh sách đang có trong bản ghi cũ. Chỉ đổi widget, không thay đổi validation của trường dữ liệu.
- Users/Groups: giữ form và cơ chế phân quyền của Django; nhãn quyền theo ứng dụng/model/thao tác, tìm kiếm hai danh sách, bố cục gọn và xếp dọc trên mobile. Không cấp thêm quyền tự động.
- Xếp lịch: hướng dẫn sáu bước, tách ba file, tên file đã chọn, cấu hình tuần/ngày thực của học kỳ, lỗi theo file/sheet/dòng, trạng thái hàng đợi/kết quả và các liên kết tác nghiệp. Trang đang tự làm mới không chứa form upload để tránh mất nội dung đang nhập.
- Rà soát: bộ lọc, badge, chọn tất cả buổi có thể duyệt trên trang, số buổi đã chọn và nút duyệt được bật khi có lựa chọn; giữ báo cáo nguyện vọng, cảnh báo và quy tắc khóa học kỳ.
- Thời khóa biểu: màu và nhãn phân biệt loại buổi, lưới thứ/tiết, bộ lọc, liên kết chi tiết và cuộn bảng độc lập trên màn hình nhỏ.
- Nhập/xuất: chuyển giữa ba danh mục, tải mẫu, xem trước, báo lỗi và xác nhận; giữ hợp đồng Excel hiện có và kiểm tra độ đầy đủ khi xuất.
- Cổng giảng viên: lịch đã duyệt, nguyện vọng, học kỳ được chọn đồng bộ với form và thông báo lỗi dùng nhãn tiếng Việt. Đăng nhập, chưa có hồ sơ và đăng xuất dùng cùng hệ thống giao diện.

## Chạy và xem kết quả

Không cần cài dependency frontend hoặc tạo migration. Từ thư mục gốc:

```powershell
$env:UCTP_DEBUG = '1' # chỉ dùng phát triển cục bộ để phục vụ static
& .\.venv\Scripts\python.exe backend\manage.py runserver
```

Worker xếp lịch vẫn chạy riêng như trước:

```powershell
& .\.venv\Scripts\python.exe backend\manage.py process_auto_schedule
```

Ảnh trước/sau nằm trong `outputs/ui-qa/before/` (29 ảnh) và `outputs/ui-qa/after/` (63 ảnh), cùng `checks.json`. Ví dụ:

- [Dashboard trước](../outputs/ui-qa/before/desktop-dashboard.png) / [Dashboard sau](../outputs/ui-qa/after/desktop-dashboard.png).
- [Form phòng học mobile](../outputs/ui-qa/after/mobile-room-add.png).
- [Widget quyền mobile](../outputs/ui-qa/after/mobile-group-add.png).
- [Dashboard tối](../outputs/ui-qa/after/desktop-dark-dashboard.png).
- [Xếp lịch trên mobile](../outputs/ui-qa/after/mobile-auto.png).

Thư mục `outputs/` được Git bỏ qua theo cấu hình sẵn có. Mã tái hiện: `analysis/ui_preview.py` và `analysis/ui_browser.cjs`; Playwright/Edge chỉ dùng cho QA, không phải dependency của ứng dụng. Chạy server QA bằng `python analysis/ui_preview.py --phase after --port 8029`, rồi ở terminal khác chạy `node analysis/ui_browser.cjs after`. Chạy baseline với `--phase before --port 8028` và `node analysis/ui_browser.cjs before`.

## Giới hạn kiểm chứng

Chưa kiểm thử trực tiếp trên SQL Server, Safari/Firefox hoặc thiết bị di động thật. Kiểm tra tương phản bằng token màu và rà soát ảnh, chưa có đánh giá accessibility toàn diện. Backend hiện không cung cấp phần trăm tiến độ thật hoặc thao tác từ chối phương án, nên giao diện chỉ dùng trạng thái và các thao tác được hỗ trợ. Trong triển khai production cần phục vụ static theo cấu hình triển khai của Django; không bật DEBUG ngoài máy phát triển.

## Danh sách file thay đổi

- `analysis/ui_browser.cjs`
- `analysis/ui_preview.py`
- `backend/README.md`
- `backend/config/settings.py`
- `backend/school/admin.py`
- `backend/school/apps.py`
- `backend/school/static/school/css/admin.css`
- `backend/school/static/school/css/ui.css`
- `backend/school/static/school/js/theme.js`
- `backend/school/static/school/js/ui.js`
- `backend/school/templates/school/admin_breadcrumbs.html`
- `backend/school/templates/school/admin_index.html`
- `backend/school/templates/school/auth_base.html`
- `backend/school/templates/school/auto_run_status.html`
- `backend/school/templates/school/auto_schedule.html`
- `backend/school/templates/school/base.html`
- `backend/school/templates/school/edit_schedule.html`
- `backend/school/templates/school/export_assignments.html`
- `backend/school/templates/school/faculty_timetable.html`
- `backend/school/templates/school/icon.html`
- `backend/school/templates/school/import_catalog.html`
- `backend/school/templates/school/import_schedule.html`
- `backend/school/templates/school/login.html`
- `backend/school/templates/school/no_profile.html`
- `backend/school/templates/school/portal.html`
- `backend/school/templates/school/review_schedules.html`
- `backend/school/templates/school/ui_end.html`
- `backend/school/templates/school/ui_shell.html`
- `backend/school/templates/school/ui_styles.html`
- `backend/school/templatetags/__init__.py`
- `backend/school/templatetags/school_ui.py`
- `backend/school/test_ui.py`
- `backend/school/ui.py`
- `backend/school/views.py`
- `backend/templates/admin/app_index.html`
- `backend/templates/admin/app_list.html`
- `backend/templates/admin/base_site.html`
- `backend/templates/admin/change_list.html`
- `backend/templates/admin/filter.html`
- `backend/templates/admin/includes/fieldset.html`
- `backend/templates/admin/login.html`
- `backend/templates/admin/submit_line.html`
- `backend/templates/registration/logged_out.html`
- `docs/ui-redesign.md`
