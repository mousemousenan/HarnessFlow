"""Conflict-aware merge and post-merge verification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Callable, Iterable


class MergeError(RuntimeError):
    pass


@dataclass(frozen=True)
class MergeResult:
    status: str
    commits: tuple[str, ...] = ()
    message: str = ""


class MergeController:
    def __init__(self, repo: Path):
        self.repo = repo.resolve()

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(["git", *args], cwd=self.repo, text=True, encoding="utf-8", errors="replace", capture_output=True)
        if check and result.returncode:
            raise MergeError(result.stderr.strip() or f"git {' '.join(args)} failed")
        return result

    def check_conflicts(self, commits: Iterable[str]) -> str | None:
        current = self._git("rev-parse", "HEAD").stdout.strip()
        for commit in commits:
            result = self._git("merge-tree", "--write-tree", current, commit, check=False)
            if result.returncode != 0:
                return commit
            # Use the virtual tree as the next comparison base without changing HEAD.
            tree = result.stdout.splitlines()[0].strip() if result.stdout.splitlines() else ""
            if tree:
                current = commit
        return None

    def merge(self, commits: Iterable[str], *, verify: Callable[[Path], bool] | None = None) -> MergeResult:
        commit_list = tuple(commits)
        if not commit_list:
            return MergeResult("nothing_to_merge")
        conflict = self.check_conflicts(commit_list)
        if conflict:
            return MergeResult("awaiting_human", commit_list, f"HUMAN_BLOCKER: merge conflict for {conflict}")
        merged: list[str] = []
        try:
            for commit in commit_list:
                result = self._git("merge", "--no-ff", "--no-edit", commit, check=False)
                if result.returncode:
                    self._git("merge", "--abort", check=False)
                    return MergeResult("awaiting_human", commit_list, f"HUMAN_BLOCKER: merge conflict for {commit}")
                merged.append(commit)
            if verify is not None and not verify(self.repo):
                self._git("reset", "--merge", "HEAD~" + str(len(merged)), check=False)
                return MergeResult("failed", tuple(merged), "post-merge verification failed")
        except MergeError as exc:
            self._git("merge", "--abort", check=False)
            return MergeResult("failed", tuple(merged), str(exc))
        return MergeResult("merged", tuple(merged), "merge and verification passed")

