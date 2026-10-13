"""Render the thesis research-method flowchart as PNG and SVG."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "diagrams"
OUTPUT.mkdir(parents=True, exist_ok=True)

fig, ax = plt.subplots(figsize=(10, 10.5))
ax.set_xlim(0, 1)
ax.set_ylim(0, 1)
ax.axis("off")
fig.patch.set_facecolor("white")

EDGE = "#40566f"
FILL = ["#eaf0f7", "#e5effa", "#e8f3f0", "#fff0d9", "#e7f4ec", "#edf0f5"]


def rounded(x, y, w, h, label, fill, fontsize=12):
    ax.add_patch(FancyBboxPatch(
        (x - w / 2, y - h / 2), w, h,
        boxstyle="round,pad=0.008,rounding_size=0.014",
        edgecolor=EDGE, facecolor=fill, linewidth=1.5,
    ))
    ax.text(x, y, label, ha="center", va="center", fontsize=fontsize,
            color="#172839", linespacing=1.3)


def down(y_top, y_bottom):
    ax.add_patch(FancyArrowPatch((0.5, y_top), (0.5, y_bottom),
                                 arrowstyle="-|>", mutation_scale=15,
                                 linewidth=1.45, color=EDGE))


ax.text(0.5, 0.967, "Quy trình nghiên cứu và kiểm chứng",
        ha="center", va="center", fontsize=17, fontweight="bold", color="#172839")
ax.text(0.5, 0.932, "Từ nguồn tham chiếu và dữ liệu thử nghiệm đến kết quả đánh giá",
        ha="center", va="center", fontsize=10, color="#536579")

steps = [
    (0.865, "1. Nguồn dữ liệu\nTài liệu ITC 2019 • thời khóa biểu công khai • ba tệp Excel thử nghiệm",
     "Đầu ra: nguồn tham chiếu và dữ liệu đầu vào", FILL[0]),
    (0.730, "2. Kiểm tra và thống kê\nCấu trúc, quan hệ dữ liệu, quy mô và mức khan hiếm nguồn lực",
     "Đầu ra: bảng thống kê và lỗi dữ liệu", FILL[1]),
    (0.595, "3. Mô hình hóa\nBuổi học, tập ứng viên, ràng buộc cứng và hàm điểm phạt",
     "Đầu ra: tập ứng viên và mô hình bài toán", FILL[2]),
    (0.460, "4. Chạy bộ giải\nCP-SAT hoặc heuristic; Great Deluge khi có điều kiện",
     "Đầu ra: phương án lịch và trạng thái lần chạy", FILL[3]),
    (0.325, "5. Kiểm tra nghiệm độc lập\nĐối chiếu số buổi và toàn bộ ràng buộc cứng đã mô hình hóa",
     "Đầu ra: lịch chờ duyệt nếu nghiệm hợp lệ", FILL[4]),
    (0.190, "6. Đánh giá thực nghiệm\nTính hợp lệ, trạng thái, thời gian và điểm phạt trước/sau",
     "Đầu ra: báo cáo kiểm thử và giới hạn kết luận", FILL[5]),
]

for y, label, output, fill in steps:
    rounded(0.5, y, 0.75, 0.073, label, fill, 11)
    ax.text(0.5, y - 0.061, output, ha="center", va="center",
            fontsize=9.1, color="#526678", style="italic")

for upper, lower in zip(steps[:-1], steps[1:]):
    down(upper[0] - 0.075, lower[0] + 0.045)

ax.text(0.5, 0.075,
        "Các kết quả thử nghiệm được diễn giải trong phạm vi dữ liệu,\n"
        "ràng buộc và giới hạn thời gian của từng lần chạy.",
        ha="center", va="center", fontsize=9, color="#526678")

for suffix in ("png", "svg"):
    fig.savefig(OUTPUT / f"so_do_phuong_phap_nghien_cuu_1_5.{suffix}",
                dpi=260, bbox_inches="tight", facecolor="white")
plt.close(fig)
print(OUTPUT)
