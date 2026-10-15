"""Assignment 2, Part E: three detectors, and Lecture 2's ladder.

Three of the four plan failures have a detector of a few lines over a trace
(Lecture 2, slides 45 to 49); the validator is the fourth. The signatures of
checks/FORMATS.md, section 10.2:

    repeat_check(trace) -> list[list]                 circular reasoning
    orphan_check(plan) -> list                        hallucinated steps
    expected_result_check(plan, trace) -> list        premature stopping, in part
    ladder(plan, trace) -> {"q1": ..., "q2": ..., "q3": ...}

`trace` is a list of trace lines, as harness.trace.read_trace returns them.

    python -m agent.detectors      # both recorded runs' ladders and slide 51's diff
"""

from __future__ import annotations

import json

from agent.diff import diff, match_calls


def _key(call: dict) -> str:
    return json.dumps([call.get("name"), call.get("input") or {}], sort_keys=True)


def repeat_check(trace: list[dict]) -> list[list]:
    """Exact repeats: tool_call lines with the same tool and the same arguments,
    each group as the step numbers of its lines, in the order the groups began."""
    groups: dict[str, list] = {}
    for call in (r for r in trace if r.get("type") == "tool_call"):
        groups.setdefault(_key(call), []).append(call.get("step"))
    return [steps for steps in groups.values() if len(steps) > 1]


def orphan_check(plan: dict) -> list:
    """The ids of the steps, other than the last, that no later step lists in depends_on."""
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    orphans = []
    for i, step in enumerate(steps[:-1]):
        later = {str(d) for s in steps[i + 1:] for d in s.get("depends_on") or []}
        if str(step.get("id")) not in later:
            orphans.append(step.get("id"))
    return orphans


def expected_result_check(plan: dict, trace: list[dict]) -> list:
    """The ids of the plan steps that did not run and return their result: no call
    matched them (agent/diff.py's matching), or the last call that did was an error."""
    owned, _ = match_calls(plan, trace)
    missing = []
    for step in (s for s in plan.get("steps") or [] if isinstance(s, dict)):
        calls = owned[str(step.get("id"))]
        if not calls or calls[-1].get("is_error"):
            missing.append(step.get("id"))
    return missing


def unused_from_trace(trace: list[dict]) -> list:
    """Question 2 for a plan with no depends_on, answered from the trace, as a judgment:
    a call's result was not used if the run later made the exact same call again
    (it asked for the same result instead of using the one it had). Returns the
    step numbers of the first call of each such pair."""
    calls = [r for r in trace if r.get("type") == "tool_call"]
    unused = []
    for i, call in enumerate(calls):
        if any(_key(later) == _key(call) for later in calls[i + 1:]) and call.get("step") not in unused:
            if not any(_key(earlier) == _key(call) for earlier in calls[:i]):
                unused.append(call.get("step"))
    return unused


def ladder(plan: dict, trace: list[dict]) -> dict:
    """Lecture 2's questions 1 to 3 (slide 50); question 4 needs judgment, in the report."""
    repeats = repeat_check(trace)
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    if any("depends_on" in s for s in steps):
        unused = orphan_check(plan)
    else:   # no dependency graph to walk: judge from the trace (step numbers)
        unused = unused_from_trace(trace)
    missing = expected_result_check(plan, trace)
    return {"q1": {"fired": bool(repeats), "ids": repeats},
            "q2": {"fired": bool(unused), "ids": unused},
            "q3": {"fired": bool(missing), "ids": missing}}


if __name__ == "__main__":
    from harness import ROOT
    from harness.trace import read_trace

    for run in ("looping", "s49"):
        folder = ROOT / "fixtures" / "traces" / run
        plan, trace = json.loads((folder / "plan.json").read_text()), read_trace(folder / "trace.jsonl")
        print(run, json.dumps(ladder(plan, trace)))
        print(run, "diff", json.dumps(diff(plan, trace)))
