"""Cooperative wall-clock deadlines for scheduling, including model construction."""

import json
from math import isfinite
from pathlib import Path
from time import monotonic


class SearchBudgetExpired(Exception):
    pass


def check_deadline(deadline):
    if deadline is not None and monotonic() >= deadline:
        raise SearchBudgetExpired


def load_cp_observations(path):
    """Explicit operator profile, never inferred by scanning benchmark outputs."""
    if not path:
        return ()
    profile = json.loads(Path(path).read_text(encoding="utf-8"))
    if profile.get("format_version") != 1:
        raise ValueError("Unsupported CP build profile")
    rows = profile["observations"]
    for row in rows:
        if (type(row["sessions"]) is not int or row["sessions"] < 1
                or type(row["model_complete"]) is not bool
                or not isfinite(row["seconds"]) or row["seconds"] <= 0):
            raise ValueError("Invalid CP build observation")
    return tuple(rows)


def estimate_cp_build(sessions, observations=(), *, seconds_per_session=0.04, safety_factor=1.25):
    """Planning estimate, not a runtime bound. Censored timings are lower bounds.

    Only match the same session count; do not extrapolate a timeout at another
    size into a completed-model measurement. The configured prior covers gaps.
    Model density/hardware can still invalidate this estimate; deadlines remain.
    """
    if (not isfinite(seconds_per_session) or seconds_per_session <= 0
            or not isfinite(safety_factor) or safety_factor < 1):
        raise ValueError("Invalid CP cost estimate configuration")
    matched = [row for row in observations if row["sessions"] == sessions]
    observed = max((row["seconds"] for row in matched), default=0)
    return {"seconds": max(0.05, sessions * seconds_per_session, observed) * safety_factor,
            "source": "OBSERVATIONS_AND_PRIOR" if matched else "CONFIGURED_PRIOR",
            "observations": len(matched),
            "censored_observations": sum(not row["model_complete"] for row in matched)}


def trial_budget(now, deadline, *, gd_reserve, audit_reserve):
    """Reserve downstream work within this start, without borrowing later starts."""
    if any(not isfinite(v) or v < 0 for v in (gd_reserve, audit_reserve)):
        raise ValueError("Invalid downstream reserve")
    remaining = max(0, deadline - now)
    audit = min(audit_reserve, remaining * 0.1)
    gd = min(gd_reserve, remaining * 0.2)
    return {"generation_deadline": min(now + remaining * 0.8, deadline - gd - audit),
            "improvement_deadline": deadline - audit,
            "gd_reserved_seconds": gd, "audit_reserved_seconds": audit}


def cp_budget(now, deadline, *, has_seed, estimate, refinement_seconds, min_solve_seconds,
              audit_reserve, cp_time_limit):
    """Admit an improvement only if model + solver fit. Rescue may take a risk."""
    if not isfinite(audit_reserve) or audit_reserve < 0:
        raise ValueError("Invalid candidate audit reserve")
    remaining = max(0, deadline - now) if deadline is not None else refinement_seconds + audit_reserve
    available = max(0, remaining - audit_reserve)
    required = estimate["seconds"] + min_solve_seconds
    decision = {"cp_remaining_seconds": remaining, "cp_available_seconds": available,
                "cp_required_seconds": required, "cp_estimate": estimate,
                "cp_candidate_audit_reserved_seconds": audit_reserve,
                "cp_min_solve_seconds": min_solve_seconds}
    if min(available, cp_time_limit) < min_solve_seconds or (has_seed and available < required):
        decision.update(cp_decision="SKIPPED_BUDGET", cp_allocated_seconds=0)
        return decision
    # A larger model may receive more than the former fixed window only when
    # the actual generation allocation can cover it, with GD/audits protected.
    allocated = min(available, max(refinement_seconds, required)) if has_seed else available
    decision.update(cp_decision="RUN_IMPROVEMENT" if has_seed else "RUN_RESCUE",
                    cp_allocated_seconds=allocated, cp_deadline=now + allocated,
                    cp_build_deadline=now + allocated - min_solve_seconds,
                    cp_estimate_exceeds_budget=estimate["seconds"] > allocated - min_solve_seconds)
    return decision


def extra_gd_budget(now, deadline, *, eligible_starts, path_seconds, audit_reserve, min_seconds):
    """Share leftover time after all initial starts, keeping final audit time."""
    if (eligible_starts < 1 or any(not isfinite(v) or v < 0
                                  for v in (path_seconds, audit_reserve, min_seconds))
            or path_seconds <= 0 or min_seconds <= 0):
        raise ValueError("Invalid extra GD budget")
    usable = max(0, deadline - now - audit_reserve)
    limit = min(path_seconds, usable / eligible_starts)
    return limit if limit >= min_seconds else 0
