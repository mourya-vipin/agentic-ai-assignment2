"""Assignment 2's results script: builds reports/LAB_02.json from the code, runs/ and the tracker.

    python -m eval.lab02            # writes reports/LAB_02.json, prints Part F's and Part G's tables
    python -m eval.lab02 --dry-run  # prints, writes nothing

Every field follows checks/FORMATS.md, section 10.10. Success is decided by Assignment
1's grounded check, eval/check_triage.check, read from the tracker by run_id; nothing
the agent says decides anything. Never edit the numbers it writes by hand.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

import yaml

from agent.detectors import ladder
from agent.diff import diff
from agent.validator import validate
from eval.check_triage import check
from harness import LAB, ROOT
from harness.formats import UNFINISHED, normalize_path, parse_triage_comment
from harness.runner import is_free
from harness.trace import read_trace
from harness.tracker import Tracker

CONFIGS = ("agent", "planned_off", "planned_self", "planned_external")
NOTES_ISSUES = (4203, 4204, 4206)
REPORT = ROOT / "reports" / "LAB_02.json"


# -- schema: section 10.11's counts ------------------------------------------------------

def schema_counts(schema: dict) -> dict:
    defs = {**(schema.get("definitions") or {}), **(schema.get("$defs") or {})}
    found = {"optional": 0, "unions": 0, "properties": 0, "depth": 0}

    def deref(node):
        while isinstance(node, dict) and "$ref" in node:
            node = defs.get(str(node["$ref"]).split("/")[-1], {})
        return node if isinstance(node, dict) else {}

    def walk(node, level, is_field):
        node = deref(node)
        found["depth"] = max(found["depth"], level)
        branches = node.get("anyOf") or node.get("oneOf")
        kind = node.get("type")
        shapes = len(branches) if branches else (len(set(kind)) if isinstance(kind, list) else 1)
        if is_field and shapes > 1:
            found["unions"] += 1
        props = node.get("properties") or {}
        found["properties"] += len(props)
        found["optional"] += len(set(props) - set(node.get("required") or []))
        for child in props.values():
            walk(child, level + 1, True)
        if isinstance(node.get("items"), dict):
            walk(node["items"], level + 1, True)
        for b in branches or []:
            walk(b, level, False)

    walk(schema, 1, False)
    return found


# -- runs ----------------------------------------------------------------------------------

def configuration(start: dict) -> str | None:
    if start.get("way") == "agent":
        return "agent"
    if start.get("way") == "planned":
        return f"planned_{start.get('critique') or 'off'}"
    return None


def load(eval_issues: set[int]) -> tuple[dict, list[dict]]:
    """Part F's finished runs by configuration, and Part G's finished notes runs."""
    runs, notes = {c: [] for c in CONFIGS}, []
    for path in sorted((ROOT / "runs").glob("*.jsonl")):
        if path.name.startswith("_"):
            continue
        records = read_trace(path)
        start = records[0] if records and records[0].get("type") == "run_start" else None
        if not start or start.get("lab") != LAB or is_free(start.get("backend") or ""):
            continue
        if records[-1].get("type") != "run_end":
            continue
        if any(r.get("type") == "end" and r.get("terminal_reason") in UNFINISHED for r in records):
            continue
        run = {"run_id": start["run_id"], "issue": start["issue"], "sweep": start["sweep"],
               "notes": start.get("notes") or "off", "records": records}
        if start.get("way") == "notes":
            if start["issue"] in NOTES_ISSUES:
                notes.append(run)
        elif configuration(start) in CONFIGS and start["issue"] in eval_issues:
            runs[configuration(start)].append(run)
    return runs, notes


def nearest_rank(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(pct / 100 * len(ordered)) - 1)]


def exact_repeat(records: list[dict]) -> bool:
    seen = set()
    for r in records:
        if r.get("type") == "tool_call":
            key = json.dumps([r.get("name"), r.get("input") or {}], sort_keys=True)
            if key in seen:
                return True
            seen.add(key)
    return False


def right_text(body, answer) -> bool:
    label, file = parse_triage_comment(body or "")
    return label == answer["label"] and file == normalize_path(answer["file"])


def summarize(config: str, runs: list[dict], answers: dict, tracker: Tracker) -> tuple[dict, dict]:
    """Section 10.10's fields for one configuration, and extra figures for the report."""
    planned, second = config != "agent", config in ("planned_self", "planned_external")
    per_issue, per_sweep = defaultdict(int), defaultdict(int)
    tokens, latency, plan_share, plan_only, critique_share, revisions, rounds = [], [], [], [], [], [], []
    changed = fixed = broken = held = 0
    by_calls = defaultdict(list)
    extra = defaultdict(int)
    for r in runs:
        ok = check(tracker, r["run_id"], r["issue"], answers[r["issue"]])
        r["ok"] = ok
        per_issue[r["issue"]] += ok
        per_sweep[r["sweep"]] += ok
        recs = r["records"]
        calls = [x for x in recs if x.get("type") == "model_call"]
        total = sum(c["usage"]["prompt_tokens"] for c in calls)
        share = lambda ps: sum(c["usage"]["prompt_tokens"] for c in calls if c.get("purpose") in ps) / total if total else 0.0  # noqa: E731
        tokens.append(sum(c["usage"]["prompt_tokens"] + c["usage"]["output_tokens"] for c in calls))
        latency.append(recs[-1].get("elapsed_s") or 0.0)
        plan_share.append(share(("plan", "revise")))
        plan_only.append(share(("plan",)))
        critique_share.append(share(("critique",)))
        by_calls[len(calls)].append((share(("plan", "revise")), share(("plan",))))
        revisions.append(sum(1 for x in recs if x.get("type") == "revision"))
        lines = [x for x in recs if x.get("type") == "critique"]
        rounds.append(len(lines))
        if any(x.get("changed") for x in lines):
            changed += 1
            before = right_text(lines[0].get("draft"), answers[r["issue"]])
            fixed += (not before) and ok
            broken += before and not ok
        held += bool(lines) and lines[-1].get("result") == "fail" and not tracker.comments(run_id=r["run_id"])
        ends = [x.get("terminal_reason") for x in recs if x.get("type") == "end"]
        extra[f"end_{ends[-1] if ends else 'none'}"] += 1
        extra["schema_lines"] += sum(1 for x in recs if x.get("type") == "schema")
        extra["validation_lines"] += sum(1 for x in recs if x.get("type") == "validation")
        extra["plan_calls"] += sum(1 for c in calls if c.get("purpose") == "plan")
        extra["revisions_valid"] += sum(1 for x in recs if x.get("type") == "revision" and x.get("valid"))
        extra["checkpoint_fails"] += sum(1 for x in recs if x.get("type") == "checkpoint" and not x.get("passed"))
        extra["model_calls"] += len(calls)
        extra["tool_calls"] += sum(1 for x in recs if x.get("type") == "tool_call")
        extra["cost_usd"] += sum(c.get("cost_usd") or 0 for c in calls)
        extra["first_draft_right"] += bool(lines) and right_text(lines[0].get("draft"), answers[r["issue"]])
        extra["critique_fail_lines"] += sum(1 for x in lines if x.get("result") == "fail")
    n = len(runs)
    mean = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
    sweeps = sorted(per_sweep)
    fields = {
        "runs": n,
        "passes": sum(r["ok"] for r in runs),
        "per_issue": {str(i): per_issue[i] for i in sorted(answers)},
        "sweep_min": min((per_sweep[s] for s in sweeps), default=None),
        "sweep_max": max((per_sweep[s] for s in sweeps), default=None),
        "mean_tokens": mean(tokens),
        "p50_latency_s": nearest_rank(latency, 50),
        "max_latency_s": max(latency, default=None),
        "plan_overhead_share": mean(plan_share) if planned else None,
        "critique_overhead_share": mean(critique_share) if second else None,
        "runs_with_repeat": sum(exact_repeat(r["records"]) for r in runs),
        "off_plan": sum(1 for r in runs for x in r["records"] if x.get("type") == "off_plan") if planned else None,
        "revisions_mean": mean(revisions) if planned else None,
        "revisions_max": max(revisions, default=None) if planned else None,
        "rounds_mean": mean(rounds) if second else None,
        "rounds_max": max(rounds, default=None) if second else None,
        "drafts_changed": changed if second else None,
        "drafts_fixed": fixed if second else None,
        "drafts_broken": broken if second else None,
        "drafts_held": held if second else None,
    }
    extra["mean_cost_usd"] = extra["cost_usd"] / n if n else None
    extra["plan_call_share_mean"] = mean(plan_only) if planned else None
    extra["plan_share_by_calls"] = {k: {"runs": len(v), "plan_and_revise": mean([a for a, _ in v]),
                                        "plan_call": mean([b for _, b in v])} for k, v in sorted(by_calls.items())}
    extra["per_issue_runs"] = {str(i): sum(1 for r in runs if r["issue"] == i) for i in sorted(answers)}
    return fields, dict(extra)


