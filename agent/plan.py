"""Assignment 2, Parts A and C: the planner and the reviser.

The contract (checks/FORMATS.md, section 10). The checker calls both functions
directly, with a scripted model that keeps a copy of every request, so keep these
exact signatures. Extra keyword arguments have defaults; the checker passes only these.

    make_plan(client, issue_number, tool_schemas, trace=None) -> dict
    revise_plan(client, plan, step_results, trace=None) -> dict

make_plan writes the plan and stops (Lecture 2, slide 15). Its request carries the
task, the issue number and the tool list, and nothing from the issue: not its body,
not its title. The plan comes back as data: the model is offered one tool,
submit_plan, whose input_schema is agent/plan_schema.json, marked strict.

revise_plan repairs before it replaces. A step whose status is done comes back
unchanged, every field but status, whatever the model wrote; a failed step may be
changed to retry it, and any step not yet run may change. Its request carries the
plan and structured step results only (status, counts, paths, error codes): never
the issue's text, and never a step result's `args`, which the executor may have
filled in from the issue.

Neither function sanitises what the model returned. The plan's steps are the
model's own, so ways/planned.py can check them against the schema, which a vendor
that accepts "strict" without enforcing it may not have.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "agent" / "plan_schema.json"
PLAN_TOOL = "submit_plan"
PLANNER_PROMPT = "prompts/planner.md"
REVISER_PROMPT = "prompts/reviser.md"

# What a reviser may see of a step result: never `args` (section 10.3).
RESULT_FIELDS = ("id", "tool", "status", "count", "paths", "error_code")


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def plan_tool() -> dict:
    """The planner's and the reviser's one tool: its input is a plan, in our schema."""
    return {
        "name": PLAN_TOOL,
        "description": "Submit the plan: the steps RepoMind will run, in order.",
        "input_schema": load_schema(),
        "strict": True,
    }


def describe_tools(tool_schemas: list[dict]) -> str:
    """The tool list as the planner reads it: name, description and arguments."""
    lines = []
    for t in tool_schemas:
        schema = t.get("input_schema") or {}
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        args = ", ".join(f"{name} ({p.get('type', 'any')}{'' if name in required else ', optional'})"
                         for name, p in props.items())
        lines.append(f"- {t['name']}: {t.get('description', '')} Arguments: {args or 'none'}.")
    return "\n".join(lines)


def _plan_call(response) -> dict | None:
    """The input of the response's submit_plan call, or None if the model answered otherwise."""
    for call in response.tool_calls:
        if call.name == PLAN_TOOL and isinstance(call.input, dict):
            return call.input
    return None


def _meta(response, prompt: str, tool_names: list[str], **extra) -> dict:
    return {"model": response.model, "prompt": prompt, "tools": list(tool_names), **extra}


def make_plan(client, issue_number: int, tool_schemas: list[dict], trace=None, *, feedback=None) -> dict:
    """Write the plan for one issue. `feedback`, on a re-plan, lists why the last plan
    was rejected: schema errors and validator failures, never issue text."""
    names = [t["name"] for t in tool_schemas]
    text = (f"Write the plan to triage issue #{int(issue_number)}.\n\n"
            f"The tools the plan may use:\n{describe_tools(tool_schemas)}")
    if feedback:
        text += ("\n\nYour last plan was rejected before it ran, for these reasons. Write a new plan "
                 "that fixes every one:\n" + "\n".join(f"- {f}" for f in feedback))
    system = (ROOT / PLANNER_PROMPT).read_text()
    response = client.create(system=system, messages=[{"role": "user", "content": text}], tools=[plan_tool()])
    if trace is not None:
        trace.model_call(0, response, purpose="plan")
    raw = _plan_call(response)
    if raw is None:   # answered in prose: an empty plan, which the way rejects
        return {"steps": [], "meta": _meta(response, PLANNER_PROMPT, names, rejected="no submit_plan call")}
    plan = copy.deepcopy(raw)
    plan["meta"] = _meta(response, PLANNER_PROMPT, names)
    return plan


