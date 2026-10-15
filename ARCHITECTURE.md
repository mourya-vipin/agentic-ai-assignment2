# ARCHITECTURE.md · RepoMind on the seven layers

For each layer: what does this job, and where is it enforced. Cite code as a file
path and line number joined by a colon, inside backticks; a checker opens every
reference (`checks/FORMATS.md`, section 8). A layer held only by a sentence in a
prompt (any file under `prompts/`) is **EMPTY**, and so is a layer nothing does
yet. Status is one of: present, partial (say what is missing), or **EMPTY**. Each
assignment brings this file up to date.

What each layer is for (Lecture 1, slides 40 to 42):

- **Model**: reasoning, choosing tools, generating text.
- **Harness**: runs the loop, builds each prompt, trims old history.
- **Tools**: where the system acts on the world.
- **Memory & State**: what survives a step, a session, a restart.
- **Control & Policy**: what the system may do, and when it must ask.
- **Observability**: a step-by-step record of what it did.
- **Evaluation**: measuring quality, before and after release.

The table below is RepoMind after Assignment 2. The Harness row now cites the
plan's validator, its reject exit and the executor's boundary; Memory & State,
Control & Policy, Observability and Evaluation changed with them.

| Layer | What does this job | Where it is enforced | Status |
|---|---|---|---|
| Model | The configured model, called only through the metered client | `harness/client.py:116` | present |
| Harness | Assignment 1's loop, with three bounds checked in code before every call; and, for the planned way, a plan written as data before the issue is read, checked against the schema (`ways/planned.py:78`) and by the four-check validator (`agent/validator.py:29`, called at `ways/planned.py:150`) before any tool runs, with a reject exit that escalates after `MAX_REPLANS` (`ways/planned.py:125`), the plan logged before the first tool call (`ways/planned.py:127`), and an executor that runs only the active step's tool and refuses anything else (`ways/planned.py:227`) | `agent/loop.py:38`, `agent/validator.py:29`, `ways/planned.py:150`, `ways/planned.py:125`, `ways/planned.py:227` | present |
| Tools | Four tools behind one registry (read_file arrived with Assignment 2's starter); post_comment stamps the run_id; the executor checks every input against its tool's schema before the call | `tools/__init__.py:52`, `harness/tracker.py:60`, `ways/planned.py:250` | present |
| Memory & State | Within a run: the plan's versions and per-step status, and Part G's progress file outside the conversation, written after every tool call; nothing survives a run | `ways/notes.py:66`, `ways/notes.py:87` | partial: one run only |
| Control & Policy | The plan fixes which steps run before untrusted text arrives; revision only at one checkpoint, bounded by `MAX_REVISIONS`; a second pass in code that holds a draft it cannot verify (`MAX_ROUNDS`); still no approval by a person | `ways/planned.py:300`, `ways/planned.py:359`, `agent/critique.py:48` | partial: no human approval gate yet (Lecture 5) |
| Observability | One trace line per model call and per tool call; plus the plan as data, schema/validation/revision/off_plan/critique lines, and a diff of the plan against what ran | `agent/loop.py:50`, `ways/planned.py:228`, `ways/planned.py:316`, `agent/diff.py:1` | partial: traces and offline detectors, no alerts |
| Evaluation | The grounded check reads the tracker, never the agent; three detectors and Lecture 2's ladder over traces; Part F's results script | `eval/check_triage.py:7`, `agent/detectors.py:1`, `eval/lab02.py:1` | partial: offline only |

**Empty layers: 0 of 7**, and four are partial. Assignment 2 moved the plan into the
Harness, where a program can check it before anything runs; Control & Policy is
no longer only a prompt, but nothing yet asks a person before the comment posts.
