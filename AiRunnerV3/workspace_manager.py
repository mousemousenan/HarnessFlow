"""Git worktree lifecycle for isolated agent tasks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess


class WorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Workspace:
    task_id: str
    path: Path
    branch: str


class WorkspaceManager:
    def __init__(self, repo: Path, root: Path | None = None):
        self.repo = repo.resolve()
        self.root = (root or self.repo / ".agents" / "worktree").resolve()
        try:
            self.root.relative_to(self.repo)
        except ValueError as exc:
            raise WorkspaceError("worktree root must be inside the repository") from exc
        self.root.mkdir(parents=True, exist_ok=True)

    def _git(self, *args: str) -> str:
        result = subprocess.run(["git", *args], cwd=self.repo, text=True, encoding="utf-8", errors="replace", capture_output=True)
        if result.returncode:
            raise WorkspaceError(result.stderr.strip() or f"git {' '.join(args)} failed")
        return result.stdout.strip()

    def create(self, task_id: str, *, base_ref: str = "HEAD") -> Workspace:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", task_id):
            raise WorkspaceError(f"invalid task id: {task_id!r}")
        path = (self.root / task_id).resolve()
        branch = f"harnessflow/{task_id}"
        if path.exists():
            raise WorkspaceError(f"workspace already exists: {path}")
        if branch in self._git("for-each-ref", "--format=%(refname:short)", "refs/heads").splitlines():
            raise WorkspaceError(f"worktree branch already exists: {branch}")
        self._git("worktree", "add", "-b", branch, str(path), base_ref)
        return Workspace(task_id, path, branch)

    def remove(self, workspace: Workspace, *, force: bool = False) -> None:
        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(str(workspace.path))
        self._git(*args)

    def commit(self, workspace: Workspace, message: str) -> str:
        result = subprocess.run(["git", "add", "-A"], cwd=workspace.path, text=True, capture_output=True)
        if result.returncode:
            raise WorkspaceError(result.stderr.strip() or "git add failed")
        result = subprocess.run(["git", "commit", "-m", message], cwd=workspace.path, text=True, encoding="utf-8", errors="replace", capture_output=True)
        if result.returncode:
            raise WorkspaceError(result.stderr.strip() or "git commit failed")
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=workspace.path, text=True, encoding="utf-8", capture_output=True)
        return result.stdout.strip()

    def changed_paths(self, workspace: Workspace) -> list[str]:
        result = subprocess.run(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=workspace.path, text=True, encoding="utf-8", errors="replace", capture_output=True)
        if result.returncode:
            raise WorkspaceError(result.stderr.strip() or "git status failed")
        return sorted({line[3:].replace("\\", "/") for line in result.stdout.splitlines() if len(line) >= 4})


GitWorktreeManager = WorkspaceManager
