from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Faculty(models.Model):
    code = models.CharField(max_length=20, unique=True, db_column="MaKhoaVietTat")
    name = models.CharField(max_length=200, db_column="TenKhoa")

    class Meta:
        db_table = "Khoa"

    def __str__(self):
        return self.name


class Department(models.Model):
    faculty = models.ForeignKey(Faculty, on_delete=models.PROTECT, db_column="MaKhoa")
    code = models.CharField(max_length=30, null=True, blank=True, db_column="MaBoMonCode")
    name = models.CharField(max_length=200, db_column="TenBoMon")

    class Meta:
        db_table = "BoMon"

    def __str__(self):
        return self.name


class Lecturer(models.Model):
    department = models.ForeignKey(Department, on_delete=models.PROTECT, db_column="MaBoMon")
    user = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="lecturer_profile")
    employee_code = models.CharField(max_length=30, unique=True, null=True, blank=True, db_column="MaVienChuc")
    name = models.CharField(max_length=200, db_column="HoTen")
    email = models.EmailField(null=True, blank=True, db_column="Email")
    status = models.CharField(max_length=20, default="DangCongTac", db_column="TrangThai")

    class Meta:
        db_table = "GiangVien"

    def __str__(self):
        return self.name


class Course(models.Model):
    department = models.ForeignKey(Department, on_delete=models.PROTECT, db_column="MaBoMon")
    code = models.CharField(max_length=30, unique=True, db_column="MaHocPhanCode")
    name = models.CharField(max_length=200, db_column="TenHocPhan")
    credits = models.PositiveSmallIntegerField(db_column="SoTinChi")
    kind = models.CharField(max_length=20, default="CHUYEN_NGANH", db_column="LoaiMon")

    class Meta:
        db_table = "HocPhan"

    def __str__(self):
        return f"{self.code} {self.name}"


class Program(models.Model):
    faculty = models.ForeignKey(Faculty, on_delete=models.PROTECT, db_column="MaKhoa")
    code = models.CharField(max_length=20, db_column="MaNganhCTDT")
    name = models.CharField(max_length=200, db_column="TenChuongTrinh")
    cycle = models.CharField(max_length=30, db_column="ChuKyCTDT")

    class Meta:
        db_table = "ChuongTrinhDaoTao"
        constraints = [models.UniqueConstraint(fields=["code", "cycle"], name="uq_program_code_cycle")]

    def __str__(self):
        return f"{self.code} ({self.cycle})"


class CourseProgram(models.Model):
    course = models.ForeignKey(Course, on_delete=models.PROTECT, db_column="MaHocPhan")
    program = models.ForeignKey(Program, on_delete=models.PROTECT, db_column="MaChuongTrinh")
    requirement = models.CharField(max_length=20, db_column="LoaiTrongCTDT")

    class Meta:
        db_table = "HocPhanChuongTrinh"
        constraints = [models.UniqueConstraint(fields=["course", "program"], name="uq_course_program")]


class TeachingQualification(models.Model):
    lecturer = models.ForeignKey(Lecturer, on_delete=models.CASCADE, db_column="MaGV")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, db_column="MaHocPhan")
    priority = models.PositiveSmallIntegerField(default=2, db_column="MucDoUuTien")

    class Meta:
        db_table = "ChuyenMonGV"
        constraints = [models.UniqueConstraint(fields=["lecturer", "course"], name="uq_qualification_lecturer_course")]


class Semester(models.Model):
    name = models.CharField(max_length=50, db_column="TenHocKy")
    academic_year = models.CharField(max_length=20, db_column="NamHoc")
    start_date = models.DateField(db_column="NgayBatDau")
    end_date = models.DateField(db_column="NgayKetThuc")
    week_count = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(53)], db_column="SoTuan")
    status = models.CharField(max_length=20, default="DangMo", db_column="TrangThai")

    class Meta:
        db_table = "HocKy"

    def __str__(self):
        return self.name


class Building(models.Model):
    code = models.CharField(max_length=30, null=True, blank=True, db_column="MaToaNhaCode")
    name = models.CharField(max_length=100, db_column="TenToaNha")

    class Meta:
        db_table = "ToaNha"


class Room(models.Model):
    building = models.ForeignKey(Building, on_delete=models.PROTECT, db_column="MaToaNha")
    code = models.CharField(max_length=30, unique=True, db_column="MaPhongCode")
    name = models.CharField(max_length=50, db_column="TenPhong")
    capacity = models.PositiveIntegerField(db_column="SucChua")
    room_type = models.CharField(max_length=30, default="LyThuyet", db_column="LoaiPhong")
    status = models.CharField(max_length=20, default="SanSang", db_column="TrangThai")

    class Meta:
        db_table = "PhongHoc"

    def __str__(self):
        return self.code


class Period(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, db_column="MaTiet")
    block = models.CharField(max_length=10, db_column="Buoi")
    start_time = models.TimeField(db_column="GioBatDau")
    end_time = models.TimeField(db_column="GioKetThuc")

    class Meta:
        db_table = "CauHinhTiet"

    def __str__(self):
        return f"Tiết {self.pk} ({self.start_time:%H:%M}–{self.end_time:%H:%M})"


