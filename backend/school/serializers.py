from rest_framework import serializers
from .models import TeachingQuota, WorkloadPolicy, ConversionRule

class TeachingQuotaSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeachingQuota
        fields = "__all__"

class WorkloadPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkloadPolicy
        fields = "__all__"

class ConversionRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConversionRule
        fields = "__all__"

from .models import (Building, Cohort, Course, CourseGroup, CourseProgram, Department, Faculty,
                     GroupCohort, Lecturer, LecturerPreference, Period, Room,
                     Program, ScheduleEntry, Semester, TeachingQualification)


class FacultySerializer(serializers.ModelSerializer):
    class Meta:
        model = Faculty
        fields = "__all__"


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = "__all__"


class LecturerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lecturer
        fields = ["id", "department", "employee_code", "name", "email", "status", "user"]

    def validate(self, attrs):
        if self.instance and attrs.get("status", self.instance.status) != "DangCongTac":
            if ScheduleEntry.objects.filter(lecturer=self.instance, status="DaDuyet").exists():
                raise serializers.ValidationError({"status": "Giảng viên đang có lịch đã duyệt"})
        return attrs


class CourseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = "__all__"


class ProgramSerializer(serializers.ModelSerializer):
    class Meta:
        model = Program
        fields = "__all__"


class CourseProgramSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourseProgram
        fields = "__all__"


class TeachingQualificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeachingQualification
        fields = "__all__"

    def validate(self, attrs):
        if self.instance and ScheduleEntry.objects.filter(
            lecturer=self.instance.lecturer, group__course=self.instance.course, status="DaDuyet"
        ).exists():
            if any(field in attrs and attrs[field] != getattr(self.instance, field)
                   for field in ("lecturer", "course")):
                raise serializers.ValidationError("Không thể đổi chuyên môn đang dùng trong lịch đã duyệt")
        return attrs


class SemesterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Semester
        fields = "__all__"

    def validate(self, attrs):
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start and end and end < start:
            raise serializers.ValidationError("Ngày kết thúc phải sau ngày bắt đầu")
        week_count = attrs.get("week_count", getattr(self.instance, "week_count", None))
        if self.instance and week_count is not None:
            from .models import ScheduleWeek
            if ScheduleWeek.objects.filter(entry__group__semester=self.instance, week__gt=week_count).exists():
                raise serializers.ValidationError({"week_count": "Đã có buổi học ở tuần lớn hơn giới hạn mới"})
        return attrs


class BuildingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Building
        fields = "__all__"


class RoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room
        fields = "__all__"

    def validate(self, attrs):
        if self.instance and attrs.get("status", self.instance.status) != "SanSang":
            if ScheduleEntry.objects.filter(room=self.instance, status="DaDuyet").exists():
                raise serializers.ValidationError({"status": "Phòng đang có lịch đã duyệt"})
        return attrs


class PeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = Period
        fields = "__all__"


class CourseGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourseGroup
        fields = "__all__"

    def validate(self, attrs):
        if self.instance and ScheduleEntry.objects.filter(group=self.instance).exists():
            for field in ("semester", "course", "code", "group", "lab_group", "needs_room"):
                if field in attrs and attrs[field] != getattr(self.instance, field):
                    raise serializers.ValidationError({field: "Không thể đổi khi nhóm đã có lịch"})
        if self.instance and "semester" in attrs and attrs["semester"] != self.instance.semester:
            if self.instance.cohort_links.exists():
                raise serializers.ValidationError({"semester": "Nhóm đã liên kết lớp hành chính"})
        return attrs


class CohortSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cohort
        fields = "__all__"


class GroupCohortSerializer(serializers.ModelSerializer):
    class Meta:
        model = GroupCohort
        fields = "__all__"

    def validate(self, attrs):
        group = attrs.get("group", getattr(self.instance, "group", None))
        cohort = attrs.get("cohort", getattr(self.instance, "cohort", None))
        if group and cohort and group.semester_id != cohort.semester_id:
            raise serializers.ValidationError("Lớp hành chính phải thuộc cùng học kỳ với nhóm học phần")
        if group and ScheduleEntry.objects.filter(group=group).exists():
            raise serializers.ValidationError("Không thể đổi lớp hành chính khi nhóm đã có lịch")
        return attrs


class ScheduleEntrySerializer(serializers.ModelSerializer):
    weeks = serializers.ListField(child=serializers.IntegerField(min_value=1, max_value=53),
                                  write_only=True, allow_empty=False, required=False)
    week_numbers = serializers.SerializerMethodField()

    class Meta:
        model = ScheduleEntry
        fields = ["id", "group", "lecturer", "room", "other_location", "day",
                  "start_period", "period_count", "source", "status", "weeks", "week_numbers",
                  "approved_by", "approved_at"]
        read_only_fields = ["source", "approved_by", "approved_at"]

    def get_week_numbers(self, obj):
        return sorted(week.week for week in obj.schedule_weeks.all())

    def validate(self, attrs):
        if self.instance is None and "weeks" not in attrs:
            raise serializers.ValidationError({"weeks": "Cần ít nhất một tuần học"})
        if self.instance and "group" in attrs and attrs["group"] != self.instance.group:
            raise serializers.ValidationError({"group": "Không thể đổi nhóm học phần của buổi đã tạo"})
        if "weeks" in attrs and len(attrs["weeks"]) != len(set(attrs["weeks"])):
            raise serializers.ValidationError({"weeks": "Tuần học không được lặp"})
        return attrs

    def create(self, validated_data):
        from .services import save_schedule_entry
        return save_schedule_entry(validated_data, actor=self.context["request"].user)

    def update(self, instance, validated_data):
        from .services import save_schedule_entry
        return save_schedule_entry(validated_data, instance=instance, actor=self.context["request"].user)


class LecturerPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = LecturerPreference
        fields = ["id", "semester", "kind", "day", "time_block", "priority", "note"]

    def validate(self, attrs):
        from .preference_validation import preference_errors
        values = {name: getattr(self.instance, name) for name in
                  ("kind", "day", "time_block", "priority")} if self.instance else {}
        values.update(attrs)
        errors = preference_errors(values)
        if errors:
            raise serializers.ValidationError(errors)
        return attrs
