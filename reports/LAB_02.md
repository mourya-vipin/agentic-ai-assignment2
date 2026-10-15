# Assignment 2 report · A plan RepoMind cannot quietly abandon

Model: `gemini-3.5-flash-lite` through Gemini's OpenAI-compatible endpoint, on the
free tier, priced at the paid rates in `pricing.yaml` (input $0.30, output $2.50 per
million tokens; source https://ai.google.dev/gemini-api/docs/pricing, read
2026-10-11). Every number with a field in `reports/LAB_02.json` comes from
`python -m eval.lab02`, which builds that file from `runs/` and the tracker.

## Part A · The plan artifact

**`args` as `args_json`.** Each step's arguments are one string field, the object
encoded as JSON (`{"query": "$fill", "max_results": 20}`), which costs strict mode
nothing; `oneOf` with one shape per tool would have spent four union fields of
the 16, plus a discriminator per branch, to say what the executor checks anyway.
The price is that strict mode cannot see inside the string, so the executor parses
it and checks its keys against the named tool's `input_schema` before the plan is
accepted (`structural_errors` in `ways/planned.py`), and checks every filled-in
input against the same schema before the call (`input_problem`).

**Strict-mode count.** Every field is required and none is nullable: **0 optional
fields** (budget 24) and **0 union types** (budget 16), with 8 object properties
(limit 5,000) and 5 levels of nesting (limit 10). A strict request carrying the
schema was **accepted** (`strict_compiles: true`; every planned run's plan call is
one), but Gemini did not enforce it: in development run `planned-4191-s01-9f8cdc`
the first plan came back with no `tool` in any of its five steps, the schema check
rejected it (a `schema` line), and the re-plan was valid.

## Part B · The validator and the boundary

| Plan | Valid | Failures (step, check) |
|---|---|---|
| `good_export_fix.json` | yes | none |
| `good_triage.json` | yes | none |
| `s18_specimen.json` | no | (2, 2) needs step 4, a later step · (3, 3) no tool and no expected result · (5, 1) `export_report` is not in its tool list; check 4 passes (5 steps) |

**`MAX_REPLANS = 2`**: a rejected plan is re-planned with its reasons (schema
errors and validator failures, never issue text), so a run makes at most three
planner calls before it escalates; one re-plan with feedback fixed the only bad
plan seen in development, and a planner that fails three times running is a
systematic fault for a person, not something a fourth call fixes.

**Plans that broke the schema.** In the 54 measured planned runs, **0 of 54 first
plans** broke the schema or lacked a final `post_comment`, and none was rejected
by the validator, so no measured run re-planned. **2 of 32 revisions** broke the
schema (steps missing required fields; `schema` lines) and were rejected without
running.

**What a fill-in call sees.** The executor's call for a `"$fill"` step sees the
step (its action, its tool, its expected result, the arguments the plan fixes),
the issue, and the results of every step it depends on, directly or through other
steps, including every earlier run of a retried step. It is offered that step's
tool alone; what the plan fixes overrides whatever the model writes, and a call to
any other tool is refused and logged as `off_plan`.

## Part C · Revision at a checkpoint

**The check**: after the first search step, and after any search step a revision
added or changed, the search must have returned at least one source file, a `.ts`
or `.tsx` file under `src/` outside `src/i18n/`; documentation, translations or no
matches fail it. **`MAX_REVISIONS = 2`**: one repair of the first search and one
retry of the repair. In the 54 measured planned runs the checkpoint ran 101 times
and failed 32 times, all on 4203, 4204 and 4206; 30 of the 32 revisions passed the
validator and were logged as new versions.

## Part D · A second pass before posting

The four external checks (`verify` in `agent/critique.py`), in order:

1. **parses**: two lines, `label:` with a known label and `file:` with a path or none;
2. **exists**: a path it names is a file under `fixtures/repo`;
3. **seen**: the path is in the `paths` of one of this run's `tool_call` lines (a search returned it or a read read it);
4. **agrees**: a `question` names `none`, and every other label names a file.

**`MAX_ROUNDS = 2`**: check, rewrite once with the reason, check again; a draft
still failing is held and the run escalates.

| Mode | Can a check find the error? | Does the critic know more than the agent? | Is there a limit and a log? |
|---|---|---|---|
| `off` | no check | no critic | nothing to bound |
| `self` | no: an opinion, with no pass or fail it can be held to | no: the same model, the same issue and results | yes: `MAX_ROUNDS`, a `critique` line per round |
| `external` | yes, for format, existence, provenance and label/file agreement; not for whether a seen file is the cause | yes: the repository's files and this run's own trace | yes: `MAX_ROUNDS`, a `critique` line per round |

