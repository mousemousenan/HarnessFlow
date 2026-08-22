# HarnessFlow Single Task Implementation

You are implementing exactly one task from an approved implementation plan in the current Git repository. Follow all repository instructions that Codex loads independently. Do not inspect or modify the task graph or execution state, and do not work on any other task.

The complete task payload is:

```json
{{TASK_JSON}}
```

Required workflow:

1. Run the `context_queries` as focused repository searches, then read every `read_first` entry that exists.
2. Implement only this task and only within `allowed_paths`.
3. Produce every `expected_outputs` item and satisfy the observable `acceptance` criteria.
4. Add or update focused tests in proportion to risk. Run useful checks while developing. HarnessFlow will independently run every command-based `verify` step.
5. Preserve unrelated user changes. Do not create Git commits. Do not edit the configured task graph or execution state.
6. Finish with one JSON result that conforms to the supplied result schema. Report decisions and invariants honestly. Use `blocked` or `failed` when appropriate.

For a `human_gate` task, create the configured handoff file with exactly one `Status: Pending Review` line. Never mark it `Accepted`; only the human reviewer may accept it.

Your self-assessment is advisory. HarnessFlow decides completion using Git scope checks and independent verification commands.

{{REPAIR_CONTEXT}}
