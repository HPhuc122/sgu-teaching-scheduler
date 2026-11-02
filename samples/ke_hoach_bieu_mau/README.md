# Ba bộ kế hoạch giảng dạy 15 khoa

Mỗi thư mục hk1, hk2, hk3 có đúng ba file courses.xlsx, rooms.xlsx, lecturers.xlsx để nhập trên giao diện. Thông tin học kỳ, ngày bắt đầu/kết thúc và quy mô có trong manifest.json. Có thể lưu kế hoạch trước hoặc chạy xếp lịch ngay.

Học phần, mã môn, lớp, nhóm, tên khoa và mã phòng dựa trên các bộ SGU đã đối chiếu từ sổ tay đăng ký môn học HK1 năm học 2026–2027. Ba bộ mới là ba học kỳ mô phỏng của năm học 2027–2028, lần lượt có 240, 480 và 960 buổi. Không diễn giải là kế hoạch HK2/HK3 thật của trường.

Toàn bộ họ tên giảng viên, mã MPGV, học vị, nơi công tác và phân công là giả lập. Tên được đặt tự nhiên và nhất quán giữa ba học kỳ. Không sao chép danh tính từ các ảnh biểu mẫu nội bộ và không giữ tên/mã giảng viên thật trong chín tệp mới.

Mỗi khoa có ví dụ phân công cơ hữu, mời giảng nội bộ, thỉnh giảng và công tác khác. Hoạt động ngoài trường, đơn vị quản lý lớp, giờ kế hoạch, số tiết thực tế và hệ số 1 là dữ liệu mô phỏng. Các hệ số này không đại diện cho quy định nội bộ SGU. Các buổi bỏ trống mã giảng viên cho phép thử phân công tự động.

Nguồn công khai: https://daotao.sgu.edu.vn/index.php/thong-bao/so-tay-dang-ki-mon-hoc/so-tay-dang-ki-mon-hoc-hk1-nh-2026-2027 và https://www.sgu.edu.vn/danh-sach-cac-don-vi/. Từng bộ có tệp hkN_nguon.json ghi đường dẫn và SHA-256 của bộ nguồn cục bộ. Khi dùng --preserve-catalog, các thuộc tính học phần/phòng hiện có được giữ để tương thích lịch đã lưu; cần dùng cùng CSDL hoặc snapshot để tái tạo đúng biến thể đó.
