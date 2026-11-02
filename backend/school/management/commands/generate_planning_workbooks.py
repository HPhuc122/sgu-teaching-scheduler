"""Prepare realistic SGU planning inputs with natural, fictional lecturer names."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from school.realistic_planning_data import build_realistic_packs
from school.sample_data import workbook_bytes


class Command(BaseCommand):
    help = "Sinh ba bộ kế hoạch 15 khoa từ học phần SGU có nguồn, dùng danh tính giảng viên hoàn toàn giả lập"

    def add_arguments(self, parser):
        parser.add_argument("--output", default="samples/ke_hoach_bieu_mau")
        parser.add_argument("--source-root", default="samples/sgu_15_khoa")
        parser.add_argument("--preserve-catalog", action="store_true", help="Giữ thuộc tính học phần/phòng hiện có để không thay dữ liệu đã có lịch")

    def handle(self, *args, **options):
        source = Path(options["source_root"])
        if not all((source / f"bo_{i:02d}" / "courses.xlsx").exists() for i in (1, 2, 3)):
            raise CommandError("Missing SGU source packs; pass --source-root.")
        root = Path(options["output"])
        root.mkdir(parents=True, exist_ok=True)
        manifest = []
        for number, start, end, name, rows, provenance in build_realistic_packs(source, preserve_catalog=options["preserve_catalog"]):
            folder = root / f"hk{number}"
            folder.mkdir(exist_ok=True)
            for kind, sheets in rows.items():
                (folder / f"{kind}.xlsx").write_bytes(workbook_bytes(kind, sheets))
            counts = {kind: {sheet: len(records) for sheet, records in sheets.items()} for kind, sheets in rows.items()}
            manifest.append(dict(semester=name, number=number, academic_year="2027-2028", start_date=start, end_date=end,
                weeks=16, sessions=counts["courses"]["BuoiHocYeuCau"], groups=counts["courses"]["NhomHocPhan"],
                faculties=counts["courses"]["Khoa"], courses=counts["courses"]["HocPhan"], lecturers=counts["lecturers"]["GiangVien"],
                rooms=counts["rooms"]["PhongHoc"], folder=str(folder), counts=counts))
            (root / f"hk{number}_nguon.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
        (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (root / "README.md").write_text("""# Ba bộ kế hoạch giảng dạy 15 khoa

Mỗi thư mục hk1, hk2, hk3 có đúng ba file courses.xlsx, rooms.xlsx, lecturers.xlsx để nhập trên giao diện. Thông tin học kỳ, ngày bắt đầu/kết thúc và quy mô có trong manifest.json. Có thể lưu kế hoạch trước hoặc chạy xếp lịch ngay.

Học phần, mã môn, lớp, nhóm, tên khoa và mã phòng dựa trên các bộ SGU đã đối chiếu từ sổ tay đăng ký môn học HK1 năm học 2026–2027. Ba bộ mới là ba học kỳ mô phỏng của năm học 2027–2028, lần lượt có 240, 480 và 960 buổi. Không diễn giải là kế hoạch HK2/HK3 thật của trường.

Toàn bộ họ tên giảng viên, mã MPGV, học vị, nơi công tác và phân công là giả lập. Tên được đặt tự nhiên và nhất quán giữa ba học kỳ. Không sao chép danh tính từ các ảnh biểu mẫu nội bộ và không giữ tên/mã giảng viên thật trong chín tệp mới.

Mỗi khoa có ví dụ phân công cơ hữu, mời giảng nội bộ, thỉnh giảng và công tác khác. Hoạt động ngoài trường, đơn vị quản lý lớp, giờ kế hoạch, số tiết thực tế và hệ số 1 là dữ liệu mô phỏng. Các hệ số này không đại diện cho quy định nội bộ SGU. Các buổi bỏ trống mã giảng viên cho phép thử phân công tự động.

Nguồn công khai: https://daotao.sgu.edu.vn/index.php/thong-bao/so-tay-dang-ki-mon-hoc/so-tay-dang-ki-mon-hoc-hk1-nh-2026-2027 và https://www.sgu.edu.vn/danh-sach-cac-don-vi/. Từng bộ có tệp hkN_nguon.json ghi đường dẫn và SHA-256 của bộ nguồn cục bộ. Khi dùng --preserve-catalog, các thuộc tính học phần/phòng hiện có được giữ để tương thích lịch đã lưu; cần dùng cùng CSDL hoặc snapshot để tái tạo đúng biến thể đó.
""", encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Created 3 realistic planning packs: {root.resolve()}"))
