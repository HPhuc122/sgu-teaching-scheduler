# Kiểm thử phân quyền, nguyện vọng và xuất phân công — 18/10/2026

## Phạm vi và dữ liệu

Kiểm thử giao diện bằng các tài khoản giảng viên, trưởng bộ môn, quản lý khoa,
đào tạo cấp khoa, đào tạo toàn trường và người chỉ xem. Các kịch bản thay đổi
nguyện vọng và lịch chạy trên bản sao CSDL trong `outputs/temp/`.
Mật khẩu tài khoản demo, CSDL và file tải xuống không thuộc nội dung đưa lên Git.

## Các lỗi đã sửa

- Biểu mẫu giảng viên và API dùng chung quy tắc: chỉ nhận hai loại nguyện vọng,
  thứ từ 2 đến 8, buổi sáng/chiều/tối, ưu tiên từ 1 đến 4. Ngày không thể dạy
  phải có thứ; ưu tiên khung giờ phải có buổi. Dữ liệu sai không được lưu.
- Giao diện và tệp Excel cấp đơn vị có thông tin kiểm tra độ đầy đủ và cảnh báo
  khi thiếu dữ liệu yêu cầu. Phạm vi đơn vị được ghi rõ, không thay cho kết luận
  toàn học kỳ. Không hiển thị thông tin cá nhân hoặc nhu cầu của đơn vị không
  liên quan.
- Bảng xuất lấy khoa theo đơn vị quản lý giảng viên, bao gồm các buổi dạy học phần
  do đơn vị khác quản lý. Quyền sửa và duyệt liên đơn vị vẫn giữ kiểm tra riêng.
- Thanh điều hướng và trang tổng quan ẩn chức năng xếp lịch/nhập dữ liệu khi
  tài khoản không có quyền. Các dòng rà soát chỉ có nút Sửa và ô duyệt phù hợp
  với quyền thực tế; dòng đã duyệt vẫn có dấu tick bị khóa.
- Truy cập trực tiếp URL bị cấm trả HTTP 403 với thông báo và đường về không gian
  làm việc. Việc ẩn nút không thay cho kiểm tra quyền ở máy chủ.
- Biểu mẫu sửa lịch điền sẵn giảng viên, phòng, thứ, tiết và tuần của buổi hiện tại.

## Nguyện vọng phát sinh sau khi duyệt lịch

Nguyện vọng được lưu nhưng không tự thay đổi lịch đã duyệt. Nếu ngày không thể
dạy trùng lịch đã duyệt, giảng viên nhận cảnh báo ngay khi gửi và khi xem lại
lịch. API trả thêm trường `warning` khi có tình huống này.

Người có quyền sửa từng buổi bị ảnh hưởng, lưu về chờ duyệt; đào tạo duyệt lại.
Lịch đang chờ duyệt không hiển thị trên lịch giảng viên. Khi duyệt lại thành công,
lịch mới xuất hiện và cảnh báo xung đột biến mất. Bộ kiểm tra xuất phân công
không đánh dấu đầy đủ nếu còn xung đột ngày không thể dạy.

Chạy lại ba tệp Excel áp dụng cho nhóm chỉ có lịch chờ duyệt do thuật toán tạo.
Nhóm đã có lịch duyệt hoặc lịch nhập riêng được hướng dẫn sửa từng buổi,
không được thay thế tự động bằng lần chạy mới.

## Kết quả kiểm chứng