## Part E · Detectors and the diff

**How the diff matches a call to a step** (`agent/diff.py`): a `tool_call` line
with a `plan_step` belongs to that step if the step exists and calls that tool (a
step can own several calls, its retries). A line without one, as in the two
recorded runs, belongs to the earliest step, in plan order, that no call has
matched yet, whose tool is the call's tool and whose fixed arguments (every
argument but `"$fill"`) all equal the call's; so each such step owns at most one
call, and slide 51's second `run_tests` can belong only to step 5. Anything else is
`extra`. A matched step is `executed` if its first call comes after those of every
earlier matched step, otherwise `reordered`.

**The looping run.**
- Q1, repetition: **fires**, turns [1, 3] (`search("export")`) and [2, 4] (`read(ReportsPage.tsx)`).
- Q2, unused result: **fires**, turns 1 and 2, as a judgment. The plan has no `depends_on`, and its results list no paths, so I judged from the trace: a result was not used if the run later made the exact same call again, asking for the result instead of using the one it had. Turns 1 and 2 were re-asked at turns 3 and 4. Whether turns 3 and 4 fed the switch to `exportButton` at turn 5 cannot be told from the trace, so I did not flag them.
- Q3, missing execution: **fires**, steps 3, 4, 5 and 6. "Identify the bug" has no tool; edit, test and pull request never ran before the turn limit.
- Q4, plan and task: no. Its first steps are too coarse to check: "search for export" against 247 results cannot succeed or fail, so the agent had no representation of its own progress and repeated itself until the turn limit, the only exit.

**Slide 51's run.**
- Q1: **fires**, steps [2, 4], the same `search_repo("export")` twice.
- Q2: **does not fire**: every step but the last is in a later step's `depends_on`.
- Q3: **fires**, step 6, "confirm the button works", which never ran. Step 5 also ran but returned "1 failing", not its expected "test_export_csv passes", and the run still reported "fixed the export handler".
- Q4: mostly; the plan was right for the task, but the run stopped before its goal and reported success, so the failure is premature stopping, which only an outside test of the result exposes.
- The diff: steps 1 to 5 `executed`, step 6 `skipped`; `extra` is [4], the repeated search.

## Part F · What the plan and the second pass bought

Three sweeps a configuration, 18 runs each, on the six evaluation issues: a pilot,
not a settled difference. Built by `eval/lab02.py` (`python -m eval.lab02`), from
`runs/` and the tracker, with success decided by `eval/check_triage.check`.

| Measure | Agent | Planned, off | Planned, self | Planned, external |
|---|---|---|---|---|
| Passes, of 18 | 13 | 9 | 8 | 9 |
| Per issue, 4201 to 4206, of 3 each | 3 2 3 2 3 0 | 3 0 3 0 3 0 | 3 0 3 0 2 0 | 3 0 3 0 3 0 |
| Spread: the lowest and highest sweep, of 6 | 4 to 5 | 3 to 3 | 2 to 3 | 3 to 3 |
| Tokens per run | 12,615 | 8,942 | 11,626 | 9,809 |
| Latency per run: median, and slowest | 32.6 s, 79.3 s | 30.4 s, 94.7 s | 17.4 s, 85.7 s | 9.7 s, 90.8 s |
| Plan overhead: the mean share of prompt tokens |  | 24.5% | 19.3% | 22.8% |
| Second-pass overhead: the mean share of prompt tokens |  |  | 20.7% | 3.7% |
| Runs with at least one exact repeat | 1 | 0 | 0 | 0 |
| `off_plan` lines |  | 0 | 0 | 0 |
| Revisions per run: mean, and maximum |  | 0.56, 2 | 0.61, 2 | 0.61, 2 |
| Second-pass rounds per run: mean, and maximum |  |  | 1.00, 1 | 1.17, 2 |
| Drafts changed; of those fixed, and broken |  |  | 0; 0, 0 | 3; 2, 0 |
| Drafts held at the bound |  |  | 0 | 1 |

Mean cost per run, at paid rates: agent $0.0041, planned off $0.0045, self $0.0054,
external $0.0048. Plan overhead by run length (planned, off): the planner call
alone is 17.6% of prompt tokens in a 5-call run, 12.3% in a 7-call run and 7.6% in
the one 10-call run; plan plus revise calls are 17.6%, 29.8% and 30.9%, because the
longer runs are the ones that revised. Latency includes the free tier's rate-limit
waits (15 requests a minute), which fell unevenly across sweeps, so the medians do
not rank the configurations.