def context_entry(run: dict) -> dict:
    seen, compacted, asked, questions = [], False, False, []
    for x in run["records"]:
        if x.get("type") == "tool_call":
            seen += [p for p in x.get("paths") or [] if p not in seen]
        elif x.get("type") == "compaction" and not asked:
            compacted = True
        elif x.get("type") == "question":
            asked = True
            questions.append({"path": x.get("path"), "truth": "yes" if x.get("path") in seen else "no",
                              "answer": x.get("answer")})
    return {"run_id": run["run_id"], "issue": run["issue"], "notes_shown": run["notes"] == "on",
            "compacted": compacted, "questions": questions,
            "right": sum(q["truth"] == q["answer"] for q in questions)}


def notes_extra(run: dict) -> dict:
    recs = run["records"]
    calls = [x for x in recs if x.get("type") == "model_call"]
    return {"tokens": sum(c["usage"]["prompt_tokens"] + c["usage"]["output_tokens"] for c in calls),
            "prompt_tokens": sum(c["usage"]["prompt_tokens"] for c in calls),
            "model_calls": len(calls),
            "compactions": sum(1 for x in recs if x.get("type") == "compaction"),
            "end": next((x.get("terminal_reason") for x in recs if x.get("type") == "end"), None)}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    answers = {int(k): v for k, v in yaml.safe_load((ROOT / "fixtures/answers.yaml").read_text())["eval"].items()}
    tracker = Tracker(ROOT)
    report = json.loads(REPORT.read_text()) if REPORT.exists() else {"lab": LAB}

    schema = json.loads((ROOT / "agent" / "plan_schema.json").read_text())
    counts = schema_counts(schema)
    report["schema"] = {"args_representation": "args_json" if '"args_json"' in json.dumps(schema) else "oneOf",
                        "optional_fields": counts["optional"], "union_types": counts["unions"],
                        "strict_compiles": report.get("schema", {}).get("strict_compiles")}
    report["fixture_validation"] = [{"plan": path.name, **validate(json.loads(path.read_text()))}
                                    for path in sorted((ROOT / "fixtures" / "plans").glob("*.json"))]
    traces = {}
    for run in ("looping", "s49"):
        folder = ROOT / "fixtures" / "traces" / run
        traces[run] = (json.loads((folder / "plan.json").read_text()), read_trace(folder / "trace.jsonl"))
    report["ladder"] = {run: ladder(*traces[run]) for run in traces}
    d = diff(*traces["s49"])
    report["diff_s49"] = {"steps": {str(k): v for k, v in d["steps"].items()}, "extra": d["extra"]}

    runs, notes = load(set(answers))
    results, extras = {}, {}
    for config in CONFIGS:
        results[config], extras[config] = summarize(config, runs[config], answers, tracker)
    report["results"] = results
    report["context"] = [context_entry(r) for r in sorted(notes, key=lambda r: (r["notes"], r["issue"], r["sweep"]))]

    if not a.dry_run:
        REPORT.write_text(json.dumps(report, indent=2) + "\n")
        (ROOT / "reports" / "lab02_extra.json").write_text(json.dumps(
            {"configs": extras, "notes": {r["run_id"]: {**notes_extra(r), "notes": r["notes"], "issue": r["issue"]}
                                          for r in notes},
             "schema_sizes": counts}, indent=2) + "\n")

    def cell(config, key, fmt="{}"):
        v = results[config].get(key)
        return "" if v is None else fmt.format(v)

    rows = [
        ("Passes, of 18", lambda c: cell(c, "passes")),
        ("Per issue, 4201 to 4206, of 3 each", lambda c: " ".join(str(v) for v in results[c]["per_issue"].values())),
        ("Spread: the lowest and highest sweep, of 6",
         lambda c: f"{results[c]['sweep_min']} to {results[c]['sweep_max']}" if results[c]["runs"] else ""),
        ("Tokens per run", lambda c: cell(c, "mean_tokens", "{:,.0f}")),
        ("Latency per run: median, and slowest",
         lambda c: f"{results[c]['p50_latency_s']:.1f} s, {results[c]['max_latency_s']:.1f} s" if results[c]["runs"] else ""),
        ("Plan overhead: the mean share of prompt tokens", lambda c: cell(c, "plan_overhead_share", "{:.1%}")),
        ("Second-pass overhead: the mean share of prompt tokens", lambda c: cell(c, "critique_overhead_share", "{:.1%}")),
        ("Runs with at least one exact repeat", lambda c: cell(c, "runs_with_repeat")),
        ("`off_plan` lines", lambda c: cell(c, "off_plan")),
        ("Revisions per run: mean, and maximum",
         lambda c: "" if results[c]["revisions_mean"] is None else f"{results[c]['revisions_mean']:.2f}, {results[c]['revisions_max']}"),
        ("Second-pass rounds per run: mean, and maximum",
         lambda c: "" if results[c]["rounds_mean"] is None else f"{results[c]['rounds_mean']:.2f}, {results[c]['rounds_max']}"),
        ("Drafts changed; of those fixed, and broken",
         lambda c: "" if results[c]["drafts_changed"] is None else
         f"{results[c]['drafts_changed']}; {results[c]['drafts_fixed']}, {results[c]['drafts_broken']}"),
        ("Drafts held at the bound", lambda c: cell(c, "drafts_held")),
    ]
    print("| Measure | Agent | Planned, off | Planned, self | Planned, external |\n|---|---|---|---|---|")
    for name, fn in rows:
        print(f"| {name} | " + " | ".join(fn(c) for c in CONFIGS) + " |")
    print("\nruns per configuration:", {c: results[c]["runs"] for c in CONFIGS})
    print("\n| Run | Issue | Progress file shown | Compacted before the questions | Answers right, of 6 |\n|---|---|---|---|---|")
    for e in report["context"]:
        print(f"| `{e['run_id']}` | {e['issue']} | {'yes' if e['notes_shown'] else 'no'} | "
              f"{'yes' if e['compacted'] else 'no'} | {e['right']} |")


if __name__ == "__main__":
    main()
