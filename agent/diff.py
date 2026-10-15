"""Assignment 2, Part E: the diff of the plan against what ran.

"The one people skip" (Lecture 2, slide 54). The signature of checks/FORMATS.md,
section 10.2:

    diff(plan, trace) -> {"steps": {step_id: label}, "extra": [step numbers]}

    steps   every plan step, labelled
              executed   it ran, in plan order
              skipped    it never ran
              reordered  it ran, out of plan order
    extra   the step numbers of tool_call lines that match no plan step

How a call matches a step (match_calls, below):

  - A tool_call line with a plan_step (the planned way's executor writes one on
    every call) belongs to that step, if the step exists and calls that tool; a
    step may then own several calls, its retries.
  - A line without one (Assignment 1's ways, the transcribed runs) belongs to the
    earliest step, in plan order, that no call has matched yet, whose tool is the
    call's tool, and whose fixed arguments (every argument but "$fill") all equal
    the call's. So each such step owns at most one call: slide 51's run calls
    run_tests twice, and only one call can belong to each run_tests step.
  - Anything else is extra.

A matched step is executed if its first call comes after the first call of every
earlier matched step, and reordered if it ran before one of them.
"""

from __future__ import annotations

import json

FILL = "$fill"


def fixed_args(step: dict) -> dict:
    args = step.get("args")
    if not isinstance(args, dict):
        try:
            args = json.loads(step.get("args_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            args = {}
    return {k: v for k, v in (args if isinstance(args, dict) else {}).items() if v != FILL}


def _matches(step: dict, call: dict) -> bool:
    if not step.get("tool") or step.get("tool") != call.get("name"):
        return False
    given = call.get("input") or {}
    return all(k in given and given[k] == v for k, v in fixed_args(step).items())


def match_calls(plan: dict, trace: list[dict]) -> tuple[dict[str, list[dict]], list[dict]]:
    """Each plan step's tool_call lines, in order, and the lines that match no step."""
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    by_id = {str(s.get("id")): s for s in steps}
    owned: dict[str, list[dict]] = {str(s.get("id")): [] for s in steps}
    extra = []
    for call in (r for r in trace if r.get("type") == "tool_call"):
        if call.get("plan_step") is not None:
            key = str(call["plan_step"])
            if key in by_id and by_id[key].get("tool") == call.get("name"):
                owned[key].append(call)
            else:
                extra.append(call)
            continue
        step = next((s for s in steps if not owned[str(s.get("id"))] and _matches(s, call)), None)
        if step is None:
            extra.append(call)
        else:
            owned[str(step.get("id"))].append(call)
    return owned, extra


def diff(plan: dict, trace: list[dict]) -> dict:
    owned, extra = match_calls(plan, trace)
    position = {id(r): i for i, r in enumerate(trace)}
    labels, latest = {}, -1
    for step in (s for s in plan.get("steps") or [] if isinstance(s, dict)):
        calls = owned[str(step.get("id"))]
        if not calls:
            labels[step.get("id")] = "skipped"
            continue
        first = position[id(calls[0])]
        if first < latest:
            labels[step.get("id")] = "reordered"
        else:
            labels[step.get("id")] = "executed"
            latest = first
    return {"steps": labels, "extra": [c.get("step") for c in extra]}
