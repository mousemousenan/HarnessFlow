# Multi-Agent Task Graph Harness Final Report

## Delivered

- `scheduler.py`: validated DAG scheduling, dependency checks, bounded parallel leases, task locking, and failure propagation.
- `agent_pool.py`: bounded worker pool with per-task agent IDs, isolated context metadata, and independent JSONL logs.
- `workspace_manager.py`: Git worktree creation, task branches, commits, changed-path inspection, and cleanup.
- `merge_controller.py`: conflict preflight, non-fast-forward merge, post-merge verification hook, and `HUMAN_BLOCKER` results.
- `multi_runner.py`: opt-in wave-based orchestration that verifies each isolated commit before merging it.
- `schemas/tasks.schema.json` and `templates/03_TASKS.json`: additive task metadata for agent role, execution mode, workspace, and grouped context.
- `docs/MULTI_AGENT_DESIGN.md`: architecture, contracts, invariants, failure model, security, and rollout decisions.

## Compared With `ai_runner.py`

`ai_runner.py` remains the compatibility path: one repository workspace, one ephemeral Codex context, independent verification, repair attempts, human gates, and status commits. `multi_runner.py` adds opt-in parallel scheduling and worktree isolation. It does not trust agent JSON output and does not modify the main branch until a commit has passed scope and verification checks.

## Execution Flow

1. Load and normalize the task graph; legacy `auto` maps to `serial`.
2. Claim ready tasks under the configured parallel limit.
3. Create one Git worktree, context ID, and log for each task.
4. Run the agent and independent verification in that worktree.
5. Commit only verified changes, then preflight and merge into the main branch; `human_gate` commits stop before merge.
6. Persist task status. Failed dependencies become blocked; merge conflicts become `awaiting_human`.

Example:

```bash
python multi_runner.py --repo . --max-parallel 3 --dry-run
python multi_runner.py --repo . --max-parallel 3
```

## Risks and Boundaries

- Worktree creation requires a Git repository with configured identity for agent commits.
- A task graph and its shell verification commands are trusted configuration.
- A merge conflict, product decision, security review, real-environment operation, or irreversible change requires a human gate.
- Interrupted workers leave their worktree and task evidence for explicit recovery; stale conversational context is never reused.

## Follow-up Directions

- Persist scheduler leases and retry counters in a structured runtime journal.
- Add a durable event stream and resumable merge queue.
- Add role-specific prompt policies and resource quotas.
- Add integration coverage for Codex process interruption and crash recovery.
