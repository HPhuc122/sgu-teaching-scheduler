"""New objective baseline on a small simulated fixture; never compare v1/v2 totals."""
import argparse
import json
import os
from pathlib import Path
import sys

from compare_quality_search import ROOT, run_job


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/workload_v2_smoke_01")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists():
        parser.error("Choose a new directory; never overwrite existing experiments")
    print(json.dumps({"jobs": 2, "sessions_per_run": 12, "budget_seconds": 5, "max_starts": 3,
                      "workers": 1, "execute": args.run}), flush=True)
    if not args.run:
        return
    output.mkdir(parents=True)
    os.environ.update(DJANGO_SETTINGS_MODULE="config.settings", UCTP_DB_ENGINE="sqlite",
                      UCTP_SQLITE_PATH=str(output / "unused_parent.sqlite3"))
    sys.path.insert(0, str(ROOT / "backend"))
    import django
    django.setup()
    from school.sample_data import synthetic_rows, workbook_bytes
    from prepare_quality_experiments import build_profile
    from audit_quality_reports import audit_saved_report
    from school.models import AlgorithmRun
    from school.workload import workload_rows
    from school.models import Lecturer
    from django.db import connections

    pack = "workload_demo"
    folder = output / "data" / pack
    folder.mkdir(parents=True)
    data = synthetic_rows(sessions=12, semester_name="SGU DEMO 15 khoa - WORKLOAD_DEMO", seed=42)
    for kind, sheets in data.items():
        (folder / f"{kind}.xlsx").write_bytes(workbook_bytes(kind, sheets))
    (folder / "experiment.json").write_text(json.dumps(build_profile(folder, 20261018), ensure_ascii=False, indent=2), encoding="utf-8")
    rows = []
    for weight in (0, 1):
        workload_profile = {"format_version": 1, "simulated": True, "factor": "1.00", "quota": "120.00", "weight": weight,
                            "quotas": {str(row[0]): str(40 * (1 + i % 3)) for i, row in enumerate(data["lecturers"]["GiangVien"])}}
        profile = output / f"workload_weight{weight}.json"
        profile.write_text(json.dumps(workload_profile, indent=2), encoding="utf-8")
        job = {"pack": pack, "input_dir": folder, "mode": "multi-start", "budget": 5, "seed": 42, "workers": 1,
               "gd_policy": "adaptive", "generation_policy": "greedy-first", "cp_policy": "budget-aware",
               "workload_profile": profile, "report": output / f"weight{weight}.json",
               "database": output / f"weight{weight}.sqlite3"}
        run_job(job)
        report = json.loads(job["report"].read_text(encoding="utf-8"))
        audited = audit_saved_report(job["report"], report, pack, input_root=output / "data")
        run = AlgorithmRun.objects.get(pk=report["run_id"])
        totals = workload_rows(run.semester, Lecturer.objects.filter(employee_code__startswith="TEST_GV_"))
        rows.append({"weight": weight, "objective_version": report["objective_version"], "objective": report["objective_after"],
                     "processing_seconds": report["processing_seconds"], "audit": audited,
                     "quality_snapshot": report["quality_snapshot"], "workbook_sha256": report["workbook_sha256"],
                     "experiment_sha256": report["experiment_sha256"], "algorithm_sha256": report["algorithm_sha256"],
                     "loads": [{"employee_code": r["lecturer"].employee_code, "periods":r["actual_periods"],
                                "units": str(r["converted_units"]), "quota": str(r["effective_quota"])} for r in totals]})
        connections.close_all()
    for key in ("workbook_sha256", "experiment_sha256", "algorithm_sha256"):
        if rows[0][key] != rows[1][key]:
            raise ValueError(f"Unmatched {key}")
    (output / "summary.json").write_text(json.dumps({"note": "Separate objective baselines. Do not compare total v1/v2 scores or historical totals.",
                "simulated": True, "seed":42,"budget_seconds":5,"rows":rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"rows":[{k:v for k,v in r.items() if k not in ("quality_snapshot","loads","algorithm_sha256")} for r in rows]}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
