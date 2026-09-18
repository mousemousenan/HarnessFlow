from __future__ import annotations

import subprocess
from pathlib import Path
import tempfile
import unittest

from agent_pool import AgentPool
from merge_controller import MergeController
from scheduler import SchedulerError, TaskScheduler
from workspace_manager import Workspace, WorkspaceManager


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, text=True, encoding="utf-8", capture_output=True)
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


class SchedulerTests(unittest.TestCase):
    def test_parallel_ready_tasks_and_failure_propagation(self) -> None:
        scheduler = TaskScheduler([
            {"id": "A", "depends_on": [], "execution_mode": "parallel"},
            {"id": "B", "depends_on": ["A"], "execution_mode": "parallel"},
            {"id": "C", "depends_on": ["A"], "execution_mode": "parallel"},
        ], parallel_limit=2)
        self.assertEqual([task["id"] for task in scheduler.ready_tasks()], ["A"])
        lease = scheduler.acquire("A")
        self.assertIsNotNone(lease)
        self.assertIsNone(scheduler.acquire("A"))
        scheduler.finish("A", "done")
        self.assertEqual({task["id"] for task in scheduler.ready_tasks()}, {"B", "C"})
        scheduler.acquire("B")
        scheduler.finish("B", "failed", reason="verification")
        self.assertEqual({task["id"] for task in scheduler.ready_tasks()}, {"C"})
        self.assertEqual(scheduler.task("B")["status"], "failed")
        self.assertEqual(scheduler.task("C")["status"], "todo")
        scheduler.acquire("C")
        scheduler.finish("C", "done")

    def test_cycle_is_rejected(self) -> None:
        with self.assertRaises(SchedulerError):
            TaskScheduler([{"id": "A", "depends_on": ["B"]}, {"id": "B", "depends_on": ["A"]}])


class WorkspaceTests(unittest.TestCase):
    def test_worktrees_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            git(repo, "init")
            git(repo, "config", "user.name", "Test")
            git(repo, "config", "user.email", "test@example.invalid")
            (repo / "README").write_text("base\n", encoding="utf-8")
            git(repo, "add", ".")
            git(repo, "commit", "-m", "base")
            manager = WorkspaceManager(repo)
            first = manager.create("A")
            second = manager.create("B")
            self.assertNotEqual(first.path, second.path)
            self.assertTrue(first.path.is_dir())
            manager.remove(first)
            manager.remove(second)


class MergeTests(unittest.TestCase):
    def test_conflict_is_human_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            git(repo, "init")
            git(repo, "config", "user.name", "Test")
            git(repo, "config", "user.email", "test@example.invalid")
            target = repo / "value.txt"
            target.write_text("base\n", encoding="utf-8")
            git(repo, "add", ".")
            git(repo, "commit", "-m", "base")
            manager = WorkspaceManager(repo)
            first = manager.create("A")
            second = manager.create("B")
            (first.path / "value.txt").write_text("first\n", encoding="utf-8")
            commit_a = manager.commit(first, "A")
            (second.path / "value.txt").write_text("second\n", encoding="utf-8")
            commit_b = manager.commit(second, "B")
            merged = MergeController(repo).merge([commit_a, commit_b])
            self.assertEqual(merged.status, "awaiting_human")
            self.assertIn("HUMAN_BLOCKER", merged.message)
            manager.remove(first, force=True)
            manager.remove(second, force=True)


class PoolTests(unittest.TestCase):
    def test_each_agent_gets_its_own_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            git(repo, "init")
            git(repo, "config", "user.name", "Test")
            git(repo, "config", "user.email", "test@example.invalid")
            (repo / "README").write_text("base\n", encoding="utf-8")
            git(repo, "add", ".")
            git(repo, "commit", "-m", "base")
            pool = AgentPool(repo, max_workers=2)
            paths: list[Path] = []
            def handler(task, context):
                paths.append(context.workspace)
                return None
            results = pool.run([{"id": "A", "agent_type": "coding"}, {"id": "B", "agent_type": "testing"}], handler)
            self.assertEqual(len(results), 2)
            self.assertEqual(len(set(paths)), 2)
            for path in paths:
                task_id = path.name
                pool.workspace_manager.remove(Workspace(task_id, path, f"harnessflow/{task_id}"))


if __name__ == "__main__":
    unittest.main()
