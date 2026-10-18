"""Plan or run paired experiments on fresh SQLite databases. Dry-run by default."""

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
from statistics import mean, median
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
MODES = ("legacy", "single", "multi-start")


def experiment_plan(input_root, output_dir, repeats, budgets, base_seed, workers):
    jobs = []
    for pack in ("bo_01", "bo_02", "bo_03"):
        folder = input_root / pack
        for kind in ("courses.xlsx", "rooms.xlsx", "lecturers.xlsx", "experiment.json"):
            if not (folder / kind).is_file():
                raise ValueError(f"Thiếu dữ liệu: {folder / kind}")
        for repeat in range(repeats):
            for budget in budgets:
                # Rotate order to reduce a consistent warm-up/thermal bias.
                offset = repeat % len(MODES)
                modes = MODES[offset:] + MODES[:offset]
                for mode in modes:
                    name = f"{pack}_{mode}_{budget:g}s_seed{base_seed + repeat * 3}"
                    jobs.append({"pack": pack, "input_dir": folder, "mode": mode,
                                 "budget": budget, "seed": base_seed + repeat * 3,
                                 "workers": workers, "database": output_dir / f"{name}.sqlite3",
                                 "report": output_dir / f"{name}.json"})
    return jobs


def describe(values):
    return {"n": len(values), "mean": mean(values), "median": median(values),
            "min": min(values), "max": max(values)} if values else None


def summarize(jobs):
    groups, pairs = defaultdict(list), defaultdict(list)
    for job in jobs:
        report = json.loads(job["report"].read_text(encoding="utf-8"))
        if (report["strategy"] != job["mode"] or report["budget_seconds"] != job["budget"]
                or report["search_seed"] != job["seed"] or report["cp_workers"] != job["workers"]):
            raise ValueError(f"Báo cáo không khớp kế hoạch: {job['report']}")
        groups[(job["pack"], job["mode"], job["budget"])].append(report)
        pairs[(job["pack"], job["budget"], job["seed"])].append(report)
    for reports in pairs.values():
        if len(reports) != 3:
            raise ValueError("Thiếu phương pháp trong phép so sánh ghép cặp")
        for key in ("workbook_sha256", "experiment_sha256", "algorithm_sha256", "environment"):
            if any(report[key] != reports[0][key] for report in reports[1:]):
                raise ValueError(f"Các phương pháp không cùng điều kiện: {key}")
    summary = []
    for (pack, mode, budget), reports in sorted(groups.items()):
        feasible = [r for r in reports if r["feasible"]]
        summary.append({"pack": pack, "strategy": mode, "budget_seconds": budget,
                        "runs": len(reports), "feasible_runs": len(feasible),
                        "feasible_rate": len(feasible) / len(reports),
                        "soft_penalty_feasible_only": describe([r["objective_after"] for r in feasible]),
                        "worker_seconds_all_runs": describe([r["worker_seconds"] for r in reports]),
                        "processing_seconds_all_runs": describe([r["processing_seconds"] for r in reports]),
                        "distinct_selected_solutions_across_repeats": len({r["selected_fingerprint"]
                                                                          for r in feasible}),
                        "distinct_initial_solutions": describe([r["distinct_initial_solutions"] for r in reports]),
                        "distinct_final_solutions": describe([r["distinct_final_solutions"] for r in reports])})
    return summary


def run_job(job):
    if job["database"].exists() or job["report"].exists():
        raise ValueError(f"Không ghi đè lần đo đã có: {job['report']}")
    env = dict(os.environ, UCTP_DB_ENGINE="sqlite", UCTP_BENCHMARK="1",
               UCTP_SQLITE_PATH=str(job["database"]))
    prefix = [sys.executable, "-B", "backend/manage.py"]
    subprocess.run(prefix + ["migrate", "--noinput"], cwd=ROOT, env=env, check=True, capture_output=True)
    print(f"{job['pack']} / {job['mode']} / {job['budget']:g}s / seed {job['seed']}", flush=True)
    command = prefix + [
        "benchmark_auto_schedule", "--input-dir", str(job["input_dir"]),
        "--semester-name", f"SGU DEMO 15 khoa - {job['pack'].upper()}", "--weeks", "16",
        "--experiment-file", str(job["input_dir"] / "experiment.json"),
        "--strategy", job["mode"], "--budget-seconds", str(job["budget"]),
        "--search-seed", str(job["seed"]), "--cp-workers", str(job["workers"]),
        "--generation-policy", job.get("generation_policy", "greedy-first"),
        "--cp-policy", job.get("cp_policy", "budget-aware"),
        "--gd-policy", job.get("gd_policy", "baseline"),
        "--report", str(job["report"]),
    ]
    if job.get("cp_build_profile"):
        command += ["--cp-build-profile", str(job["cp_build_profile"])]
    if job.get("workload_profile"):
        command += ["--workload-profile", str(job["workload_profile"])]
    subprocess.run(command, cwd=ROOT, env=env, check=True, capture_output=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=ROOT / "samples/sgu_15_khoa_soft")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/quality_comparison")
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--budgets", type=float, nargs="+", default=[15, 30])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--cp-workers", type=int, default=1)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--run", action="store_true", help="Actually execute the potentially long benchmark")
    action.add_argument("--summarize-only", action="store_true", help="Read all paired reports, without running solvers")
    args = parser.parse_args()
    from math import isfinite
    if (args.repeats < 1 or args.cp_workers < 1 or len(set(args.budgets)) != len(args.budgets)
            or any(not isfinite(b) or b <= 0 for b in args.budgets)
            or args.seed < 0 or args.seed + args.repeats * 3 - 1 > 2147483647):
        parser.error("Số lượt, ngân sách, seed hoặc số worker không hợp lệ")
    jobs = experiment_plan(args.input_root.resolve(), args.output_dir.resolve(), args.repeats,
                           args.budgets, args.seed, args.cp_workers)
    if len({j["report"] for j in jobs}) != len(jobs):
        parser.error("Các ngân sách tạo tên báo cáo trùng nhau; chọn các ngân sách cách biệt hơn")
    print(json.dumps({"jobs": len(jobs), "strategies": MODES, "repeats": args.repeats,
                      "budgets_seconds": args.budgets, "cp_workers": args.cp_workers,
                      "sum_search_budget_seconds": sum(j["budget"] for j in jobs),
                      "note": "Ngân sách tìm kiếm không bao gồm toàn bộ I/O, audit và khởi tạo DB; tổng thực tế có thể lớn hơn.",
                      "execute": args.run}, ensure_ascii=True))
    if not args.run and not args.summarize_only:
        return
    if args.run:
        # Preflight the complete plan before starting any expensive work.
        if any(j["database"].exists() or j["report"].exists() for j in jobs):
            parser.error("Kế hoạch trùng database hoặc báo cáo đã có; chọn thư mục đầu ra mới")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for job in jobs:
            run_job(job)
    summary = summarize(jobs)
    destination = args.output_dir / "summary.json"
    destination.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(destination))


if __name__ == "__main__":
    main()
