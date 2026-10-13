# Đối chiếu nguồn SGU trước khi chốt ba file Excel danh mục

Ngày đối chiếu: 12/10/2026. Đây là tài liệu khảo sát đã được dùng để xây chuẩn nhập liệu đề xuất; chưa phải quy trình nội bộ được SGU xác nhận. Các mẫu nhập hiện nằm ở `backend/school/catalog_import.py` và `backend/school/schedule_import.py`.

## Nguồn và mức chứng minh

| Nguồn | Điều xác nhận được | Điều không xác nhận được |
| --- | --- | --- |
| [Sổ tay đăng ký môn học HK1 2026–2027](https://daotao.sgu.edu.vn/index.php/thong-bao/so-tay-dang-ki-mon-hoc/so-tay-dang-ki-mon-hoc-hk1-nh-2026-2027) | Công bố riêng thời khóa biểu **môn chung** và thời khóa biểu **môn chuyên ngành theo mã ngành** (ví dụ DCT, DKP). | Không quy định cấu trúc file Excel đầu vào hay quan hệ chính xác giữa học phần, khoa và chương trình đào tạo. |
| [Mẫu X5110AB.006 – CNTT, HK1 2026–2027](https://daotao.sgu.edu.vn/images/pdf/sotaydkmh/261/DCT.pdf) | Có `Mã MH`, `Tên môn học`, `Số TC`, `Sỉ số`, `Họ và tên`, `Mã viên chức`, `Nhóm`, `Tổ TH`, `Thứ`, `Tiết BĐ`, `Số tiết`, `Mã phòng`, `Tên lớp`, `Tuần học`. Một mã môn học có nhiều nhóm và mỗi nhóm có thể có nhiều buổi. `Tên lớp` gồm cả các mã ngành khác trong bản CNTT. | Không có mã lớp học phần duy nhất dưới dạng `841021.01`; không có loại phòng, sức chứa phòng, email giảng viên, bộ môn, trạng thái duyệt. |
| [Mẫu X5010B.001 – Môn chung, HK1 2026–2027](https://daotao.sgu.edu.vn/images/pdf/sotaydkmh/261/TKB_monchung.pdf) | Có `Mã viên chức`, `Mã MH`, `NH`, `Tổ TH`, số sinh viên, thứ, tiết, phòng, tuần học; là báo cáo theo môn. | Không cho biết một môn chung áp dụng tự động cho mọi ngành hoặc danh sách ngành cụ thể. |
| [Trang biểu mẫu Phòng Đào tạo](https://daotao.sgu.edu.vn/index.php/van-ban/bieu-mau) | Danh mục công khai hiện không hiển thị mẫu nhập học phần, phòng, giảng viên hoặc bảng phân công giảng dạy của khoa. | Không chứng minh trường không có biểu mẫu nội bộ. |
| [Biểu mẫu Khoa Giáo dục](https://khoagiaoduc.sgu.edu.vn/blog/2023/04/24/bieu-mau-khoa-giao-duc/) | Trang tập hợp liên kết biểu mẫu của nhiều đơn vị, trong đó dẫn về biểu mẫu Phòng Đào tạo và có giấy đề nghị sử dụng phòng/hội trường. | Không phải mẫu danh mục phòng hoặc file phân công giảng dạy. |
| [Các biểu mẫu khác – Đào tạo sau đại học](https://dtsdh.sgu.edu.vn/cac-bieu-mau-khac/) | Chủ yếu là biểu mẫu thạc sĩ/tiến sĩ, có lý lịch khoa học giảng viên. | Không dùng làm căn cứ cho quy trình xếp lịch đại học chính quy của đề tài. |
| [Chương trình đào tạo chu kỳ 2024–2028](https://daotao.sgu.edu.vn/index.php/van-ban/chuong-trinh-dao-tao/chuong-trinh-dao-tao-chu-ky-2024-2028) | Trường công bố chương trình đào tạo theo chu kỳ; đây là nguồn để đối chiếu học phần với chương trình. | Chưa đủ căn cứ suy ra mã đơn vị phụ trách hoặc một trường `ma_khoa_ap_dung` duy nhất cho mọi học phần. |
| [Thông báo hủy nhóm HK1 2026–2027](https://daotao.sgu.edu.vn/index.php/thong-bao/dang-ki-mon-hoc/thong-bao-ve-viec-huy-nhom-sau-dot-dang-ki-mon-hoc-bo-sung-hoc-ki-i-nam-hoc-2026-2027) | Nhóm học phần có thể thay đổi/hủy sau giai đoạn đăng ký bổ sung. | Chưa xác minh điều kiện hủy, người duyệt, hoặc cách cập nhật lịch nội bộ. |
| [Quyết định 3183/2025 sửa đổi Quy chế đào tạo](https://daotao.sgu.edu.vn/images/pdf/quy_dinh/QD%203183.2025%20-%20Sua%20doi%20Quy%20che%20Dao%20tao%20trinh%20do%20DH_LienQuanRutMonHoc.pdf) | Xác nhận có sửa đổi quy chế đào tạo. | Chưa suy ra quy trình nhập ba danh mục hoặc phân quyền phê duyệt từ văn bản này. |
| [NotebookLM người dùng chia sẻ](https://notebook.google.com/notebook/7eb71405-14f9-4a6d-9fec-b339a3e3e1a6?authuser=6) | Danh mục 10 nguồn đã ghi ở `nguon_sgu_notebook.md`; mẫu X5110AB.006 đã được kiểm tra ở lần khảo sát trước. | Lần truy cập sâu hơn vào nguồn notebook trong phiên này bị hệ thống xét duyệt thao tác giới hạn (429), nên chưa kiểm tra trực tiếp các biểu mẫu còn lại. Tên nguồn/tóm tắt NotebookLM không đủ để xác nhận quy trình. |

## Điều chỉnh đối với đề xuất ba file

1. **Học phần:** không dùng `ma_khoa_ap_dung` như một thuộc tính duy nhất của học phần. Cần tách **đơn vị phụ trách môn** khỏi **chương trình/ngành sử dụng môn**. `mon_chung` chỉ là phân loại công bố thời khóa biểu; không được mặc định có nghĩa tất cả ngành đều học. Đề xuất một workbook gồm sheet `HocPhan` (`ma_mon_hoc`, `ten_mon_hoc`, `so_tin_chi`, `ma_don_vi_phu_trach`, `loai_mon`) và sheet `HocPhanChuongTrinh` (`ma_mon_hoc`, `ma_nganh_ctdt`, `chu_ky_ctdt`, `loai_trong_ctdt`). Các cột đơn vị, loại môn và loại trong CTĐT là **thiết kế cần xác nhận**, chưa phải cột mẫu SGU.
2. **Nhóm mở theo học kỳ:** cùng workbook học phần có sheet `NhomHocPhan` (`ma_mon_hoc`, `hoc_ky`, `nhom`, `to_th`, `si_so_du_kien`, `ten_lop`). Mã định danh nội bộ có thể ghép từ các trường này nhưng không được tuyên bố là mã SGU. Nên lưu tình trạng nhóm để phản ánh thay đổi/hủy sau đăng ký. Quy tắc mã duy nhất và khi nào nhóm được tạo là **chưa xác nhận**.
3. **Phòng:** `ma_phong` có trong cả hai mẫu thời khóa biểu. Các trường `ma_toa_nha`, `suc_chua`, `loai_phong`, `trang_thai`, thiết bị và thời gian không sử dụng là dữ liệu **hệ thống cần để xếp phòng**, chưa thấy trong mẫu nguồn; cần nguồn danh mục cơ sở vật chất để xác nhận mã và giá trị.
4. **Giảng viên:** `ma_vien_chuc` và `ho_ten` có trong mẫu báo cáo. `email`, `ma_khoa`, `ma_bo_mon`, `trang_thai` và danh sách học phần đủ điều kiện giảng dạy chưa được các nguồn trên xác nhận là cột của file SGU. Quan hệ giảng viên–học phần nên ở sheet `GiangVienHocPhan` riêng trong workbook giảng viên thay vì chuỗi nhiều mã trong một ô; quy tắc xác nhận chuyên môn vẫn cần làm rõ.

## Quy trình có thể mô hình hóa và điểm dừng xác nhận

| Bước | Căn cứ | Trạng thái |
| --- | --- | --- |
| Danh mục môn và chương trình đào tạo | Trang CTĐT, báo cáo thời khóa biểu | Có căn cứ cho mã môn và sự tồn tại của CTĐT; thiếu file nguồn chính thức. |
| Mở nhóm học phần theo học kỳ | Mẫu `Nhóm`/`Tổ TH`, thông báo hủy nhóm | Có căn cứ cho thực thể nhóm và việc nhóm thay đổi; thiếu quy trình mở/hủy và quyền hạn. |
| Gắn giảng viên, thời gian, phòng, tuần | Hai mẫu thời khóa biểu | Có căn cứ cho dữ liệu đầu ra; thiếu trình tự phân công/xếp phòng và quyền phê duyệt. |
| Xuất thời khóa biểu theo môn/ngành | X5010B.001 và X5110AB.006 | Có mẫu công khai để đối chiếu. |
| Xuất bảng phân công giảng dạy hoàn chỉnh theo khoa | Chưa tìm thấy mẫu công khai | Chưa được xác minh. |

## Quyết định cần duyệt trước khi lập trình

- Dùng **ba workbook riêng**, nhưng workbook học phần có các sheet danh mục môn, quan hệ môn–CTĐT và nhóm học phần theo kỳ; workbook giảng viên có sheet chuyên môn giảng dạy; workbook phòng có một sheet danh mục và có thể thêm sheet đặc tính phòng nếu nguồn sau này yêu cầu.
- Dùng **mã ngành/CTĐT** để diễn tả môn áp dụng cho chương trình nào; giữ **đơn vị phụ trách** là quan hệ khác. Không suy diễn `TOAN_TRUONG` từ nhãn “môn chung”.
- Khi thiếu nguồn chính thức, gọi đây là **chuẩn nhập liệu đề xuất cho hệ thống SGU**, không gọi là “biểu mẫu chuẩn của trường”. Trước khi dùng thật, đối chiếu với người phụ trách đào tạo hoặc file nội bộ nếu có.
