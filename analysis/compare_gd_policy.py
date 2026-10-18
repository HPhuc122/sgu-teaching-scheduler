"""Small paired GD baseline/adaptive experiment; three starts, dry-run default."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path

from compare_quality_search import ROOT, run_job


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=ROOT / "samples/sgu_15_khoa_soft")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/gd_budget_smoke")
    parser.add_argument("--packs", choices=("bo_01", "bo_02", "bo_03"), nargs="+", default=["bo_01", "bo_02"])
    parser.add_argument("--budget-seconds", type=float, default=15)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--cp-workers", type=int, default=1)
    parser.add_argument("--cp-build-profile", type=Path, default=ROOT / "analysis/cp_build_observations.json")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if (not isfinite(args.budget_seconds) or args.budget_seconds <= 0 or args.repeats < 1
            or args.cp_workers < 1 or args.seed < 0 or args.seed + args.repeats * 3 - 1 > 2147483647
            or len(args.packs) != len(set(args.packs))):
        parser.error("Invalid budget, seed, repeats, workers or packs")
    output = args.output_dir.resolve()
    profile = args.cp_build_profile.resolve()
    if not profile.is_file():
        parser.error(f"Missing profile: {profile}")
    jobs = []
    for pack_index, pack in enumerate(args.packs):
        folder = args.input_root.resolve() / pack
        for name in ("courses.xlsx", "rooms.xlsx", "lecturers.xlsx", "experiment.json"):
            if not (folder / name).is_file():
                parser.error(f"Missing input: {folder / name}")
        for repeat in range(args.repeats):
            policies = ("baseline", "adaptive")
            if (pack_index + repeat) % 2:
                policies = policies[::-1]
            for policy in policies:
                seed = args.seed + repeat * 3
                name = f"{pack}_{policy}_{args.budget_seconds:g}s_seed{seed}"
                jobs.append({"pack": pack, "input_dir": folder, "mode": "multi-start",
                             "budget": args.budget_seconds, "seed": seed, "workers": args.cp_workers,
                             "generation_policy": "greedy-first", "cp_policy": "budget-aware",
                             "gd_policy": policy, "cp_build_profile": profile,
                             "report": output / f"{name}.json", "database": output / f"{name}.sqlite3"})
    if (output / "summary.json").exists() or any(j["database"].exists() or j["report"].exists() for j in jobs):
        parser.error("Output exists; choose a fresh directory")
    print(json.dumps({"jobs": len(jobs), "strategy": "multi-start", "max_starts": 3,
                      "sum_search_budget_seconds": sum(j["budget"] for j in jobs), "execute": args.run}))
    if not args.run:
        return
    output.mkdir(parents=True, exist_ok=True)
    reports, rows, pairs = [], [], []
    for job in jobs:
        print(f"GD policy: {job['gd_policy']}", flush=True)
        run_job(job)
        r = json.loads(job["report"].read_text(encoding="utf-8"))
        if (r["strategy"], r["generation_policy"], r["cp_policy"], r["gd_policy"],
                r["search_seed"], r["budget_seconds"], r["cp_workers"]) != (
                "multi-start", "greedy-first", "budget-aware", job["gd_policy"],
                job["seed"], job["budget"], job["workers"]):
            raise ValueError("Report differs from experiment plan")
        reports.append(r)
        starts = [t for t in r["optimization_trials"] if t.get("kind") == "start"]
        paths = [p for t in starts for p in t.get("paths", [])]
        rows.append({"pack": job["pack"], "seed": job["seed"], "policy": job["gd_policy"],
                     "feasible": r["feasible"], "status": r["status"], "score_before": r["objective_before"],
                     "score_after": r["objective_after"], "processing_seconds": r["processing_seconds"],
                     "initial_starts": len(starts), "distinct_initial_solutions": r["distinct_initial_solutions"],
                     "initial_gd_paths": sum(p["phase"] == "initial" for p in paths),
                     "extra_gd_paths": sum(p["phase"] == "extra" for p in paths),
                     "gd_seconds": sum(t["improvement_seconds"] for t in starts),
                     "extra_gd_seconds": sum(t.get("extra_gd_seconds", 0) for t in starts),
                     "gd_allocated_seconds": sum(t["gd_allocated_seconds"] for t in starts),
                     "counters": {k: sum(p.get(k, 0) for p in paths) for k in
                                  ("iterations", "proposals", "valid_moves", "accepted_moves", "score_improvements")},
                     "path_stop_reasons": dict(Counter(p["stop_reason"] for p in paths)),
                     "generation_seconds": sum(t["generation_seconds"] for t in starts),
                     "audit_seconds": sum(t["audit_seconds"] + t.get("selection_audit_seconds", 0) for t in starts),
                     "starts": starts, "report": str(job["report"])})
    for offset in range(0, len(reports), 2):
        left, right = reports[offset:offset + 2]
        for key in ("workbook_sha256", "experiment_sha256", "algorithm_sha256", "environment",
                    "strategy", "generation_policy", "cp_policy", "search_seed", "budget_seconds", "cp_workers",
                    "cp_build_profile_sha256", "cp_budget_configuration", "cp_refinement_seconds",
                    "cp_min_solve_seconds", "gd_configuration"):
            if left[key] != right[key]:
                raise ValueError(f"Unmatched experimental condition: {key}")
        def initial_paths(report):
            return [(t["seed"], t.get("initial_fingerprint"),
                     [p.get("fingerprint") for p in t.get("paths", []) if p["phase"] == "initial"])
                    for t in report["optimization_trials"] if t.get("kind") == "start"]
        pairs.append({"pack": jobs[offset]["pack"], "seed": left["search_seed"],
                      "same_initial_starts_and_first_gd": initial_paths(left) == initial_paths(right)})
    snapshot = ROOT / "analysis/baselines/great_deluge_3_1_2.py"
    result = {"baseline_snapshot_sha256": sha256(snapshot.read_bytes()).hexdigest(), "rows": rows, "pairs": pairs}
    (output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"rows": [{k: v for k, v in row.items() if k != "starts"} for row in rows],
                      "pairs": pairs}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
