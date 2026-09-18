"""Bounded, observable execution pool for independent task agents."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
import json
import threading
import uuid
from typing import Callable, Iterable

from workspace_manager import Workspace, WorkspaceManager


@dataclass(frozen=True)
class AgentContext:
    agent_id: str
    task_id: str
    agent_type: str
    workspace: Path
    log_path: Path


@dataclass
class AgentResult:
    task_id: str
    status: str
    agent_id: str
    commit: str | None = None
    error: str = ""
    diff: str = ""
    log_path: str = ""
    workspace: str = ""


Handler = Callable[[dict, AgentContext], AgentResult | str | None]


class AgentPool:
    def __init__(self, repo: Path, *, max_workers: int = 1, workspace_manager: WorkspaceManager | None = None, log_dir: Path | None = None):
        if isinstance(max_workers, bool) or max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        self.repo = repo.resolve()
        self.max_workers = max_workers
        self.workspace_manager = workspace_manager or WorkspaceManager(self.repo)
        self.log_dir = (log_dir or self.repo / ".agents" / "logs").resolve()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._active: dict[str, AgentContext] = {}

    @property
    def active(self) -> dict[str, AgentContext]:
        with self._lock:
            return dict(self._active)

    def _context(self, task: dict) -> tuple[AgentContext, Workspace]:
        task_id = task["id"]
        if task.get("workspace", "isolated") != "isolated":
            raise ValueError(f"{task_id} must use an isolated workspace in AgentPool")
        workspace = self.workspace_manager.create(task_id)
        agent_id = f"agent-{task_id}-{uuid.uuid4().hex[:8]}"
        log_path = self.log_dir / f"{task_id}-{agent_id}.jsonl"
        context = AgentContext(agent_id, task_id, task.get("agent_type", "coding"), workspace.path, log_path)
        with self._lock:
            self._active[task_id] = context
        return context, workspace

    def submit(self, executor: ThreadPoolExecutor, task: dict, handler: Handler) -> Future[AgentResult]:
        def run() -> AgentResult:
            context = None
            workspace = None
            try:
                context, workspace = self._context(task)
                context.log_path.write_text(json.dumps({"event": "started", "agent_id": context.agent_id, "task_id": context.task_id}, ensure_ascii=False) + "\n", encoding="utf-8")
                outcome = handler(task, context)
                if isinstance(outcome, AgentResult):
                    result = outcome
                elif isinstance(outcome, str):
                    result = AgentResult(task["id"], "done", context.agent_id, commit=outcome)
                else:
                    result = AgentResult(task["id"], "done", context.agent_id)
                result.log_path = str(context.log_path)
                result.workspace = str(context.workspace)
                return result
            except Exception as exc:  # worker errors become auditable task failures
                agent_id = context.agent_id if context else f"agent-{task['id']}"
                return AgentResult(task["id"], "failed", agent_id, error=str(exc), log_path=str(context.log_path) if context else "", workspace=str(context.workspace) if context else "")
            finally:
                with self._lock:
                    self._active.pop(task["id"], None)

        return executor.submit(run)

    def run(self, tasks: Iterable[dict], handler: Handler) -> list[AgentResult]:
        results: list[AgentResult] = []
        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="harnessflow-agent") as executor:
            futures = [self.submit(executor, task, handler) for task in tasks]
            for future in as_completed(futures):
                results.append(future.result())
        return results

    def close_workspace(self, task_id: str, *, force: bool = False) -> None:
        context = self.active.get(task_id)
        if context:
            self.workspace_manager.remove(Workspace(task_id, context.workspace, ""), force=force)
