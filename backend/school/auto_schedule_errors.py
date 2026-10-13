"""Structured input errors for the three-workbook scheduling flow."""

FILE_LABELS = {"courses": "Học phần", "rooms": "Phòng học", "lecturers": "Giảng viên"}


def issue(kind, sheet, line, message):
    return {"file": FILE_LABELS[kind], "sheet": sheet or "", "line": line,
            "message": str(message)}


class InputIssues(ValueError):
    def __init__(self, issues):
        self.issues = list(issues)
        super().__init__("\n".join(self._describe(row) for row in self.issues))

    @staticmethod
    def _describe(row):
        location = ", ".join(part for part in (
            f"File {row['file']}" if row["file"] else "",
            f"sheet {row['sheet']}" if row["sheet"] else "",
            f"dòng {row['line']}" if row["line"] else "",
        ) if part)
        return f"{location}: {row['message']}" if location else row["message"]