class CourseGroup(models.Model):
    course = models.ForeignKey(Course, on_delete=models.PROTECT, db_column="MaHocPhan")
    semester = models.ForeignKey(Semester, on_delete=models.PROTECT, db_column="MaHocKy")
    code = models.CharField(max_length=30, db_column="MaLopCode")
    group = models.CharField(max_length=10, db_column="Nhom")
    lab_group = models.CharField(max_length=10, null=True, blank=True, db_column="ToTH")
    capacity = models.PositiveIntegerField(db_column="SiSoToiDa")
    needs_room = models.BooleanField(default=True, db_column="CanPhongHoc")

    class Meta:
        db_table = "LopHocPhan"
        constraints = [models.UniqueConstraint(fields=["course", "semester", "code"], name="uq_course_semester_groupcode")]


class Cohort(models.Model):
    semester = models.ForeignKey(Semester, on_delete=models.PROTECT, db_column="MaHocKy")
    name = models.CharField(max_length=30, db_column="TenLop")

    class Meta:
        db_table = "LopHanhChinh"
        constraints = [models.UniqueConstraint(fields=["semester", "name"], name="uq_cohort_semester_name")]


class GroupCohort(models.Model):
    group = models.ForeignKey(CourseGroup, on_delete=models.CASCADE, related_name="cohort_links", db_column="MaLopHP")
    cohort = models.ForeignKey(Cohort, on_delete=models.CASCADE, db_column="MaLopHC")

    class Meta:
        db_table = "LopHocPhanLopHanhChinh"
        constraints = [models.UniqueConstraint(fields=["group", "cohort"], name="uq_group_cohort")]


class AlgorithmRun(models.Model):
    semester = models.ForeignKey(Semester, on_delete=models.PROTECT, related_name="algorithm_runs")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20)
    objective = models.IntegerField(null=True, blank=True)
    objective_before = models.IntegerField(null=True, blank=True)
    entry_count = models.PositiveIntegerField(default=0)
    optimization_trials = models.JSONField(default=list, blank=True)
    message = models.TextField(blank=True)
    diagnostics = models.JSONField(default=list, blank=True)
    preferences_snapshot = models.JSONField(default=list, blank=True)
    preferences_captured_at = models.DateTimeField(null=True, blank=True)
    demand_snapshot = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "LanChayThuatToan"


class ScheduleRunQueue(models.Model):
    """One active run per semester; uploaded files are removed on completion."""

    semester = models.OneToOneField(Semester, on_delete=models.PROTECT, related_name="active_schedule_run")
    run = models.OneToOneField(AlgorithmRun, on_delete=models.CASCADE, related_name="queue_item")
    courses_file = models.BinaryField()
    rooms_file = models.BinaryField()
    lecturers_file = models.BinaryField()

    class Meta:
        db_table = "HangDoiXepLich"


class ScheduleEntry(models.Model):
    group = models.ForeignKey(CourseGroup, on_delete=models.PROTECT, db_column="MaLopHP")
    lecturer = models.ForeignKey(Lecturer, null=True, blank=True, on_delete=models.PROTECT, db_column="MaGV")
    room = models.ForeignKey(Room, null=True, blank=True, on_delete=models.PROTECT, db_column="MaPhong")
    other_location = models.CharField(max_length=100, null=True, blank=True, db_column="DiaDiemKhac")
    day = models.PositiveSmallIntegerField(db_column="Thu")
    start_period = models.ForeignKey(Period, on_delete=models.PROTECT, db_column="MaTietBatDau")
    period_count = models.PositiveSmallIntegerField(db_column="SoTiet")
    source = models.CharField(max_length=20, default="ThuCong", db_column="NguonGoc")
    status = models.CharField(max_length=20, default="ChoDuyet", db_column="TrangThai")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="approved_schedule_entries",
                                    db_column="NguoiDuyet")
    approved_at = models.DateTimeField(null=True, blank=True, db_column="NgayDuyet")
    algorithm_run = models.ForeignKey(AlgorithmRun, null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name="entries")
    request_code = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        db_table = "PhanCong"
        indexes = [
            models.Index(fields=["lecturer", "day", "start_period"], name="ix_schedule_lecturer"),
            models.Index(fields=["room", "day", "start_period"], name="ix_schedule_room"),
        ]


class ScheduleWeek(models.Model):
    entry = models.ForeignKey(ScheduleEntry, on_delete=models.CASCADE, related_name="schedule_weeks", db_column="MaPhanCong")
    week = models.PositiveSmallIntegerField(db_column="Tuan")

    class Meta:
        db_table = "PhanCongTuan"
        constraints = [models.UniqueConstraint(fields=["entry", "week"], name="uq_schedule_week")]


class LecturerPreference(models.Model):
    lecturer = models.ForeignKey(Lecturer, on_delete=models.CASCADE, db_column="MaGV")
    semester = models.ForeignKey(Semester, on_delete=models.CASCADE, db_column="MaHocKy")
    kind = models.CharField(max_length=30, db_column="LoaiNguyenVong")
    day = models.PositiveSmallIntegerField(null=True, blank=True, db_column="Thu")
    time_block = models.CharField(max_length=20, null=True, blank=True, db_column="KhungGio")
    priority = models.PositiveSmallIntegerField(default=2, db_column="MucDoUuTien")
    note = models.CharField(max_length=200, blank=True, db_column="GhiChu")

    class Meta:
        db_table = "NguyenVongGV"
