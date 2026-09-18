from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


HARNESS_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = HARNESS_ROOT / "ai_runner.py"

spec = importlib.util.spec_from_file_location("harnessflow_ai_runner", RUNNER_PATH)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def process(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = process(["git", *args], repo)
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result


class PathScopeTests(unittest.TestCase):
    def test_recursive_glob_respects_directory_boundary(self) -> None:
        self.assertTrue(runner.path_allowed("src/main.py", ["src/**"]))
        self.assertTrue(runner.path_allowed("src", ["src/**"]))
        self.assertFalse(runner.path_allowed("src-old/main.py", ["src/**"]))

    def test_human_gate_handoff_is_automatically_allowed(self) -> None:
        old_handoffs = runner.HANDOFFS_REL
        try:
            runner.HANDOFFS_REL = Path("docs/harnessflow/handoffs")
            task = {
                "id": "P01-T01",
                "execution_mode": "human_gate",
                "allowed_paths": ["src/**"],
            }
            allowed = runner.task_allowed_paths(task)
            self.assertIn("docs/harnessflow/handoffs/P01-T01.md", allowed)
        finally:
            runner.HANDOFFS_REL = old_handoffs


class DependencyTests(unittest.TestCase):
    def test_cycle_reports_each_edge_once(self) -> None:
        tasks = [
            {"id": "A", "depends_on": ["B"]},
            {"id": "B", "depends_on": ["A"]},
        ]
        with self.assertRaisesRegex(runner.RunnerError, r"A -> B -> A$"):
            runner.validate_dependencies(tasks)


class DiffTests(unittest.TestCase):
    def test_current_diff_includes_untracked_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            git(repo, "init")
            (repo / "new.txt").write_text("new content\n", encoding="utf-8")

            diff = runner.current_diff(repo)

            self.assertIn("new.txt", diff)
            self.assertIn("new content", diff)


class RunnerEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name).resolve()
        git(self.repo, "init")
        git(self.repo, "config", "user.name", "HarnessFlow Test")
        git(self.repo, "config", "user.email", "harnessflow@example.invalid")
        shutil.copytree(
            HARNESS_ROOT,
            self.repo / "harnessflow",
            ignore=shutil.ignore_patterns("tests", "__pycache__", "V3-PROMPT.txt"),
        )
        self.command = [
            sys.executable,
            str(self.repo / "harnessflow/ai_runner.py"),
            "--repo",
            str(self.repo),
        ]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_runner(self, *args: str) -> subprocess.CompletedProcess[str]:
        return process([*self.command, *args], self.repo)

    def test_init_and_validate(self) -> None:
        initialized = self.run_runner("--init")
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.assertTrue((self.repo / "docs/harnessflow/00_REQUIREMENTS.md").is_file())
        self.assertTrue((self.repo / "docs/harnessflow/handoffs/_TEMPLATE.md").is_file())

        validated = self.run_runner("--validate")
        self.assertEqual(validated.returncode, 0, validated.stderr)
        self.assertIn("Tasks: 1", validated.stdout)

    def test_executes_verifies_and_commits_one_task(self) -> None:
        initialized = self.run_runner("--init")
        self.assertEqual(initialized.returncode, 0, initialized.stderr)

        fake_codex = self.repo / "harnessflow/fake_codex.py"
        fake_codex.write_text(
            """from __future__ import annotations
import json
from pathlib import Path
import sys

args = sys.argv[1:]
repo = Path(args[args.index("--cd") + 1])
result_path = Path(args[args.index("--output-last-message") + 1])
(repo / "src").mkdir(exist_ok=True)
(repo / "src/result.py").write_text("VALUE = 42\\n", encoding="utf-8")
result_path.write_text(json.dumps({
    "task_id": "P01-T01",
    "result": "completed",
    "changed_files": ["src/result.py"],
    "verification_summary": "implementation created",
    "new_decisions": [],
    "new_invariants": [],
    "blocking_reason": "",
}), encoding="utf-8")
""",
            encoding="utf-8",
            newline="\n",
        )

        config_path = self.repo / "harnessflow/harnessflow.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["codex"]["command"] = [sys.executable, "harnessflow/fake_codex.py"]
        config["runner"]["max_repair_attempts"] = 0
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        tasks_path = self.repo / "docs/harnessflow/03_TASKS.json"
        tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
        tasks[0]["verify"] = ["python -m py_compile src/result.py"]
        tasks_path.write_text(
            json.dumps(tasks, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "chore: test baseline")

        completed = self.run_runner("--task", "P01-T01")
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertIn("PASS P01-T01", completed.stdout)
        self.assertEqual((self.repo / "src/result.py").read_text(encoding="utf-8"), "VALUE = 42\n")

        stored_tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
        self.assertEqual(stored_tasks[0]["status"], "done")
        self.assertEqual(git(self.repo, "status", "--porcelain").stdout, "")
        subjects = git(self.repo, "log", "-3", "--pretty=%s").stdout
        self.assertIn("task(P01-T01): Replace with the first implementation task", subjects)
        self.assertIn("chore(harnessflow): record P01-T01 verification", subjects)

    def test_human_gate_prepares_and_accepts_review(self) -> None:
        initialized = self.run_runner("--init")
        self.assertEqual(initialized.returncode, 0, initialized.stderr)

        fake_codex = self.repo / "harnessflow/fake_codex.py"
        fake_codex.write_text(
            """from __future__ import annotations
import json
from pathlib import Path
import sys

args = sys.argv[1:]
repo = Path(args[args.index("--cd") + 1])
result_path = Path(args[args.index("--output-last-message") + 1])
(repo / "src").mkdir(exist_ok=True)
(repo / "src/reviewed.py").write_text("REVIEWED = True\\n", encoding="utf-8")
handoff = repo / "docs/harnessflow/handoffs/P01-T01.md"
handoff.write_text("# Task Handoff\\n\\nStatus: Pending Review\\n", encoding="utf-8")
result_path.write_text(json.dumps({
    "task_id": "P01-T01",
    "result": "completed",
    "changed_files": ["src/reviewed.py", "docs/harnessflow/handoffs/P01-T01.md"],
    "verification_summary": "ready for review",
    "new_decisions": [],
    "new_invariants": [],
    "blocking_reason": "",
}), encoding="utf-8")
""",
            encoding="utf-8",
            newline="\n",
        )

        config_path = self.repo / "harnessflow/harnessflow.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["codex"]["command"] = [sys.executable, "harnessflow/fake_codex.py"]
        config["runner"]["max_repair_attempts"] = 0
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        tasks_path = self.repo / "docs/harnessflow/03_TASKS.json"
        tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
        tasks[0]["execution_mode"] = "human_gate"
        tasks[0]["verify"] = [
            "python -m py_compile src/reviewed.py",
            "Review the handoff and implementation",
        ]
        tasks_path.write_text(
            json.dumps(tasks, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "chore: human gate baseline")

        prepared = self.run_runner("--task", "P01-T01")
        self.assertEqual(prepared.returncode, 2, prepared.stderr + prepared.stdout)
        self.assertIn("PREPARED P01-T01", prepared.stdout)
        stored_tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
        self.assertEqual(stored_tasks[0]["status"], "awaiting_human")
        self.assertEqual(git(self.repo, "status", "--porcelain").stdout, "")

        handoff = self.repo / "docs/harnessflow/handoffs/P01-T01.md"
        handoff.write_text(
            handoff.read_text(encoding="utf-8").replace(
                "Status: Pending Review", "Status: Accepted"
            ),
            encoding="utf-8",
            newline="\n",
        )
        accepted = self.run_runner("--accept", "P01-T01")
        self.assertEqual(accepted.returncode, 0, accepted.stderr + accepted.stdout)
        self.assertIn("ACCEPTED P01-T01", accepted.stdout)
        stored_tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
        self.assertEqual(stored_tasks[0]["status"], "done")
        self.assertEqual(git(self.repo, "status", "--porcelain").stdout, "")
        subjects = git(self.repo, "log", "-3", "--pretty=%s").stdout
        self.assertIn("task(P01-T01): prepare human review", subjects)
        self.assertIn("chore(harnessflow): accept P01-T01", subjects)


if __name__ == "__main__":
    unittest.main()
