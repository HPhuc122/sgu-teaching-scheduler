"""Create the report figure for the current three-stage scheduling workflow."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "diagrams"
OUTPUT.mkdir(parents=True, exist_ok=True)

fig, ax = plt.subplots(figsize=(10, 12))
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis("off")
fig.patch.set_facecolor("white")

BLUE = "#e8f0fb"
GREEN = "#e7f5ed"
ORANGE = "#fff1db"
GRAY = "#eef1f4"
RED = "#fde9e7"
EDGE = "#41556b"


def box(x, y, w, h, label, color=BLUE, size=11):
    patch = FancyBboxPatch((x-w/2, y-h/2), w, h,
                           boxstyle="round,pad=0.008,rounding_size=0.012",
                           edgecolor=EDGE, facecolor=color, linewidth=1.4)
    ax.add_patch(patch)
    ax.text(x, y, label, ha="center", va="center", fontsize=size,
            fontweight="normal", linespacing=1.35)


def arrow(points, label=None, label_xy=None, size=9):
    for start, end in zip(points[:-2], points[1:-1]):
        ax.plot([start[0], end[0]], [start[1], end[1]], color=EDGE, linewidth=1.25)
    ax.add_patch(FancyArrowPatch(points[-2], points[-1], arrowstyle="-|>",
                                 mutation_scale=13, linewidth=1.25, color=EDGE))
    if label and label_xy:
        ax.text(*label_xy, label, ha="center", va="center", fontsize=size,
                color="#2b3d50", bbox={"facecolor": "white", "edgecolor": "none", "pad": 1.5})


ax.text(0.5, 0.975, "Kiến trúc xếp lịch tự động theo ba giai đoạn",
        ha="center", va="center", fontsize=16, fontweight="bold")
ax.text(0.5, 0.947, "Luồng triển khai hiện tại của hệ thống", ha="center", va="center",
        fontsize=10, color="#536579")

box(0.5, 0.895, 0.64, 0.054, "Admin chọn học kỳ, tải 3 file Excel\nHọc phần • Phòng học • Giảng viên", GRAY, 11)
box(0.5, 0.813, 0.64, 0.055, "Kiểm tra cấu trúc và quan hệ dữ liệu\nBáo lỗi theo file, sheet, dòng", BLUE, 11)
box(0.5, 0.727, 0.64, 0.056, "Giai đoạn 0: tạo tập ứng viên\nƯu tiên buổi có ít lựa chọn trong lượt khởi tạo đầu", BLUE, 11)

diamond = Polygon([(0.5, 0.661), (0.64, 0.613), (0.5, 0.565), (0.36, 0.613)],
                  closed=True, edgecolor=EDGE, facecolor=ORANGE, linewidth=1.4)
ax.add_patch(diamond)
ax.text(0.5, 0.613, "Số buổi\n< 500?", ha="center", va="center", fontsize=11)

box(0.245, 0.499, 0.37, 0.072, "Giai đoạn 1: CP-SAT\nGiới hạn 30 giây; có lịch khởi tạo\nlàm phương án dự phòng hợp lệ", GREEN, 10)
box(0.755, 0.499, 0.37, 0.072, "Giai đoạn 1: heuristic\nTừ 500 buổi; trả HEURISTIC\nkhi tìm được lịch hợp lệ", GREEN, 10)
box(0.5, 0.381, 0.76, 0.066,
    "Đánh giá trạng thái lần chạy\nOPTIMAL  |  FEASIBLE  |  HEURISTIC  |  INFEASIBLE  |  UNKNOWN", GRAY, 9)
box(0.27, 0.259, 0.37, 0.075,
    "Giai đoạn 2: Great Deluge\nThử đổi thời gian, phòng, giảng viên\nGiữ nghiệm tốt nhất", ORANGE, 10)
box(0.76, 0.259, 0.36, 0.075,
    "Không có lịch để lưu\nChẩn đoán INFEASIBLE / UNKNOWN\nGiữ nguyên lịch cũ", RED, 10)
box(0.5, 0.143, 0.59, 0.063,
    "Kiểm tra độc lập toàn bộ ràng buộc cứng\nNếu không hợp lệ: hủy lần chạy", BLUE, 10)
box(0.5, 0.057, 0.59, 0.055,
    "Lưu toàn bộ buổi ở trạng thái CHỜ DUYỆT\nAdmin rà soát → duyệt → xuất kết quả", GREEN, 10)

arrow([(0.5, 0.868), (0.5, 0.841)])
arrow([(0.5, 0.785), (0.5, 0.755)])
arrow([(0.5, 0.699), (0.5, 0.661)])
arrow([(0.36, 0.613), (0.245, 0.613), (0.245, 0.535)], "Có", (0.285, 0.594))
arrow([(0.64, 0.613), (0.755, 0.613), (0.755, 0.535)], "Không", (0.718, 0.594))
arrow([(0.245, 0.463), (0.245, 0.442), (0.5, 0.442), (0.5, 0.414)])
arrow([(0.755, 0.463), (0.755, 0.442), (0.5, 0.442), (0.5, 0.414)])
arrow([(0.27, 0.348), (0.27, 0.297)],
      "FEASIBLE / HEURISTIC\nvà điểm phạt > 0", (0.155, 0.325), 8)
arrow([(0.76, 0.348), (0.76, 0.297)],
      "Không tìm được lịch", (0.82, 0.326), 8)
arrow([(0.27, 0.221), (0.27, 0.188), (0.41, 0.188), (0.41, 0.175)])
arrow([(0.5, 0.348), (0.5, 0.175)],
      "OPTIMAL hoặc\nđiểm phạt = 0", (0.5, 0.323), 8)
arrow([(0.5, 0.111), (0.5, 0.085)])

for extension in ("png", "svg"):
    fig.savefig(OUTPUT / f"so_do_thuat_toan_3_giai_doan.{extension}",
                dpi=260, bbox_inches="tight", facecolor="white")
plt.close(fig)
print(OUTPUT)
