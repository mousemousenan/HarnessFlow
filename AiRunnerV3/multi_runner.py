#!/usr/bin/env python3
"""Opt-in multi-agent Task Graph Harness runner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

import ai_runner as single
from agent_pool import AgentPool, AgentResult
from merge_controller import MergeController
from scheduler import SchedulerError, TaskScheduler, load_task_file
from workspace_manager import Workspace, WorkspaceError, WorkspaceManager


def _repository_root(start: Path) -> Path:
    return single.repository_root(start)


def _task_path(repo: Path, value: str | None) -> Path:
    if value:
        candidate = Path(value)
        resolved = (candidate if candidate.is_absolute() else repo / candidate).resolve()
        if not resolved.is_file() and not candidate.is_absolute():
            fallback = (Path(__file__).resolve().parent / candidate).resolve()
            if fallback.is_file():
                return fallback
        return resolved
    config = repo / "harnessflow.json"
    if config.is_file():
        raw = json.loads(config.read_text(encoding="utf-8"))
        configured = raw.get("paths", {}).get("tasks")
        if isinstance(configured, str):
            return (repo / configured).resolve()
    return (repo / "docs/harnessflow/03_TASKS.json").resolve()


def _persist_status(path: Path, original: list[dict], scheduler: TaskScheduler) -> None:
    states = {task["id"]: task for task in scheduler.snapshot()}
    for task in original:
        state = states[task["id"]]
        task["status"] = state["status"]
        if state.get("blocking_reason"):
            task["blocking_reason"] = state["blocking_reason"]
    path.write_text(json.dumps(original, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _agent_handler(repo: Path, pool: AgentPool, task_path: Path):
    def handle(task: dict, context) -> AgentResult:
        workspace = Path(context.workspace)
        log = Path(context.log_path)
        prompt = single.render_prompt(workspace, task)
        structured, error = single.invoke_codex(workspace, task, prompt, log)
        if error:
            return AgentResult(task["id"], "failed", context.agent_id, error=error, log_path=str(log))
        paths = single.changed_paths(workspace)
        allowed = list(task.get("allowed_paths", []))
        if task.get("execution_mode") == "human_gate":
            allowed.append(single.handoff_path(task).as_posix())
        outside = [path for path in paths if not single.path_allowed(path, allowed)]
        if outside:
            return AgentResult(task["id"], "failed", context.agent_id, error="Files changed outside allowed_paths: " + ", ".join(outside), log_path=str(log))
        passed, verify_error = single.verify_task(workspace, task, log)
        if not passed:
            return AgentResult(task["id"], "failed", context.agent_id, error=verify_error, log_path=str(log))
        outside_after_verify = [path for path in single.changed_paths(workspace) if not single.path_allowed(path, allowed)]
        if outside_after_verify:
            return AgentResult(task["id"], "failed", context.agent_id, error="Verification changed files outside allowed_paths: " + ", ".join(outside_after_verify), log_path=str(log))
        try:
            commit = pool.workspace_manager.commit(Workspace(task["id"], workspace, f"harnessflow/{task['id']}"), f"task({task['id']}): {task.get('title', task['id'])}")
        except WorkspaceError as exc:
            return AgentResult(task["id"], "failed", context.agent_id, error=str(exc), log_path=str(log))
        return AgentResult(task["id"], "done", context.agent_id, commit=commit, log_path=str(log))

    return handle


def run(repo: Path, task_path: Path, *, max_parallel: int, dry_run: bool = False) -> int:
    config_path = repo / "harnessflow.json"
    if config_path.is_file():
        single.load_config(repo, config_path, require_project_files=False)
    original = json.loads(task_path.read_text(encoding="utf-8"))
    if not isinstance(original, list):
        raise SchedulerError("task graph must be a JSON array")
    tasks = load_task_file(task_path)
    scheduler = TaskScheduler(tasks, parallel_limit=max_parallel)
    if dry_run:
        ready = scheduler.ready_tasks()
        print("Ready: " + (", ".join(task["id"] for task in ready) if ready else "none"))
        return 0
    if single.changed_paths(repo):
        raise RuntimeError("multi-runner requires a clean main worktree")
    workspace_root = None
    log_root = None
    config = repo / "harnessflow.json"
    if config.is_file():
        settings = json.loads(config.read_text(encoding="utf-8")).get("multi_agent", {})
        if isinstance(settings, dict):
            if isinstance(settings.get("workspace_root"), str):
                workspace_root = repo / settings["workspace_root"]
            if isinstance(settings.get("log_root"), str):
                log_root = repo / settings["log_root"]
    pool = AgentPool(repo, max_workers=max_parallel, workspace_manager=WorkspaceManager(repo, workspace_root), log_dir=log_root)
    merger = MergeController(repo)
    handler = _agent_handler(repo, pool, task_path)
    while scheduler.has_pending():
        leases = scheduler.claim_ready()
        if not leases:
            running = [task["id"] for task in scheduler.snapshot() if task["status"] == "running"]
            if running:
                raise RuntimeError("scheduler has active tasks but no executable leases: " + ", ".join(running))
            blocked = [task["id"] for task in scheduler.snapshot() if task["status"] == "blocked"]
            _persist_status(task_path, original, scheduler)
            print("No more executable tasks; blocked: " + (", ".join(blocked) if blocked else "none"))
            return 1 if blocked else 0
        selected = [scheduler.task(lease.task_id) for lease in leases]
        results = pool.run(selected, handler)
        for result in results:
            if result.status != "done" or not result.commit:
                scheduler.finish(result.task_id, "failed", reason=result.error or "agent failed")
                print(f"FAILED {result.task_id}: {result.error}", file=sys.stderr)
                continue
            task = scheduler.task(result.task_id)
            if task.get("execution_mode") == "human_gate":
                scheduler.finish(result.task_id, "awaiting_human", reason="verified isolated commit awaits human acceptance")
                print(f"PREPARED {result.task_id} -> {result.commit}; awaiting human review")
                continue
            merge = merger.merge([result.commit])
            if merge.status == "merged":
                scheduler.finish(result.task_id, "done")
                if result.workspace:
                    pool.workspace_manager.remove(Workspace(result.task_id, Path(result.workspace), f"harnessflow/{result.task_id}"))
                print(f"PASS {result.task_id} -> {result.commit}")
            elif merge.status == "awaiting_human":
                scheduler.finish(result.task_id, "awaiting_human", reason=merge.message)
                print(f"HUMAN_BLOCKER {result.task_id}: {merge.message}", file=sys.stderr)
            else:
                scheduler.finish(result.task_id, "failed", reason=merge.message)
                print(f"FAILED {result.task_id}: {merge.message}", file=sys.stderr)
        _persist_status(task_path, original, scheduler)
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repo", help="target Git repository")
    result.add_argument("--tasks", help="task graph path")
    result.add_argument("--max-parallel", type=int, default=None)
    result.add_argument("--dry-run", action="store_true")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    repo = _repository_root(Path(args.repo).resolve() if args.repo else None)
    parallel = args.max_parallel
    if parallel is None:
        config = repo / "harnessflow.json"
        parallel = 2
        if config.is_file():
            raw = json.loads(config.read_text(encoding="utf-8"))
            configured = raw.get("multi_agent", {}).get("parallel_limit")
            if isinstance(configured, int) and not isinstance(configured, bool):
                parallel = configured
    if parallel < 1:
        raise ValueError("--max-parallel must be at least 1")
    return run(repo, _task_path(repo, args.tasks), max_parallel=parallel, dry_run=args.dry_run)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, SchedulerError, WorkspaceError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