| Tình huống | Kết quả |
| --- | --- |
| Thiếu thứ/buổi, loại không hợp lệ, ưu tiên 99, thứ 9 | API trả 400; không lưu; biểu mẫu dùng cùng quy tắc |
| Các buổi sáng/chiều/tối và bốn mức ưu tiên hợp lệ | Được chấp nhận |
| Học kỳ khóa | Không nhận nguyện vọng mới; không sửa/duyệt lịch |
| Ngày nghỉ và ưu tiên sáng trước khi xếp lịch | Lịch tránh ngày nghỉ và đáp ứng ưu tiên trong bộ thử khả thi |
| Tránh buổi sáng | Lịch chọn buổi chiều trong bộ thử |
| Mọi ngày cho phép đều bị chặn | Không khả thi; không tạo buổi phân công |
| Nguyện vọng gửi sau lần chạy | Nhận diện bằng ảnh chụp nguyện vọng của lần chạy |
| Ngày nghỉ gửi sau khi lịch đã duyệt | Có cảnh báo; lịch giữ hiệu lực đến khi được sửa |
| Trưởng bộ môn sửa → đào tạo khoa duyệt lại | Hoàn tất trên giao diện; lịch mới hiện cho giảng viên |
| Người chỉ xem | Không có biểu mẫu duyệt hoặc liên kết sửa; máy chủ từ chối ghi |
| Bảng xuất có buổi yêu cầu đầy đủ sau duyệt lại | Tải Excel qua giao diện; 1 dòng, đủ 1 yêu cầu, 0 xung đột ngày nghỉ |
| Dữ liệu công khai/demo thiếu yêu cầu gốc | Giữ cảnh báo; không dựng thêm nhu cầu để báo đủ |

Trong dữ liệu kiểm thử, bảng xuất CNTT của tài khoản cấp khoa có 271 dòng,
thay cho 229 dòng trước sửa do bị loại các học phần liên đơn vị. Phạm vi toàn
học kỳ vẫn có 1.595 nhóm chưa lưu danh sách buổi yêu cầu gốc. Các số này là kết
quả trên CSDL demo, không phải thống kê vận hành thực tế của trường.

Kiểm thử tự động được bổ sung cho dữ liệu nguyện vọng sai, dữ liệu hợp lệ,
học kỳ khóa, cảnh báo API, sửa và duyệt lại, quyền thao tác giao diện,
phạm vi xuất, không lộ dữ liệu ngoài phạm vi và các trạng thái thiếu/chờ/đủ/trùng.
Lệnh kiểm tra: `python backend/manage.py test school --verbosity 1`.
Lượt kiểm tra cuối: 181/181 kiểm thử đạt, hoàn tất trong 35,965 giây.
Không có thay đổi cấu trúc CSDL; kiểm tra migration không phát sinh tệp mới.

## Bổ sung theo review của Quang tại issue #2

- Phạm vi đọc `ScheduleEntry` và `ScheduleWeek` được xác định theo đơn vị quản lý
  giảng viên. Buổi chưa phân công giảng viên thuộc phạm vi đơn vị quản lý học phần.
  Thời khóa biểu khoa, trang rà soát, API đọc lịch và bảng xuất vì vậy cùng hiển thị
  buổi dạy liên khoa của giảng viên thuộc đơn vị được phân quyền.
- Quyền sửa, xóa và duyệt vẫn kiểm tra cả đơn vị quản lý học phần và đơn vị của
  giảng viên. Buổi liên khoa chỉ được xem sẽ không có liên kết mở biểu mẫu sửa,
  không có ô duyệt khả dụng; gọi trực tiếp thao tác ghi vẫn bị từ chối.
- Khi xuất một khoa, kiểm tra độ đầy đủ dùng giao của các bộ môn thuộc khoa đang
  xuất với phạm vi tài khoản. Quy tắc này áp dụng cả tài khoản quản lý nhiều khoa
  và quản trị toàn trường; cảnh báo của khoa khác không đi vào bảng xuất này.
  Hàm đối chiếu vẫn hỗ trợ kiểm tra toàn học kỳ khi gọi riêng không chọn khoa.
- Thêm ba kiểm thử hồi quy: đối chiếu lịch liên khoa giữa các trang và quyền ghi;
  quyền đọc buổi chưa phân công và tuần học; xuất hai khoa có trạng thái đầy đủ
  khác nhau với tài khoản quản lý hai khoa và quản trị toàn trường.
- Lượt kiểm tra sau sửa review: 184/184 kiểm thử đạt trong 64,689 giây;
  không phát sinh migration và không có lỗi khoảng trắng trong diff.
