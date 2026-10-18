"""Twelve targeted paired Adaptive runs, 0.5s vs 0.8s reserve; dry-run default."""
import argparse
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
from statistics import mean
import sys

from compare_quality_search import ROOT, run_job

CASES = (("bo_02", 45), *(("bo_03", seed) for seed in (42, 45, 48, 51, 54)))
ENV = {"UCTP_QUALITY_CP_REFINEMENT_SECONDS": "5", "UCTP_QUALITY_CP_MIN_SOLVE_SECONDS": "1",
       "UCTP_QUALITY_CP_MODEL_SECONDS_PER_SESSION": "0.04", "UCTP_QUALITY_CP_ESTIMATE_SAFETY_FACTOR": "1.25",
       "UCTP_QUALITY_GD_RESERVE_SECONDS": "1", "UCTP_QUALITY_GD_EXTRA_PATHS": "9",
       "UCTP_QUALITY_GD_EXTRA_PATH_SECONDS": "2", "UCTP_QUALITY_GD_EXTRA_ITERATIONS": "30000",
       "UCTP_QUALITY_GD_STAGNATION_ITERATIONS": "6000", "UCTP_QUALITY_GD_STALE_ROUNDS": "2",
       "UCTP_QUALITY_GD_MIN_PATH_SECONDS": "0.1"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write_json(path, data):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)