1. **What did the plan buy RepoMind, concretely?**
   - **A plan in the run log**: 54 version-1 `plan` lines, each before its run's first tool call and naming the model and prompt that wrote it, plus 30 revised versions logged as versions 2 and 3.
   - **A validator before any tool call**: 86 plans and revisions checked; all 54 first plans passed, and 2 of 32 revisions broke the schema and never ran. In development it also caught a plan with no `tool` in any step, which Gemini returned despite `"strict": true`.
   - **A boundary**: 0 `off_plan` lines in 54 runs, and 0 exact repeats, against 1 run with a repeat for the agent.
   - **Bounded work**: 99 to 100 tool calls per 18 planned runs against the agent's 128; 8,942 tokens per run (off) against 12,615. No planned run hit a limit, while 4 agent runs (4204 once, 4206 three times) ran to the 12-step turn limit and posted nothing.
   - **One approval point** for Lecture 5, the version-1 plan, instead of the agent's 7.1 tool calls per run.
   - **A diff** of every run against its plan (`agent/diff.py`).

   **It bought no success. It cost some.** The agent passed 13 of 18; every planned mode passed 8 or 9.

   Compared with Assignment 1, on the same model: my Assignment 1 agent passed 0 of 10 on 4202 and on 4204 (`reports/LAB_01.md`), and I concluded it needed a tool that reads files and follows imports.

   With `read_file`, the agent passes 2 of 3 on each, following `rollup.ts` $\rightarrow$ `startOfWeek` $\rightarrow$ `src/util/dates.ts` on 4204. The plan's fixed shape of two searches and one read could not take that third hop, which is why the agent beat every planned mode (13 against 8–9 of 18).

2. **Where did it not pay?** Slide 52's four cases, applied to the six issues:
   - **One step**: no issue is one step.
   - **Steps known in advance**: 4201, 4203 and 4205 passed 3 of 3 in every planned mode with the same five-step shape (read, search, search, read, post). A workflow would do them, and the plan call is about a sixth of those runs' prompt tokens.
   - **Plan costs more than the work**: in tokens, never: plan and revise calls average 19% to 25% of a run's prompt tokens, and 42.7% at most, in one 6-call run that revised. In outcome, on **4202 and 4204**: the fixed two searches and one read could not follow 4204's trail (rollup email, then `startOfWeek`, then the date utility), which the agent followed in 11 to 12 calls to pass 2 of 3; the plan passed 0 of 9 on each. The decomposition was too short, and none of the four checks can see that.
   - **Nothing reads the plan**: here the validator, the checkpoint, the diff and the checker all read it. It paid for the harness, not for the answer.

3. **What did each second pass buy, and what did it cost?**
   - **Off**: no second pass, 9 of 18.
   - **Self**: 20.7% of prompt tokens and about $0.0010 more per run than off. It accepted all 18 drafts, changed none and caught nothing. It passed 8, losing one 4205 run whose draft named a file for a question, the error external caught. That loss is the draft, not the critique: self changed no draft, so it turned no passing draft into a failing one.
   - **External**: 3.7% of prompt tokens (only its rewrites call the model), and 9 of 18.
     - It caught 4 failing drafts. Twice on 4205, `label: question` with `file: docs/ARCHITECTURE.md` failed the agreement check, and the rewrite made it `file: none`: 2 drafts fixed.
     - Once on 4206, a draft naming `src/exportUtils.ts` failed the seen check, the rewrite made it `file: none`, the agreement check failed that too, and the draft was held: 1 run escalated, posting nothing, rather than a wrong comment.
     - It broke no draft.
   - **Issue 4206**, whose text blames `src/export/csv.ts`, failed in all three modes. Each run read and named the file the reporter blamed, which the run did see, so no check in code could object. Self agreed with its own reading every time.
   - **Slide 41's three gates**: off passes none. Self passes only the third, a limit and a log; no check finds the error, and the critic knows nothing new. External passes all three for the errors it targets: format, existence, provenance and agreement. It is still blind to the semantic error of a seen but wrong file.

