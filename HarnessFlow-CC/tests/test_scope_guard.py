"""Tests for the HarnessFlow scope guard hook.

Runs the hook as a subprocess against a temporary git repo, exactly how Claude Code
invokes it: event JSON on stdin, exit 0 = allow, exit 2 = block.

    python -m unittest discover -s HarnessFlow-CC/tests -v
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / ".claude" / "hooks" / "hf_scope_guard.py"


def run_hook(event: dict, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=30,
        check=False,
    )


def write_event(path: str) -> dict:
    return {"tool_name": "Write", "tool_input": {"file_path": path}}


def bash_event(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class ScopeGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name).resolve()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True, timeout=30)
        self.addCleanup(self._tmp.cleanup)

    def set_scope(self, scope: dict | None) -> None:
        target = self.repo / ".git" / "harnessflow" / "active_scope.json"
        if scope is None:
            target.unlink(missing_ok=True)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(scope), encoding="utf-8")

    def assertAllowed(self, event: dict) -> None:
        result = run_hook(event, self.repo)
        self.assertEqual(result.returncode, 0, f"expected allow, got block: {result.stderr}")

    def assertBlocked(self, event: dict, expect: str = "") -> str:
        result = run_hook(event, self.repo)
        self.assertEqual(result.returncode, 2, f"expected block, got allow: {result.stdout}")
        if expect:
            self.assertIn(expect, result.stderr)
        return result.stderr

    # --- no active batch -------------------------------------------------

    def test_no_scope_allows_arbitrary_write(self):
        """Design/plan phases run without a batch scope; writes must not be blocked."""
        self.set_scope(None)
        self.assertAllowed(write_event("src/anything/deep/file.py"))

    def test_no_scope_still_protects_ledger(self):
        self.set_scope(None)
        self.assertBlocked(write_event("docs/harnessflow/04_STATE.md"), "编排层状态文件")

    def test_unreadable_scope_does_not_disable_guard(self):
        target = self.repo / ".git" / "harnessflow" / "active_scope.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{ not json", encoding="utf-8")
        self.assertBlocked(write_event("src/api/handler.py"))

    # --- glob semantics --------------------------------------------------

    def test_double_star_matches_any_depth(self):
        self.set_scope({"batch": "B1", "allowed_globs": ["src/api/**"], "tasks": {}})
        self.assertAllowed(write_event("src/api/handler.py"))
        self.assertAllowed(write_event("src/api/v2/nested/deep.py"))

    def test_single_star_stays_within_one_segment(self):
        self.set_scope({"batch": "B1", "allowed_globs": ["src/api/*.ts"], "tasks": {}})
        self.assertAllowed(write_event("src/api/handler.ts"))
        self.assertBlocked(write_event("src/api/v2/handler.ts"))

    def test_sibling_directory_is_blocked(self):
        self.set_scope({"batch": "B1", "allowed_globs": ["src/api/**"], "tasks": {}})
        self.assertBlocked(write_event("src/core/engine.py"), "超出当前批次 B1")

    def test_prefix_lookalike_is_not_a_match(self):
        """src/api-legacy must not be captured by the src/api/** pattern."""
        self.set_scope({"batch": "B1", "allowed_globs": ["src/api/**"], "tasks": {}})
        self.assertBlocked(write_event("src/api-legacy/handler.py"))

    def test_bare_directory_prefix_matches_subtree(self):
        self.set_scope({"batch": "B1", "allowed_globs": ["tests/unit/"], "tasks": {}})
        self.assertAllowed(write_event("tests/unit/test_x.py"))
        self.assertBlocked(write_event("tests/integration/test_y.py"))

    def test_exact_path_glob(self):
        self.set_scope({"batch": "B1", "allowed_globs": ["src/index.ts"], "tasks": {}})
        self.assertAllowed(write_event("src/index.ts"))
        self.assertBlocked(write_event("src/index.js"))

    def test_empty_allowed_globs_blocks_everything(self):
        self.set_scope({"batch": "B1", "allowed_globs": [], "tasks": {}})
        self.assertBlocked(write_event("src/api/handler.py"), "未声明允许路径")

    # --- cross-task attribution -----------------------------------------

    def test_names_owning_task_when_path_belongs_to_another_batch(self):
        """The message must tell the model which task owns the path it tried to touch."""
        self.set_scope({
            "batch": "P02-B1",
            "allowed_globs": ["src/api/**"],
            "tasks": {"P02-T09": ["src/core/**"]},
        })
        stderr = self.assertBlocked(write_event("src/core/engine.py"))
        self.assertIn("P02-T09", stderr)

    # --- protected paths -------------------------------------------------

    def test_task_graph_is_protected(self):
        self.set_scope({"batch": "B1", "allowed_globs": ["docs/**"], "tasks": {}})
        self.assertBlocked(write_event("docs/harnessflow/03_TASKS.json"), "编排层状态文件")

    def test_git_internals_are_blocked(self):
        self.set_scope(None)
        self.assertBlocked(write_event(".git/config"), "git 内部目录")

    def test_scope_file_itself_is_writable(self):
        """/hf-run must be able to declare the next batch's scope."""
        self.set_scope({"batch": "B1", "allowed_globs": [], "tasks": {}})
        self.assertAllowed(write_event(".git/harnessflow/active_scope.json"))

    def test_path_outside_repo_is_blocked(self):
        self.set_scope(None)
        outside = (self.repo.parent / "elsewhere.txt").as_posix()
        self.assertBlocked(write_event(outside), "仓库之外")

    def test_traversal_out_of_repo_is_blocked(self):
        self.set_scope({"batch": "B1", "allowed_globs": ["src/**"], "tasks": {}})
        self.assertBlocked(write_event("../escaped.py"))

    # --- other write tools ----------------------------------------------

    def test_edit_tool_is_guarded(self):
        self.set_scope({"batch": "B1", "allowed_globs": ["src/api/**"], "tasks": {}})
        self.assertBlocked({"tool_name": "Edit", "tool_input": {"file_path": "src/core/x.py"}})

    def test_notebook_edit_is_guarded(self):
        self.set_scope({"batch": "B1", "allowed_globs": ["nb/**"], "tasks": {}})
        self.assertBlocked(
            {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "other/x.ipynb"}}
        )

    def test_read_tool_is_not_guarded(self):
        self.set_scope({"batch": "B1", "allowed_globs": ["src/api/**"], "tasks": {}})
        self.assertAllowed({"tool_name": "Read", "tool_input": {"file_path": "src/core/x.py"}})

    # --- dangerous commands ---------------------------------------------

    def test_git_push_is_blocked(self):
        self.set_scope(None)
        self.assertBlocked(bash_event("git push origin main"), "git push")

    def test_hard_reset_is_blocked(self):
        self.set_scope(None)
        self.assertBlocked(bash_event("git reset --hard HEAD~1"))

    def test_history_rewrite_is_blocked(self):
        self.set_scope(None)
        self.assertBlocked(bash_event("git rebase -i HEAD~3"))

    def test_amend_is_blocked(self):
        self.set_scope(None)
        self.assertBlocked(bash_event("git commit --amend -m x"))

    def test_force_clean_is_blocked(self):
        self.set_scope(None)
        self.assertBlocked(bash_event("git clean -fd"))

    def test_chained_dangerous_command_is_blocked(self):
        self.set_scope(None)
        self.assertBlocked(bash_event("npm test && git push --force"))

    def test_ordinary_commands_pass(self):
        self.set_scope(None)
        for command in ("git status", "git diff --name-only", "pytest -q", "npm run build"):
            with self.subTest(command=command):
                self.assertAllowed(bash_event(command))

    # --- malformed input -------------------------------------------------

    def test_malformed_event_does_not_block(self):
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input="not json",
            capture_output=True,
            text=True,
            cwd=self.repo,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0)

    def test_missing_file_path_does_not_block(self):
        self.set_scope({"batch": "B1", "allowed_globs": ["src/**"], "tasks": {}})
        self.assertAllowed({"tool_name": "Write", "tool_input": {}})


if __name__ == "__main__":
    unittest.main()
