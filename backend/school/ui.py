"""Presentation labels only; model metadata and database schema stay unchanged."""

MODEL_LABELS = {
    "faculty": "Khoa", "department": "Bộ môn", "lecturer": "Giảng viên",
    "course": "Học phần", "coursegroup": "Lớp học phần",
    "courseprogram": "Học phần trong chương trình", "room": "Phòng học",
    "building": "Tòa nhà", "semester": "Học kỳ", "period": "Tiết học",
    "teachingqualification": "Chuyên môn giảng dạy", "program": "Chương trình đào tạo",
    "cohort": "Lớp hành chính", "user": "Người dùng", "group": "Nhóm quyền",
}

FIELD_LABELS = {
    "code": "Mã", "name": "Tên", "faculty": "Khoa", "department": "Bộ môn",
    "user": "Tài khoản liên kết", "employee_code": "Mã viên chức", "email": "Email",
    "status": "Trạng thái", "credits": "Số tín chỉ", "kind": "Loại học phần",
    "cycle": "Chu kỳ đào tạo", "course": "Học phần", "program": "Chương trình đào tạo",
    "requirement": "Loại trong chương trình", "lecturer": "Giảng viên",
    "priority": "Mức ưu tiên", "academic_year": "Năm học", "start_date": "Ngày bắt đầu",
    "end_date": "Ngày kết thúc", "week_count": "Số tuần học", "building": "Tòa nhà",
    "capacity": "Sức chứa / sĩ số", "room_type": "Loại phòng", "id": "Số tiết",
    "block": "Buổi", "start_time": "Giờ bắt đầu", "end_time": "Giờ kết thúc",
    "semester": "Học kỳ", "group": "Nhóm", "lab_group": "Tổ thực hành",
    "needs_room": "Cần phòng học",
}

STATUS_LABELS = {
    "DangCongTac": "Đang công tác", "SanSang": "Sẵn sàng", "DangMo": "Đang mở",
    "DaKhoa": "Đã khóa", "ChoDuyet": "Chờ duyệt", "DaDuyet": "Đã duyệt",
    "CHUNG": "Học phần chung", "CHUYEN_NGANH": "Chuyên ngành",
    "LyThuyet": "Lý thuyết", "ThucHanh": "Thực hành",
    "BAT_BUOC": "Bắt buộc", "TU_CHON": "Tự chọn",
    "Sang": "Sáng", "Chieu": "Chiều", "Toi": "Tối",
    "KhungGio": "Ưu tiên khung giờ", "NgayNghi": "Ngày không thể dạy",
    "NgungCongTac": "Ngừng công tác", "BaoTri": "Bảo trì",
    "MayTinh": "Phòng máy tính", "ThiNghiem": "Phòng thí nghiệm", "HoiTruong": "Hội trường",
}

# Existing codes used by catalog_import and the scheduling services.
CODE_OPTIONS = {
    ("lecturer", "status"): ("DangCongTac", "NgungCongTac"),
    ("room", "status"): ("SanSang", "BaoTri"),
    ("semester", "status"): ("DangMo", "DaKhoa"),
    ("course", "kind"): ("CHUNG", "CHUYEN_NGANH"),
    ("courseprogram", "requirement"): ("BAT_BUOC", "TU_CHON"),
    ("room", "room_type"): ("LyThuyet", "MayTinh", "ThiNghiem", "HoiTruong"),
    ("period", "block"): ("Sang", "Chieu", "Toi"),
}