def _readable(step) -> dict:
    """A step as the reviser reads it: args_json decoded into `args`, so the model never
    sees, and copies, a JSON string escaped inside JSON."""
    if not isinstance(step, dict) or "args_json" not in step:
        return step
    out = {k: v for k, v in step.items() if k != "args_json"}
    try:
        out["args"] = json.loads(step["args_json"])
    except (TypeError, json.JSONDecodeError):
        out["args_json"] = step["args_json"]
    return out


def _without_status(step) -> dict:
    return {k: v for k, v in (step or {}).items() if k != "status"} if isinstance(step, dict) else {}


def merge_revision(old_steps: list[dict], new_steps: list) -> list[dict]:
    """The revised step list: done steps exactly as they were, in their places; the
    model's versions of everything else. A failed step the model left as it was stays
    failed (nothing changed, so there is nothing to retry); any other step it wrote is
    pending, whatever status it gave."""
    old = [s for s in old_steps if isinstance(s, dict)]
    new = [s for s in new_steps if isinstance(s, dict)] if isinstance(new_steps, list) else []
    done = {str(s.get("id")) for s in old if s.get("status") == "done"}
    by_id = {str(s.get("id")): s for s in old}
    mine = {}
    for s in new:
        if str(s.get("id")) not in done:
            mine.setdefault(str(s.get("id")), s)

    def theirs(s):
        s = copy.deepcopy(s)
        before = by_id.get(str(s.get("id")))
        unchanged = before is not None and _without_status(before) == _without_status(s)
        s["status"] = "failed" if unchanged and before.get("status") == "failed" else "pending"
        return s

    last_done = max((i for i, s in enumerate(old) if s.get("status") == "done"), default=-1)
    out, placed = [], set()
    for s in old[:last_done + 1]:
        key = str(s.get("id"))
        if key in done:
            out.append(copy.deepcopy(s))
        elif key in mine:
            out.append(theirs(mine[key]))
            placed.add(key)
    for s in new:
        key = str(s.get("id"))
        if key not in done and key not in placed:
            out.append(theirs(s))
            placed.add(key)
    return out


def revise_plan(client, plan: dict, step_results: list[dict], trace=None, *, step: int = 0,
                checkpoint: str = "after_search") -> dict:
    """The next version of the plan, from the active plan and structured step results."""
    shown = {k: v for k, v in plan.items() if k != "meta"}
    shown["steps"] = [_readable(s) for s in plan.get("steps") or []]
    results = [{k: r.get(k) for k in RESULT_FIELDS} for r in step_results]
    text = (f"The checkpoint {checkpoint!r} failed.\n\n"
            "The active plan, with each step's status. Each step's arguments are shown here as an object, "
            "`args`; in submit_plan write them as `args_json`, the same object encoded as a JSON string, "
            "such as {\"query\": \"$fill\", \"max_results\": 20}.\n"
            f"{json.dumps(shown, indent=2)}\n\n"
            f"The results of the steps that ran, in the order they ran:\n{json.dumps(results, indent=2)}\n\n"
            "Return the repaired plan with submit_plan.")
    system = (ROOT / REVISER_PROMPT).read_text()
    response = client.create(system=system, messages=[{"role": "user", "content": text}], tools=[plan_tool()])
    if trace is not None:
        trace.model_call(step, response, purpose="revise")
    raw = _plan_call(response) or {}
    tools = (plan.get("meta") or {}).get("tools") or []
    revised = {k: copy.deepcopy(v) for k, v in raw.items() if k not in ("steps", "meta")}
    revised["steps"] = merge_revision(plan.get("steps") or [], raw.get("steps"))
    revised["meta"] = _meta(response, REVISER_PROMPT, tools,
                            **({} if raw else {"rejected": "no submit_plan call"}))
    return revised
