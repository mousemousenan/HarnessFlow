# Multi-Agent Task Graph Harness Design

## 1. Current Architecture

The current entry point is `ai_runner.py`. It loads the configured task graph, validates IDs, fields, dependency cycles, and implementation-plan headings, then selects the first ready `todo` task. A single ephemeral Codex context edits the repository. The Runner, rather than the agent result, checks Git history, changed paths, automatic verification commands, and human-gate artifacts before creating commits.

Execution state is persisted in the configured `04_STATE.md`; task status is persisted in `03_TASKS.json`. Runtime logs and repair context are kept under Git's `harnessflow` path. A failed verification starts a fresh repair context up to the configured limit; after that the task becomes `blocked`. Human-gate tasks are prepared in a verified commit and stop at `awaiting_human` until the handoff is accepted.

## 2. Upgrade Goals

The following invariants remain unchanged:

- `03_TASKS.json` is the source of task truth and dependencies are explicit.
- The Runner/Verification Engine is the final authority; an agent cannot self-declare completion.
- File scope, Git history, command verification, acceptance criteria, and audit logs are checked independently.
- A failed task is recoverable from its diff, logs, and error summary using a fresh context.
- Human gates are mandatory for conflicts, product/security decisions, real-environment operations, and irreversible changes.

New capabilities are isolated behind a new `multi_runner.py` entry point:

- `Scheduler` builds and locks a DAG, enforces a parallel limit, and propagates failures.
- `AgentPool` assigns independent contexts, workspaces, and logs to agents.
- `WorkspaceManager` creates Git worktrees and never lets two agents share an isolated workspace.
- `MergeController` checks conflicts before merging and returns `awaiting_human` instead of guessing.
- Multi-agent results are only eligible for merge after independent verification.

## 3. Target Architecture

```text
DESIGN -> IMPLEMENTATION_PLAN -> 03_TASKS.json -> Scheduler
                                                   |
                                  +----------------+----------------+
                                  |                |                |
                              AgentPool       AgentPool       AgentPool
                                  |                |                |
                           isolated worktree isolated worktree isolated worktree
                                  +----------------+----------------+
                                                   |
                                         Verification Engine
                                                   |
                                          MergeController
                                                   |
                                            state/audit update
```

`multi_runner.py` coordinates these modules. It may reuse the existing prompt and verification helpers, but it does not bypass their scope and Git checks.

## 4. Task Model

The upgraded task model adds:

| Field | Purpose |
| --- | --- |
| `agent_type` | Selects a role (`coding`, `testing`, `review`, or `research`) and makes pool assignment auditable. |
| `execution_mode` | `serial`, `parallel`, or `human_gate`; legacy `auto` maps to `serial`. |
| `workspace` | Defaults to `isolated`; prevents accidental shared-directory edits. |
| `context` | Groups `read_first` and `context_queries` for orchestration clients while retaining legacy top-level fields. |
| `expected_outputs` | Records artifacts an agent must produce. |
| `acceptance` | Records observable acceptance checks separate from shell commands. |
| `verify` | Independent commands executed by the verification engine. |

The fields are additive. Existing task files remain valid, and `ai_runner.py` continues to accept `auto` and `human_gate`.

## 5. State and Failure Model

The scheduler uses `todo -> running -> verified -> done` conceptually; persisted task files use the compatible terminal values `done`, `failed`, `blocked`, and `awaiting_human`. A failed or blocked dependency transitively blocks its dependants. A worker failure records the exception, diff, log path, and commit (when one exists), then a new context may retry the task. A merge conflict is never retried automatically and is represented as `awaiting_human` with `HUMAN_BLOCKER` audit text.

## 6. Verification and Merge

For every isolated task the pool/runner checks:

1. changed paths stay inside `allowed_paths`;
2. the agent did not change `HEAD` or create an unapproved history rewrite;
3. all command-based `verify` steps pass;
4. expected outputs and acceptance evidence are recorded;
5. the worktree has a task commit.

Only verified commit IDs are handed to `MergeController`. It performs a conflict preflight, merges with `--no-ff`, runs the supplied verification callback on the target branch, and aborts on any failure. Conflicts return `awaiting_human` and preserve the source worktrees for inspection.

## 7. Security, Recovery, and Audit

Task graphs and verification commands are trusted configuration. Worktree paths are validated as repository-relative, task IDs are sanitized, and agent logs are written outside the project working tree when possible. The pool has a bounded worker count. A process crash leaves a `running` lease that can be recovered by reloading the graph and explicitly resetting or continuing the task; no stale chat context is reused.

## 8. Compatibility and Rollout

Phase 1 adds this design document and schema vocabulary. Phase 2 updates the schema/template. Phases 3-6 add scheduler, pool/workspace, and merge components. Phase 7 adds focused unit/integration tests and the final report. The original `python ai_runner.py` path is unchanged; multi-agent execution is opt-in through `python multi_runner.py`.
