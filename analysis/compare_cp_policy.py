"""Paired fixed-window vs budget-aware CP admission; dry-run by default."""

import argparse
import json
from math import isfinite
from pathlib import Path

from compare_quality_search import ROOT, run_job


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=ROOT / "samples/sgu_15_khoa_soft")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/cp_admission_smoke")
    parser.add_argument("--packs", nargs="+", choices=("bo_01", "bo_02", "bo_03"), default=["bo_01", "bo_02"])
    parser.add_argument("--budget-seconds", type=float, default=15)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--cp-workers", type=int, default=1)
    parser.add_argument("--strategy", choices=("single", "multi-start"), default="single")
    parser.add_argument("--cp-build-profile", type=Path, default=ROOT / "analysis/cp_build_observations.json")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if (not isfinite(args.budget_seconds) or args.budget_seconds <= 0 or args.repeats < 1
            or args.cp_workers < 1 or args.seed < 0 or args.seed + args.repeats * 3 - 1 > 2147483647
            or len(set(args.packs)) != len(args.packs)):
        parser.error("Invalid budget, repeats, seed, packs or workers")
    output = args.output_dir.resolve()
    profile = args.cp_build_profile.resolve()
    if not profile.is_file():
        parser.error(f"Missing CP cost profile: {profile}")
    jobs = []
    for pack_index, pack in enumerate(args.packs):
        folder = args.input_root.resolve() / pack
        for name in ("courses.xlsx", "rooms.xlsx", "lecturers.xlsx", "experiment.json"):
            if not (folder / name).is_file():
                parser.error(f"Missing input: {folder / name}")
        for repeat in range(args.repeats):
            policies = ("fixed-window", "budget-aware")
            if (pack_index + repeat) % 2:
                policies = policies[::-1]
            for policy in policies:
                seed = args.seed + repeat * 3
                name = f"{pack}_{policy}_{args.strategy}_{args.budget_seconds:g}s_seed{seed}"
                jobs.append({"pack": pack, "input_dir": folder, "mode": args.strategy,
                             "budget": args.budget_seconds, "seed": seed, "workers": args.cp_workers,
                             "generation_policy": "greedy-first", "cp_policy": policy,
                             "cp_build_profile": profile, "report": output / f"{name}.json",
                             "database": output / f"{name}.sqlite3"})
    if (output / "summary.json").exists() or any(j["report"].exists() or j["database"].exists() for j in jobs):
        parser.error("Output exists; choose a fresh directory")
    print(json.dumps({"jobs": len(jobs), "strategy": args.strategy,
                      "sum_search_budget_seconds": sum(j["budget"] for j in jobs), "execute": args.run}))
    if not args.run:
        return
    output.mkdir(parents=True, exist_ok=True)
    reports, rows = [], []
    for job in jobs:
        print(f"CP policy: {job['cp_policy']}", flush=True)
        run_job(job)
        r = json.loads(job["report"].read_text(encoding="utf-8"))
        if (r["cp_policy"], r["search_seed"], r["strategy"], r["budget_seconds"], r["cp_workers"]) != (
                job["cp_policy"], job["seed"], job["mode"], job["budget"], job["workers"]):
            raise ValueError("Report does not match experiment plan")
        reports.append(r)
        starts = [t for t in r["optimization_trials"] if t.get("kind") == "start"]
        rows.append({"pack": job["pack"], "policy": r["cp_policy"], "seed": r["search_seed"],
                     "feasible": r["feasible"], "status": r["status"],
                     "score_before": r["objective_before"], "score_after": r["objective_after"],
                     "processing_seconds": r["processing_seconds"],
                     "generation_seconds": sum(t["generation_seconds"] for t in starts),
                     "improvement_seconds": sum(t["improvement_seconds"] for t in starts),
                     "gd_allocated_seconds": sum(t["gd_allocated_seconds"] for t in starts),
                     "gd_calls": sum(t["gd_calls"] for t in starts),
                     "gd_unused_seconds": sum(t["gd_unused_seconds"] for t in starts),
                     "starts": starts, "report": str(job["report"])})
    for offset in range(0, len(reports), 2):
        left, right = reports[offset:offset + 2]
        for key in ("workbook_sha256", "experiment_sha256", "algorithm_sha256", "environment",
                    "search_seed", "budget_seconds", "cp_workers", "strategy", "generation_policy",
                    "cp_build_profile_sha256", "cp_budget_configuration", "cp_refinement_seconds", "cp_min_solve_seconds"):
            if left[key] != right[key]:
                raise ValueError(f"Different comparison condition: {key}")
    (output / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
