from django import forms

from .models import Lecturer, LecturerPreference, Period, Room, ScheduleEntry, Semester
from .schedule_import import parse_weeks


class ScheduleReviewForm(forms.Form):
    lecturer = forms.ModelChoiceField(queryset=Lecturer.objects.none(), required=False, label="Giảng viên")
    room = forms.ModelChoiceField(queryset=Room.objects.none(), required=False, label="Phòng học")
    other_location = forms.CharField(max_length=100, required=False, label="Địa điểm khác")
    day = forms.TypedChoiceField(coerce=int, choices=[(day, f"Thứ {day}") for day in range(2, 8)] + [(8, "Chủ nhật")],
                                 label="Thứ")
    start_period = forms.ModelChoiceField(queryset=Period.objects.all().order_by("id"), label="Tiết bắt đầu")
    period_count = forms.IntegerField(min_value=1, max_value=13, label="Số tiết")
    weeks = forms.CharField(label="Tuần học", help_text="Ví dụ: 1-10,12,14-16")

    def __init__(self, *args, entry=None, **kwargs):
        if (entry is not None and (not args or args[0] is None)
                and kwargs.get("data") is None and "initial" not in kwargs):
            kwargs["initial"] = {
                "lecturer": entry.lecturer_id, "room": entry.room_id,
                "other_location": entry.other_location or "", "day": entry.day,
                "start_period": entry.start_period_id, "period_count": entry.period_count,
                "weeks": ",".join(str(week.week) for week in entry.schedule_weeks.all()),
            }
        super().__init__(*args, **kwargs)
        self.fields["lecturer"].queryset = Lecturer.objects.all().order_by("name")
        self.fields["room"].queryset = Room.objects.all().order_by("code")

    def clean_weeks(self):
        try:
            return parse_weeks(self.cleaned_data["weeks"])
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc

    def clean(self):
        values = super().clean()
        if values.get("room") and values.get("other_location"):
            self.add_error("other_location", "Chỉ chọn phòng hoặc địa điểm khác")
        return values


class PreferenceForm(forms.ModelForm):
    class Meta:
        model = LecturerPreference
        fields = ["semester", "kind", "day", "time_block", "priority", "note"]
        labels = {
            "semester": "Học kỳ", "kind": "Loại nguyện vọng", "day": "Thứ",
            "time_block": "Buổi", "priority": "Mức ưu tiên", "note": "Ghi chú",
        }
        widgets = {
            "kind": forms.Select(choices=[("KhungGio", "Ưu tiên khung giờ"), ("NgayNghi", "Ngày không thể dạy")]),
            "day": forms.Select(choices=[("", "Không chọn")] + [(day, f"Thứ {day}") for day in range(2, 8)] + [(8, "Chủ nhật")]),
            "time_block": forms.Select(choices=[("", "Không chọn"), ("Sang", "Sáng"),
                                               ("Chieu", "Chiều"), ("Toi", "Tối")]),
            "priority": forms.Select(choices=[(1, "Rất ưu tiên"), (2, "Ưu tiên"),
                                               (3, "Không ưu tiên"), (4, "Tránh")]),
            "note": forms.TextInput(attrs={"placeholder": "Chi tiết cần lưu ý"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["semester"].queryset = Semester.objects.exclude(status="DaKhoa")
        self.fields["day"].required = False
        self.fields["time_block"].required = False

    def clean(self):
        data = super().clean()
        from .preference_validation import preference_errors
        for field, message in preference_errors(data).items():
            if field not in self.errors:
                self.add_error(field, message)
        return data
