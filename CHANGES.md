# CHANGES.md

Three lines per assignment: what it added, what it removed, what it constrained.
Removals are logged like additions.

## Assignment 1
- **Added:** a bounded tool loop; four ways to triage an issue (a direct call, a workflow, an agent, and a hybrid of the two); a grounded success check that reads the tracker; a results script
- **Removed:** nothing
- **Constrained:** every agent run to three bounds checked in code (steps, tokens, wall clock); success to what the tracker holds for the run's ID

## Assignment 2
- **Added:** a plan artifact (JSON, `agent/plan_schema.json`) written before the issue is read; a validator with four checks and a reject exit; a revision checkpoint after the first search; a second pass in three modes (off, self, external); three detectors and a diff of the plan against the trace; a progress file and a compaction (`ways/notes.py`)
- **Removed:** nothing
- **Constrained:** the executor to the active plan (an off-plan call is refused and logged); revision to one checkpoint and `MAX_REVISIONS`; the comment to one post, after the second pass's last round