def initial_paths(r):
    return [(t["seed"], t.get("initial_fingerprint"),
             [(p.get("fingerprint"), p.get("score")) for p in t.get("paths", []) if p["phase"] == "initial"])
            for t in r["optimization_trials"] if t.get("kind") == "start"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/audit_reserve_confirm_15")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    jobs = []
    for index, (pack, seed) in enumerate(CASES):
        for reserve in ((0.5, 0.8) if index % 2 == 0 else (0.8, 0.5)):
            name = f"{pack}_adaptive_reserve{reserve:g}_15s_seed{seed}"
            jobs.append({"pack": pack, "input_dir": ROOT / "samples/sgu_15_khoa_soft" / pack,
                         "mode": "multi-start", "budget": 15, "seed": seed, "workers": 1,
                         "generation_policy": "greedy-first", "cp_policy": "budget-aware", "gd_policy": "adaptive",
                         "cp_build_profile": ROOT / "analysis/cp_build_observations.json",
                         "reserve": reserve, "report": output / f"{name}.json",
                         "database": output / f"{name}.sqlite3"})
    require(not output.exists(), "Choose a new output directory; never overwrite")
    for job in jobs:
        require(job["cp_build_profile"].is_file(), "Missing CP profile")
        for name in ("courses.xlsx", "rooms.xlsx", "lecturers.xlsx", "experiment.json"):
            require((job["input_dir"] / name).is_file(), f"Missing {name}")
    print(json.dumps({"jobs": len(jobs), "total_nominal_search_seconds": 180,
                      "cases": CASES, "reserves": [0.5, 0.8], "execute": args.run}), flush=True)
    if not args.run:
        return
    output.mkdir(parents=True)
    os.environ.update(ENV)
    reports = []
    for job in jobs:
        os.environ["UCTP_QUALITY_AUDIT_RESERVE_SECONDS"] = str(job["reserve"])
        print(f"Reserve: {job['reserve']}", flush=True)
        run_job(job)
        report = json.loads(job["report"].read_text(encoding="utf-8"))
        require(report["cp_budget_configuration"]["audit_reserve_seconds"] == job["reserve"], "Wrong reserve")
        require((report["strategy"], report["generation_policy"], report["cp_policy"], report["gd_policy"],
                 report["search_seed"], report["budget_seconds"], report["cp_workers"])
                == ("multi-start", "greedy-first", "budget-aware", "adaptive", job["seed"], 15, 1), "Wrong policy")
        reports.append(report)
    # Audits occur after all timed runs, not in parallel with a solver.
    os.environ.update(DJANGO_SETTINGS_MODULE="config.settings", UCTP_DB_ENGINE="sqlite",
                      UCTP_SQLITE_PATH=jobs[0]["database"].as_uri() + "?mode=ro")
    sys.path.insert(0, str(ROOT / "backend"))
    import django
    django.setup()
    from audit_quality_reports import audit_saved_report
    rows, pairs = [], []
    for job, report in zip(jobs, reports):
        audited = audit_saved_report(job["report"], report, job["pack"])
        print(f"Audit {job['pack']}/{job['seed']}/{job['reserve']}: {audited['audit']}", flush=True)
        starts = [t for t in report["optimization_trials"] if t.get("kind") == "start"]
        paths = [p for t in starts for p in t.get("paths", [])]
        rows.append({"pack": job["pack"], "seed": job["seed"], "reserve": job["reserve"],
                     "score": report["objective_after"], "status": report["status"],
                     "feasible": report["feasible"] and audited["audit"] == "PASS",
                     "processing_seconds": report["processing_seconds"], "worker_seconds": report["worker_seconds"],
                     "enqueue_seconds": report["enqueue_seconds"], "phase_seconds": report["phase_seconds"],
                     "generation_seconds": sum(t["generation_seconds"] for t in starts),
                     "gd_seconds": sum(t["improvement_seconds"] for t in starts),
                     "audit_driver_seconds": sum(t["audit_seconds"] + t.get("selection_audit_seconds", 0) for t in starts),
                     "iterations": sum(p.get("iterations", 0) for p in paths), "paths": len(paths),
                     "path_stop_reasons": dict(Counter(p["stop_reason"] for p in paths)),
                     "cp_status_counts": dict(Counter(t["generation"].get("cp_status") for t in starts)),
                     "audit": audited, "report": job["report"].name,
                     "report_sha256": sha256(job["report"].read_bytes()).hexdigest()})
    for index, (pack, seed) in enumerate(CASES):
        a, b = reports[index*2:index*2+2]
        for key in ("workbook_sha256", "experiment_sha256", "algorithm_sha256", "environment", "gd_configuration",
                    "cp_build_profile_sha256", "cp_refinement_seconds", "cp_min_solve_seconds"):
            require(a[key] == b[key], f"Unmatched condition: {key}")
        require({k: v for k, v in a["cp_budget_configuration"].items() if k != "audit_reserve_seconds"}
                == {k: v for k, v in b["cp_budget_configuration"].items() if k != "audit_reserve_seconds"}, "Other budget changed")
        old, new = [next(r for r in rows if (r["pack"], r["seed"], r["reserve"]) == (pack, seed, reserve)) for reserve in (0.5, 0.8)]
        pairs.append({"pack": pack, "seed": seed, "same_s0_and_initial_gd": initial_paths(a) == initial_paths(b),
                      "score_old": old["score"], "score_new": new["score"],
                      "score_change_new_minus_old": new["score"] - old["score"] if old["feasible"] and new["feasible"] else None,
                      "processing_old": old["processing_seconds"], "processing_new": new["processing_seconds"]})
    aggregate = []
    for reserve in (0.5, 0.8):
        selected = [r for r in rows if r["reserve"] == reserve]
        aggregate.append({"reserve": reserve, "runs": len(selected), "feasible_runs": sum(r["feasible"] for r in selected),
                          "processing_over_budget": sum(r["processing_seconds"] > 15 for r in selected),
                          "worker_over_budget": sum(r["worker_seconds"] > 15 for r in selected),
                          "mean_processing_seconds": mean(r["processing_seconds"] for r in selected),
                          "max_processing_seconds": max(r["processing_seconds"] for r in selected),
                          "mean_score": mean(r["score"] for r in selected if r["feasible"])})
    write_json(output / "summary.json", {"environment": reports[0]["environment"],
                                         "algorithm_sha256": reports[0]["algorithm_sha256"],
                                         "fixed_environment": ENV, "rows": rows, "pairs": pairs, "aggregates": aggregate})
    lines = ["# Kiểm chứng dự trữ audit — bước 3.4", "", "12 lượt mới, Adaptive ở cả hai phía; sáu cặp seed/dữ liệu, 15 giây, tối đa ba khởi tạo, một CP worker.",
             "Dữ liệu SGU mô phỏng. Không thay hàm điểm/ràng buộc/toán tử. Không dùng kết quả 30 lượt cũ đại diện cấu hình 0,8 giây.", "",
             "| Bộ | Seed | Điểm 0,5s | Điểm 0,8s | Δ điểm mới−cũ | Toàn luồng cũ | Toàn luồng mới | Cùng S0/GD đầu |",
             "|---|---:|---:|---:|---:|---:|---:|---|"]
    for p in pairs:
        lines.append(f"| {p['pack']} | {p['seed']} | {p['score_old']} | {p['score_new']} | {p['score_change_new_minus_old']} | {p['processing_old']:.3f} | {p['processing_new']:.3f} | {p['same_s0_and_initial_gd']} |")
    lines += ["", "| Dự trữ | Khả thi | Số lượt toàn luồng >15s | Worker >15s | TB thời gian | Max thời gian |",
              "|---|---|---:|---:|---:|---:|"]
    for r in aggregate:
        lines.append(f"| {r['reserve']} | {r['feasible_runs']}/{r['runs']} | {r['processing_over_budget']} | {r['worker_over_budget']} | {r['mean_processing_seconds']:.3f} | {r['max_processing_seconds']:.3f} |")
    lines += ["", "SQL execute là phần con của finalization_after_search_seconds; không cộng hai số này. Tail gồm xử lý đối tượng, SQL và commit transaction. "
              "search_including_audits_seconds gồm toàn bộ driver; audit_driver_seconds là phần con. Queue/worker-other được đo riêng. "
              "Mọi database được audit chỉ đọc sau khi đo xong; điểm và fingerprint tính lại phải khớp, checksum không đổi.", "",
              "Một lần đo mỗi cấu hình/cặp, cùng máy và thứ tự xen kẽ; sai khác thời gian tác động số vòng theo deadline. "
              "Không đủ chứng minh không giảm điểm với mọi seed hoặc cam kết SLA toàn luồng cứng."]
    with (output / "report.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    print(json.dumps({"aggregates": aggregate, "pairs": pairs}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
