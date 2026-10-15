"""Way 6, notes: the planned way with a progress file and a compaction.

Assignment 2, Part G. ways/planned.py's PlannedRun with the second pass off, so
that Part F's configurations stay as they were (checks/FORMATS.md, section 10.6):

    python run.py --way notes --notes off --issues 4203,4204,4206 --runs 2
    python run.py --way notes --notes on --issues 4203,4204,4206 --runs 2

What it adds, through PlannedRun's hooks:

  1. A progress file, ctx.progress_path, written after every tool call: an "about"
     line saying what it records, "steps_done" (the ids of the steps that have run,
     in order) and "paths" (every path a search returned or a read read, in order).
     Never a search term: terms come from the issue's text. With --notes on, every
     executor call and the questions' call show the file's text exactly as written;
     with --notes off it is written and never shown.
  2. A history: every executor call sees the run's step results so far, oldest
     first, in place of planned.py's issue-and-dependencies view. Past COMPACT_AT
     tokens (characters / 4), every entry but the last KEEP_RECENT becomes one
     model-written summary, with a compaction line. It runs whatever --notes says.
  3. Six closed questions, once per run, just before the comment is drafted or,
     if the run ends first, just before it ends: "Has this run seen <path>?" about
     the three earliest paths it saw and real repository files it did not, after
     compacting once if it has not yet. Each answer is a question line.
"""

from __future__ import annotations

import json
import random
import re

from agent.critique import seen_paths
from ways.planned import RESULT_CHARS, PlannedRun

COMPACT_AT = 600     # tokens of history: a test setting, low enough that most runs compact before drafting
KEEP_RECENT = 1      # history entries a compaction keeps as they were
QUESTIONS = 6
EARLIEST = 3
EXCLUDED_DIRS = {"config", "node_modules", ".git"}   # what the tools cannot read; never asked about

ABOUT = ("RepoMind's progress file for this run, written by the harness after every tool call. steps_done: "
         "the ids of the plan steps that have run, in order. paths: every file path this run has seen, because "
         "a search returned it or a read read it, in order. A record of what was seen, not a list of things to do.")


def estimate_tokens(text: str) -> int:
    return len(text) // 4


class NotesRun(PlannedRun):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.mode = "off"          # Part G is the planned way with the second pass off
        self.history: list[dict] = []
        self.compactions = 0
        self.asked = False

    # -- the progress file -------------------------------------------------------------
    def progress(self) -> dict:
        paths = []
        for key in self.order:
            paths += [p for p in self.results[key]["paths"] if p not in paths]
        return {"about": ABOUT, "steps_done": [self.results[k]["id"] for k in self.order], "paths": paths}

    def write_progress(self) -> None:
        path = self.ctx.progress_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.progress(), indent=2) + "\n")

    def progress_text(self) -> str | None:
        """The file's text exactly as written, for a call that may see it; None with --notes off."""
        if self.ctx.notes != "on" or not self.ctx.progress_path.exists():
            return None
        return self.ctx.progress_path.read_text()

    # -- the history and its compaction -----------------------------------------------
    def render(self, entries: list[dict]) -> str:
        parts = []
        for e in entries:
            if e["kind"] == "summary":
                parts.append(f"## summary of earlier steps\n{e['text']}")
            else:
                parts.append(f"## step {e['id']}: {e['tool']} {json.dumps(e['input'])}\n{e['text']}")
        return "\n\n".join(parts)

    def compact(self, *, forced: bool = False) -> None:
        tokens = estimate_tokens(self.render(self.history))
        keep = KEEP_RECENT if len(self.history) > KEEP_RECENT else 0
        old, recent = self.history[:len(self.history) - keep], self.history[len(self.history) - keep:]
        summary = ""
        if old:
            self.step_no += 1
            response = self.ctx.client.create(
                system=self.ctx.prompt("compact.md"),
                messages=[{"role": "user", "content": f"The run's record so far, oldest first:\n\n{self.render(old)}"}])
            self.trace.model_call(self.step_no, response)
            summary = response.text.strip() or "(the summary came back empty)"
            self.history = [{"kind": "summary", "text": summary}] + recent
        self.compactions += 1
        self.trace.event("compaction", threshold=COMPACT_AT, tokens=tokens, summarized=len(old), kept=len(recent),
                         forced=forced, summary_tokens=estimate_tokens(summary))

    def context_for(self, step: dict) -> str:
        if estimate_tokens(self.render(self.history)) > COMPACT_AT and len(self.history) > KEEP_RECENT:
            self.compact()
        parts = [f"The run's history so far, oldest first:\n\n{self.render(self.history) or '(nothing yet)'}"]
        text = self.progress_text()
        if text is not None:
            parts.append(f"The run's progress file, as written:\n{text}")
        return "\n\n---\n\n".join(parts)

    def after_tool(self, step: dict, tool_input: dict, result) -> None:
        self.history.append({"kind": "result", "id": step["id"], "tool": step["tool"], "input": tool_input,
                             "text": (result.content or "")[:RESULT_CHARS]})
        self.write_progress()

    # -- the questions -----------------------------------------------------------------
    def repo_files(self) -> list[str]:
        repo = self.ctx.root / "fixtures" / "repo"
        return sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*")
                      if p.is_file() and not set(p.relative_to(repo).parts) & EXCLUDED_DIRS)

    def ask(self) -> None:
        if self.asked:
            return
        self.asked = True
        if not self.compactions:
            self.compact(forced=True)
        seen = seen_paths(self.ctx)
        rng = random.Random(self.ctx.run_id)
        unseen = [p for p in self.repo_files() if p not in seen]
        paths = seen[:EARLIEST] + rng.sample(unseen, QUESTIONS - len(seen[:EARLIEST]))
        rng.shuffle(paths)
        questions = "\n".join(f"{i}. Has this run seen `{p}`: did a search return it, or did you read it?"
                              for i, p in enumerate(paths, 1))
        parts = [f"The run's history so far, oldest first:\n\n{self.render(self.history) or '(nothing yet)'}"]
        text = self.progress_text()
        if text is not None:
            parts.append(f"The run's progress file, as written:\n{text}")
        parts.append(f"Answer these {QUESTIONS} questions about this run, one line each, as `<n>. yes` or "
                     f"`<n>. no`:\n{questions}")
        self.step_no += 1
        response = self.ctx.client.create(system=self.ctx.prompt("questions.md"),
                                          messages=[{"role": "user", "content": "\n\n---\n\n".join(parts)}])
        self.trace.model_call(self.step_no, response)
        answers = parse_answers(response.text, len(paths))
        for path, answer in zip(paths, answers):
            self.trace.event("question", path=path, answer=answer)

    def before_draft(self) -> None:
        self.ask()

    def before_end(self) -> None:
        self.ask()


def parse_answers(text: str, n: int) -> list[str]:
    """n answers, yes or no, from lines such as "3. yes". An unanswered question is "no":
    the model did not say this run saw the path."""
    found = {}
    for number, word in re.findall(r"^\W*(\d+)\W+.*?\b(yes|no)\b", text or "", re.IGNORECASE | re.MULTILINE):
        found.setdefault(int(number), word.lower())
    if found:
        return [found.get(i, "no") for i in range(1, n + 1)]
    words = [w.lower() for w in re.findall(r"\b(yes|no)\b", text or "", re.IGNORECASE)]
    if len(words) == 1:   # one word for all six
        return words * n
    return (words + ["no"] * n)[:n]


def run(ctx) -> None:
    NotesRun(ctx).run()
