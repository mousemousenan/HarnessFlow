"""Thread-safe DAG scheduling primitives for the multi-agent runner."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import threading
from typing import Iterable


class SchedulerError(ValueError):
    """Raised when a task graph or scheduler operation is invalid."""


TERMINAL_SUCCESS = {"done", "verified"}
TERMINAL_FAILURE = {"failed", "blocked"}
VALID_AGENT_TYPES = {"coding", "testing", "review", "research"}
VALID_EXECUTION_MODES = {"auto", "serial", "parallel", "human_gate"}
VALID_WORKSPACES = {"isolated", "shared"}


@dataclass(frozen=True)
class TaskLease:
    task_id: str
    agent_type: str


def _string_list(value: object, field: str, *, required: bool = False) -> list[str]:
    if value is None:
        if required:
            raise SchedulerError(f"{field} must be an array")
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise SchedulerError(f"{field} must contain non-empty strings")
    return [item.strip() for item in value]


def normalize_task(task: dict) -> dict:
    """Validate and fill additive fields without changing the caller's object."""
    if not isinstance(task, dict):
        raise SchedulerError("each task must be an object")
    result = dict(task)
    task_id = result.get("id")
    if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", task_id):
        raise SchedulerError(f"invalid task id: {task_id!r}")
    dependencies = _string_list(result.get("depends_on", []), f"{task_id}.depends_on")
    result["depends_on"] = dependencies
    agent_type = result.get("agent_type", "coding")
    if isinstance(agent_type, list):
        values = _string_list(agent_type, f"{task_id}.agent_type", required=True)
        if len(values) != 1:
            raise SchedulerError(f"{task_id}.agent_type must select one role")
        agent_type = values[0]
    if agent_type not in VALID_AGENT_TYPES:
        raise SchedulerError(f"{task_id}.agent_type must be one of {sorted(VALID_AGENT_TYPES)}")
    result["agent_type"] = agent_type
    mode = result.get("execution_mode", "serial")
    if mode not in VALID_EXECUTION_MODES:
        raise SchedulerError(f"{task_id}.execution_mode must be one of {sorted(VALID_EXECUTION_MODES)}")
    result["execution_mode"] = "serial" if mode == "auto" else mode
    workspace = result.get("workspace", "isolated")
    if workspace not in VALID_WORKSPACES:
        raise SchedulerError(f"{task_id}.workspace must be isolated or shared")
    result["workspace"] = workspace
    context = result.get("context", {})
    if context is None:
        context = {}
    if not isinstance(context, dict):
        raise SchedulerError(f"{task_id}.context must be an object")
    result["context"] = dict(context)
    result["read_first"] = _string_list(result.get("read_first", context.get("read_first", [])), f"{task_id}.read_first")
    result["context_queries"] = _string_list(result.get("context_queries", context.get("context_queries", [])), f"{task_id}.context_queries")
    status = result.get("status", "todo")
    if status not in {"todo", "running", "done", "verified", "failed", "blocked", "awaiting_human"}:
        raise SchedulerError(f"{task_id}.status is unsupported: {status!r}")
    result["status"] = status
    return result


def load_task_file(path: Path) -> list[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchedulerError(f"cannot read task graph {path}: {exc}") from exc
    if not isinstance(payload, list):
        raise SchedulerError("task graph must be a JSON array")
    return [normalize_task(item) for item in payload]


class TaskScheduler:
    """Owns task state and leases; it never executes an agent itself."""

    def __init__(self, tasks: Iterable[dict], parallel_limit: int = 1):
        if isinstance(parallel_limit, bool) or parallel_limit < 1:
            raise SchedulerError("parallel_limit must be at least 1")
        self.tasks = [normalize_task(task) for task in tasks]
        self.parallel_limit = parallel_limit
        self._by_id = {task["id"]: task for task in self.tasks}
        self._leases: dict[str, TaskLease] = {}
        self._lock = threading.RLock()
        self.validate()

    def validate(self) -> None:
        if len(self._by_id) != len(self.tasks):
            raise SchedulerError("task ids must be unique")
        for task in self.tasks:
            missing = [dep for dep in task["depends_on"] if dep not in self._by_id]
            if missing:
                raise SchedulerError(f"{task['id']} has unknown dependencies: {', '.join(missing)}")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str, trail: list[str]) -> None:
            if task_id in visiting:
                start = trail.index(task_id)
                raise SchedulerError("task dependency cycle: " + " -> ".join(trail[start:]))
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency in self._by_id[task_id]["depends_on"]:
                visit(dependency, [*trail, dependency])
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in self._by_id:
            visit(task_id, [task_id])

    def failed_dependencies(self, task_id: str) -> list[str]:
        with self._lock:
            task = self._by_id[task_id]
            return [dep for dep in task["depends_on"] if self._by_id[dep]["status"] in TERMINAL_FAILURE]

    def ready_tasks(self) -> list[dict]:
        with self._lock:
            ready: list[dict] = []
            for task in self.tasks:
                if task["status"] != "todo":
                    continue
                failed = self.failed_dependencies(task["id"])
                if failed:
                    task["status"] = "blocked"
                    task["blocking_reason"] = "dependency failed: " + ", ".join(failed)
                    continue
                if all(self._by_id[dep]["status"] in TERMINAL_SUCCESS for dep in task["depends_on"]):
                    ready.append(task)
            if any(task["execution_mode"] == "serial" for task in ready):
                return [next(task for task in ready if task["execution_mode"] == "serial")]
            return ready

    def acquire(self, task_id: str) -> TaskLease | None:
        with self._lock:
            if len(self._leases) >= self.parallel_limit or task_id in self._leases:
                return None
            task = self._by_id.get(task_id)
            if task is None or task not in self.ready_tasks():
                return None
            task["status"] = "running"
            lease = TaskLease(task_id, task["agent_type"])
            self._leases[task_id] = lease
            return lease

    def claim_ready(self) -> list[TaskLease]:
        leases: list[TaskLease] = []
        for task in self.ready_tasks():
            lease = self.acquire(task["id"])
            if lease is None:
                break
            leases.append(lease)
        return leases

    def finish(self, task_id: str, status: str = "done", *, reason: str = "") -> None:
        if status not in {"done", "verified", "failed", "blocked", "awaiting_human"}:
            raise SchedulerError(f"unsupported terminal status: {status}")
        with self._lock:
            task = self._by_id.get(task_id)
            if task is None:
                raise SchedulerError(f"unknown task: {task_id}")
            if task_id not in self._leases and task["status"] != "running":
                raise SchedulerError(f"task is not running: {task_id}")
            task["status"] = status
            if reason:
                task["blocking_reason"] = reason
            self._leases.pop(task_id, None)

    def task(self, task_id: str) -> dict:
        return self._by_id[task_id]

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [dict(task) for task in self.tasks]

    def has_pending(self) -> bool:
        return any(task["status"] in {"todo", "running"} for task in self.tasks)


Scheduler = TaskScheduler
