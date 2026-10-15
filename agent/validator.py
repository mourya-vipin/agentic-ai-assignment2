"""Assignment 2, Part B: the validator.

Four checks you can run before anything executes (Lecture 2, slide 17), defined
exactly in checks/FORMATS.md, section 10.2:

    validate(plan) -> {"valid": bool, "failures": [{"step": id, "check": n}]}

    1  every referenced tool exists: a step's tool is in the plan's own list,
       plan["meta"]["tools"] (a step with no tool fails check 3, not check 1)
    2  no step depends on a later step: every id in depends_on is an earlier step's
       (a dependency on itself, or on a step that does not exist, fails too)
    3  every step has an observable outcome: a tool, and an expected_result
    4  the step count is within bounds: at least one, and at most max_steps in
       agent/bounds.yaml

The other half is in ways/planned.py: a plan that fails is rejected, re-planned up
to MAX_REPLANS, then escalated. Never executed.
"""

from __future__ import annotations

from agent.loop import load_bounds


def _blank(value) -> bool:
    return value is None or not str(value).strip()


def validate(plan: dict, *, max_steps: int | None = None) -> dict:
    limit = load_bounds().max_steps if max_steps is None else max_steps
    meta = plan.get("meta") if isinstance(plan, dict) else None
    tools = set((meta or {}).get("tools") or [])
    raw = plan.get("steps") if isinstance(plan, dict) else None
    steps = [s for s in raw if isinstance(s, dict)] if isinstance(raw, list) else []

    failures = []
    earlier: set[str] = set()   # ids compared as text, so 2 and "2" are the same step
    for step in steps:
        sid = step.get("id")
        tool = step.get("tool")
        if not _blank(tool) and tool not in tools:
            failures.append({"step": sid, "check": 1})
        deps = step.get("depends_on") or []
        if not isinstance(deps, list) or any(str(d) not in earlier for d in deps):
            failures.append({"step": sid, "check": 2})
        if _blank(tool) or _blank(step.get("expected_result")):
            failures.append({"step": sid, "check": 3})
        earlier.add(str(sid))
    if not 1 <= len(steps) <= limit:
        failures.append({"step": None, "check": 4})
    return {"valid": not failures, "failures": failures}
