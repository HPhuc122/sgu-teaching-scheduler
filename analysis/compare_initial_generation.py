"""Small paired generation-policy control. Dry-run unless --run is supplied."""

import argparse
import json
from math import isfinite
from pathlib import Path

from compare_quality_search import ROOT, run_job


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=ROOT / "samples/sgu_15_khoa_soft/bo_01")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/initial_generation_smoke")
    parser.add_argument("--budget-seconds", type=float, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--cp-workers", type=int, default=1)
    parser.add_argument("--strategy", choices=("single", "multi-start"), default="single")
    parser.add_argument("--cp-policy", choices=("fixed-window", "budget-aware"), default="fixed-window",
                        help="Use fixed-window to isolate the original ordering comparison")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if (not isfinite(args.budget_seconds) or args.budget_seconds <= 0 or args.repeats < 1
            or args.cp_workers < 1 or args.seed < 0 or args.seed + 3 * args.repeats - 1 > 2147483647):
        parser.error("Invalid time budget, repeats, seed or workers")
    folder, destination = args.input_dir.resolve(), args.output_dir.resolve()
    for name in ("courses.xlsx", "rooms.xlsx", "lecturers.xlsx", "experiment.json"):
        if not (folder / name).is_file():
            parser.error(f"Missing input: {folder / name}")
    jobs = []
    for repeat in range(args.repeats):
        policies = ("model-first", "greedy-first")
        if repeat % 2:
            policies = policies[::-1]
        for policy in policies:
            seed = args.seed + repeat * 3
            name = f"{policy}_{args.strategy}_{args.budget_seconds:g}s_seed{seed}"
            jobs.append({"pack": folder.name, "input_dir": folder, "mode": args.strategy,
                         "budget": args.budget_seconds, "seed": seed, "workers": args.cp_workers,
                         "generation_policy": policy, "report": destination / f"{name}.json",
                         "cp_policy": args.cp_policy,
                         "database": destination / f"{name}.sqlite3"})
    if (destination / "summary.json").exists() or any(
            j["report"].exists() or j["database"].exists() for j in jobs):
        parser.error("Output already exists; choose a fresh output directory")
    print(json.dumps({"jobs": len(jobs), "strategy": args.strategy,
                      "sum_search_budget_seconds": sum(j["budget"] for j in jobs),
                      "execute": args.run, "note": "Includes neither DB setup nor all mandatory audit/I/O time."}))
    if not args.run:
        return
    destination.mkdir(parents=True, exist_ok=True)
    reports, rows = [], []
    for job in jobs:
        print(f"Generation policy: {job['generation_policy']}", flush=True)
        run_job(job)
        report = json.loads(job["report"].read_text(encoding="utf-8"))
        reports.append(report)
        starts = [t for t in report["optimization_trials"] if t.get("kind") == "start"]
        rows.append({"policy": report["generation_policy"], "seed": report["search_seed"],
                     "strategy": report["strategy"], "feasible": report["feasible"],
                     "status": report["status"], "soft_penalty": report["objective_after"],
                     "processing_seconds": report["processing_seconds"],
                     "distinct_initial_solutions": report["distinct_initial_solutions"],
                     "generation_seconds": sum(t["generation_seconds"] for t in starts),
                     "generation": [t["generation"] for t in starts],
                     "report": str(job["report"])})
    for offset in range(0, len(reports), 2):
        left, right = reports[offset:offset + 2]
        for key in ("workbook_sha256", "experiment_sha256", "algorithm_sha256", "environment",
                    "search_seed", "budget_seconds", "cp_workers", "strategy",
                    "cp_refinement_seconds", "cp_min_solve_seconds"):
            if left[key] != right[key]:
                raise ValueError(f"Unmatched comparison conditions: {key}")
    (destination / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
