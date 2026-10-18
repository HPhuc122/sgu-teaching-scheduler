"""Preference rules shared by the lecturer form and API."""


def preference_errors(values):
    errors = {}
    kind = values.get("kind")
    day = values.get("day")
    block = values.get("time_block")
    priority = values.get("priority", 2)
    if kind not in ("KhungGio", "NgayNghi"):
        errors["kind"] = "Loại nguyện vọng không hợp lệ"
    if day is not None and not 2 <= day <= 8:
        errors["day"] = "Thứ phải từ 2 đến 8"
    if block not in (None, "", "Sang", "Chieu", "Toi"):
        errors["time_block"] = "Buổi phải là sáng, chiều hoặc tối"
    if priority not in (1, 2, 3, 4):
        errors["priority"] = "Mức ưu tiên phải từ 1 đến 4"
    if kind == "NgayNghi" and day is None:
        errors["day"] = "Cần chọn thứ cho ngày không thể dạy"
    if kind == "KhungGio" and not block:
        errors["time_block"] = "Cần chọn buổi ưu tiên"
    return errors