4. **Which failure did no detector catch?** Premature stopping. Every wrong planned run that posted ended `completed`. All its steps ran and returned their expected results, so the expected-result check was silent, the repeat check found nothing and the validator had passed the plan. 4204's planned runs posted `src/notifications/rollup.ts` with nothing in the run disagreeing. I knew only because the grounded check compared the posted comment with the answer key, from outside the run. The plan reached its last step, a report of the goal, not the goal (slide 49). One agent run shows the opposite pattern: 4202 sweep 1 stopped after one search and named `src/export/tsv.ts`, a file that does not exist, which external verification would have caught had the agent had one.

## Part G · Note-taking against compaction

`COMPACT_AT = 600` tokens of history (characters / 4). Past it, every history entry
but the most recent becomes one model-written summary; a run that has not
compacted by the questions compacts once first. Every Part G run compacted 1 to 3
times before its questions. The progress file, `runs/<run_id>.progress.json`,
holds an `about` line saying it is a record of what was seen, not a to-do list;
`steps_done`, the ids of the steps that have run; and `paths`, every path a search
returned or a read read. It never holds a search term.

| Run | Issue | Progress file shown | Compacted before the questions | Answers right, of 6 |
|---|---|---|---|---|
| `notes-4203-s01-e1119a` | 4203 | no | yes | 4 |
| `notes-4203-s02-e21be7` | 4203 | no | yes | 3 |
| `notes-4204-s01-4012e7` | 4204 | no | yes | 5 |
| `notes-4204-s02-c08c09` | 4204 | no | yes | 3 |
| `notes-4206-s01-0c623e` | 4206 | no | yes | 4 |
| `notes-4206-s02-74d901` | 4206 | no | yes | 6 |
| `notes-4203-s01-1bde7e` | 4203 | yes | yes | 6 |
| `notes-4203-s02-8812ee` | 4203 | yes | yes | 6 |
| `notes-4204-s01-db01e3` | 4204 | yes | yes | 6 |
| `notes-4204-s02-1a23a8` | 4204 | yes | yes | 6 |
| `notes-4206-s01-3f578e` | 4206 | yes | yes | 6 |
| `notes-4206-s02-e18c36` | 4206 | yes | yes | 6 |

1. **What did the progress file keep that compaction lost, and what did it cost?**
   - **Kept**: the paths the run had seen. With the file shown, 36 of 36 answers were right. Without it, 25 of 36.
   - **Lost**: all 11 wrong answers were seen paths answered "no". Only 7 of the 18 seen-path questions were answered right, while all 18 unseen paths were correctly denied. Compaction did not make the model invent a history; it made it forget one. The summary kept the conclusion, such as "the searches point to the parser", and dropped the early hits it reached it through, such as `src/i18n/en.json` and `src/ingest/errors.ts`.
   - **Cost**: about 1,640 prompt tokens a run (mean 14,059 shown, 12,420 not shown, about 13% more), from showing the file, a few hundred tokens, on every executor call and on the questions call. Plus one file write per tool call, which costs no tokens.

2. **Which context operations did RepoMind need?** My longest Part F run, `agent-4202-s02-b97bd2`, used 33,176 tokens over 11 calls, and its largest single prompt was 5,127 tokens. The longest planned run's largest prompt was 2,447. Both are far inside the model's context window, so the honest answer is that runs this short needed none of the four.
   - **Structured note-taking**: not needed within a run. It would cost about 1,600 tokens a run, as measured above. It would pay once a run must survive a restart or a second session, and it is the operation to reach for first if the runs grow.
   - **Sub-agent isolation**: not needed. It would cost a hand-off summary and its extra calls, and whatever the sub-agent learned and did not summarize.
   - **Just-in-time retrieval**: RepoMind already does this. Searches return paths, and `read_file` fetches one file only when a step needs it, which cost one extra call per run, about 1,000 to 2,000 prompt tokens.
   - **Compaction**: not needed. Its cost, measured in Part G, is a summarizing call per compaction and the loss of 11 of 18 facts the run had seen, which is why it comes last.

## Assistance

Claude Code (Anthropic's CLI, model Claude Opus 5.5) wrote some code for the schema, the planner, reviser and their prompts, the validator, the planned
and notes ways, the critique, the detectors and diff, `eval/lab02.py`. I ran the
development, measured and Part G runs, and drafted this report from the measured
numbers. What was checked: `make test` and `make check-02` (84 of 84 automated),
every scripted model run against the ways, traces read run by run for the
development and the failing evaluation issues, and every table regenerated by the
script, never typed. Two executor bugs found on the first three measured runs
(a refused rerun still spent a revision; a retried search lost its first results)
were fixed and those runs discarded before measuring again, so every
configuration's 18 runs come from one version of the code.
