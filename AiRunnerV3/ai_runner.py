#!/usr/bin/env python3
"""Run a configuration-driven Codex implementation task graph."""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Sequence, TextIO
import uuid


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_NAME = "harnessflow.json"
DOCS_REL = Path("docs/harnessflow")
REQUIREMENTS_REL = DOCS_REL / "00_REQUIREMENTS.md"
DESIGN_REL = DOCS_REL / "01_DESIGN.md"
PLAN_REL = DOCS_REL / "02_IMPLEMENTATION_PLAN.md"
TASKS_REL = DOCS_REL / "03_TASKS.json"
STATE_REL = DOCS_REL / "04_STATE.md"
HANDOFFS_REL = DOCS_REL / "handoffs"
PROMPT_PATH = SCRIPT_DIR / "prompts/task_prompt.md"
SCHEMA_PATH = SCRIPT_DIR / "schemas/task_result.schema.json"
TASKS_SCHEMA_PATH = SCRIPT_DIR / "schemas/tasks.schema.json"
MAX_REPAIR_ATTEMPTS = 2
AUTO_COMMIT = True
MAX_DIFF_CHARS = 60000
CODEX_COMMAND = ["codex"]
CODEX_EXEC_ARGS: list[str] = []
CODEX_SANDBOX = "workspace-write"
CODEX_MODEL: str | None = None
TASK_FIELDS = (
    "id",
    "title",
    "agent_type",
    "execution_mode",
    "workspace",
    "context",
    "goal",
    "depends_on",
    "context_queries",
    "read_first",
    "allowed_paths",
    "expected_outputs",
    "acceptance",
    "verify",
)
VERIFY_COMMAND_PREFIXES = [
    "pnpm", "npm", "yarn", "npx", "node", "deno", "bun",
    "python", "python3", "pytest", "cargo", "go", "dotnet",
    "mvn", "gradle", "make", "cmake", "bash", "sh", "pwsh",
    "powershell", "git",
]
COMMAND_PREFIX = re.compile(r"^(?:" + "|".join(map(re.escape, VERIFY_COMMAND_PREFIXES)) + r")\b", re.IGNORECASE)


class RunnerError(RuntimeError):
    pass


def print_stream_output(label: str, line: str) -> None:
    text = f"[{label}] {line}"
    try:
        print(text, end="", flush=True)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "ascii"
        safe_text = text.encode(encoding, errors="replace").decode(encoding)
        print(safe_text, end="", flush=True)


def run_process(
    args: list[str] | str,
    *,
    cwd: Path,
    input_text: str | None = None,
    shell: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        shell=shell,
        check=False,
    )


def run_streaming_process(
    args: list[str] | str,
    *,
    cwd: Path,
    label: str,
    input_text: str | None = None,
    shell: bool = False,
    heartbeat_seconds: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        args,
        cwd=cwd,
        stdin=subprocess.PIPE if input_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=shell,
        bufsize=1,
    )
    assert process.stdout is not None
    assert process.stderr is not None

    events: queue.Queue[tuple[str, str | None]] = queue.Queue()

    def consume(name: str, stream: TextIO) -> None:
        try:
            for line in stream:
                events.put((name, line))
        finally:
            events.put((name, None))

    threads = [
        threading.Thread(target=consume, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=consume, args=("stderr", process.stderr), daemon=True),
    ]
    for thread in threads:
        thread.start()

    if process.stdin is not None:
        try:
            process.stdin.write(input_text or "")
        except BrokenPipeError:
            pass
        finally:
            process.stdin.close()

    output = {"stdout": [], "stderr": []}
    closed_streams = 0
    started = time.monotonic()
    last_activity = started
    while closed_streams < 2:
        try:
            poll_seconds = min(1.0, max(heartbeat_seconds, 0.01))
            name, line = events.get(timeout=poll_seconds)
        except queue.Empty:
            now = time.monotonic()
            if now - last_activity >= heartbeat_seconds:
                elapsed = int(now - started)
                print(f"[{label}] still running ({elapsed}s, pid={process.pid})", flush=True)
                last_activity = now
            continue
        if line is None:
            closed_streams += 1
            continue
        output[name].append(line)
        print_stream_output(label, line)
        last_activity = time.monotonic()

    returncode = process.wait()
    for thread in threads:
        thread.join()
    process.stdout.close()
    process.stderr.close()
    return subprocess.CompletedProcess(
        args=args,
        returncode=returncode,
        stdout="".join(output["stdout"]),
        stderr="".join(output["stderr"]),
    )


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = run_process(["git", *args], cwd=repo)
    if result.returncode != 0:
        raise RunnerError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result


def shell_invocation(command: str) -> tuple[list[str] | str, bool]:
    if os.name == "nt":
        return [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ], False
    return command, True


def repository_root(start: Path | None = None) -> Path:
    location = (start or Path.cwd()).resolve()
    result = run_process(["git", "rev-parse", "--show-toplevel"], cwd=location)
    if result.returncode != 0:
        raise RunnerError(f"{location} is not inside a Git repository")
    return Path(result.stdout.strip()).resolve()


def relative_project_path(value: object, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise RunnerError(f"{field} must be a non-empty relative path")
    path = Path(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise RunnerError(f"{field} must stay inside the target repository")
    return path


def config_path(repo: Path, value: str | None) -> Path:
    if value:
        candidate = Path(value)
        return (candidate if candidate.is_absolute() else repo / candidate).resolve()
    candidates = (SCRIPT_DIR / CONFIG_NAME, repo / CONFIG_NAME)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise RunnerError(
        f"No {CONFIG_NAME} found in {SCRIPT_DIR} or {repo}. "
        "Copy HarnessFlow into the repository and run --init."
    )


def string_list(value: object, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise RunnerError(f"{field} must be an array of non-empty strings")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise RunnerError(f"{field} must contain only non-empty strings")
    return [item.strip() for item in value]


def load_config(repo: Path, path: Path, *, require_project_files: bool = True) -> None:
    global DOCS_REL, REQUIREMENTS_REL, DESIGN_REL, PLAN_REL, TASKS_REL
    global STATE_REL, HANDOFFS_REL, PROMPT_PATH, SCHEMA_PATH, TASKS_SCHEMA_PATH
    global MAX_REPAIR_ATTEMPTS, AUTO_COMMIT, MAX_DIFF_CHARS
    global CODEX_COMMAND, CODEX_EXEC_ARGS, CODEX_SANDBOX, CODEX_MODEL
    global VERIFY_COMMAND_PREFIXES, COMMAND_PREFIX
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunnerError(f"Cannot read HarnessFlow config {path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise RunnerError("HarnessFlow config must be an object with version=1")
    paths = raw.get("paths")
    codex = raw.get("codex")
    runner = raw.get("runner")
    if not all(isinstance(section, dict) for section in (paths, codex, runner)):
        raise RunnerError("Config sections paths, codex and runner must be objects")
    assert isinstance(paths, dict) and isinstance(codex, dict) and isinstance(runner, dict)
    REQUIREMENTS_REL = relative_project_path(paths.get("requirements"), "paths.requirements")
    DESIGN_REL = relative_project_path(paths.get("design"), "paths.design")
    PLAN_REL = relative_project_path(paths.get("plan"), "paths.plan")
    TASKS_REL = relative_project_path(paths.get("tasks"), "paths.tasks")
    STATE_REL = relative_project_path(paths.get("state"), "paths.state")
    HANDOFFS_REL = relative_project_path(paths.get("handoffs"), "paths.handoffs")
    DOCS_REL = PLAN_REL.parent
    config_dir = path.parent.resolve()
    resources = raw.get("resources")
    if not isinstance(resources, dict):
        raise RunnerError("Config section resources must be an object")
    resource_values = {
        "task_prompt": resources.get("task_prompt"),
        "task_result_schema": resources.get("task_result_schema"),
        "tasks_schema": resources.get("tasks_schema"),
    }
    resolved: dict[str, Path] = {}
    for name, value in resource_values.items():
        relative = relative_project_path(value, f"resources.{name}")
        candidate = (config_dir / relative).resolve()
        try:
            candidate.relative_to(config_dir)
        except ValueError as exc:
            raise RunnerError(f"resources.{name} escapes the HarnessFlow directory") from exc
        resolved[name] = candidate
    PROMPT_PATH = resolved["task_prompt"]
    SCHEMA_PATH = resolved["task_result_schema"]
    TASKS_SCHEMA_PATH = resolved["tasks_schema"]
    CODEX_COMMAND = string_list(codex.get("command", ["codex"]), "codex.command")
    CODEX_EXEC_ARGS = string_list(codex.get("exec_args", []), "codex.exec_args", allow_empty=True)
    CODEX_SANDBOX = codex.get("sandbox", "workspace-write")
    if CODEX_SANDBOX not in {"read-only", "workspace-write", "danger-full-access"}:
        raise RunnerError("codex.sandbox has an unsupported value")
    CODEX_MODEL = codex.get("model")
    if CODEX_MODEL is not None and (not isinstance(CODEX_MODEL, str) or not CODEX_MODEL.strip()):
        raise RunnerError("codex.model must be null or a non-empty string")
    MAX_REPAIR_ATTEMPTS = runner.get("max_repair_attempts", 2)
    if not isinstance(MAX_REPAIR_ATTEMPTS, int) or isinstance(MAX_REPAIR_ATTEMPTS, bool) or not 0 <= MAX_REPAIR_ATTEMPTS <= 10:
        raise RunnerError("runner.max_repair_attempts must be an integer between 0 and 10")
    AUTO_COMMIT = runner.get("auto_commit", True)
    if not isinstance(AUTO_COMMIT, bool):
        raise RunnerError("runner.auto_commit must be a boolean")
    MAX_DIFF_CHARS = runner.get("max_diff_chars", 60000)
    if not isinstance(MAX_DIFF_CHARS, int) or isinstance(MAX_DIFF_CHARS, bool) or MAX_DIFF_CHARS < 1000:
        raise RunnerError("runner.max_diff_chars must be an integer of at least 1000")
    VERIFY_COMMAND_PREFIXES = string_list(
        runner.get("verify_command_prefixes", VERIFY_COMMAND_PREFIXES),
        "runner.verify_command_prefixes",
    )
    COMMAND_PREFIX = re.compile(
        r"^(?:" + "|".join(map(re.escape, VERIFY_COMMAND_PREFIXES)) + r")\b",
        re.IGNORECASE,
    )
    required = [PROMPT_PATH, SCHEMA_PATH, TASKS_SCHEMA_PATH]
    if require_project_files:
        required.extend([repo / PLAN_REL, repo / TASKS_REL, repo / STATE_REL])
    missing = [str(candidate) for candidate in required if not candidate.is_file()]
    if missing:
        raise RunnerError("Missing HarnessFlow files: " + ", ".join(missing))
    try:
        prompt = PROMPT_PATH.read_text(encoding="utf-8")
        result_schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        tasks_schema = json.loads(TASKS_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunnerError(f"Cannot read HarnessFlow resources: {exc}") from exc
    missing_placeholders = [
        placeholder
        for placeholder in ("{{TASK_JSON}}", "{{REPAIR_CONTEXT}}")
        if placeholder not in prompt
    ]
    if missing_placeholders:
        raise RunnerError(
            "Task prompt is missing placeholders: " + ", ".join(missing_placeholders)
        )
    if not isinstance(result_schema, dict) or not isinstance(tasks_schema, dict):
        raise RunnerError("HarnessFlow schema resources must contain JSON objects")


def load_tasks(repo: Path) -> list[dict]:
    path = repo / TASKS_REL
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunnerError(f"Cannot read {TASKS_REL.as_posix()}: {exc}") from exc
    if not isinstance(value, list):
        raise RunnerError(f"{TASKS_REL.as_posix()} must contain a JSON array")
    ids: list[str] = []
    list_fields = (
        "depends_on", "context_queries", "read_first", "allowed_paths",
        "expected_outputs", "acceptance", "verify",
    )
    for index, task in enumerate(value):
        if not isinstance(task, dict):
            raise RunnerError(f"Task at index {index} must be an object")
        task_id = task.get("id")
        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", task_id):
            raise RunnerError(f"Task at index {index} has an invalid id")
        ids.append(task_id)
        for field in ("title", "goal"):
            if not isinstance(task.get(field), str) or not task[field].strip():
                raise RunnerError(f"{task_id}: {field} must be a non-empty string")
        if "agent_type" in task:
            agent_type = task["agent_type"]
            if agent_type not in {"coding", "testing", "review", "research"}:
                raise RunnerError(f"{task_id}: unsupported agent_type")
        if "workspace" in task and task["workspace"] not in {"isolated", "shared"}:
            raise RunnerError(f"{task_id}: unsupported workspace")
        if "context" in task and not isinstance(task["context"], dict):
            raise RunnerError(f"{task_id}: context must be an object")
        if task.get("execution_mode") not in {"auto", "serial", "parallel", "human_gate"}:
            raise RunnerError(f"{task_id}: unsupported execution_mode")
        if task.get("status") not in {"todo", "running", "blocked", "failed", "awaiting_human", "done", "verified"}:
            raise RunnerError(f"{task_id}: unsupported status")
        for field in list_fields:
            items = task.get(field)
            if not isinstance(items, list) or any(
                not isinstance(item, str) or not item.strip() for item in items
            ):
                raise RunnerError(
                    f"{task_id}: {field} must be an array of non-empty strings"
                )
        if not task["allowed_paths"]:
            raise RunnerError(f"{task_id}: allowed_paths must not be empty")
        if not task["verify"]:
            raise RunnerError(f"{task_id}: verify must not be empty")
        for pattern in task["allowed_paths"]:
            candidate = Path(pattern.replace("\\", "/").replace("*", "x").replace("?", "x"))
            if candidate.is_absolute() or ".." in candidate.parts:
                raise RunnerError(f"{task_id}: allowed_paths escapes the repository: {pattern!r}")
    if len(ids) != len(set(ids)):
        raise RunnerError("Task ids must be unique")
    return value


def save_tasks(repo: Path, tasks: list[dict]) -> None:
    text = json.dumps(tasks, ensure_ascii=False, indent=2) + "\n"
    (repo / TASKS_REL).write_text(text, encoding="utf-8", newline="\n")


def task_map(tasks: list[dict]) -> dict[str, dict]:
    return {task["id"]: task for task in tasks}


def validate_dependencies(tasks: list[dict]) -> None:
    by_id = task_map(tasks)
    for task in tasks:
        dependencies = task.get("depends_on")
        if not isinstance(dependencies, list):
            raise RunnerError(f"{task['id']}: depends_on must be an array")
        missing = [item for item in dependencies if item not in by_id]
        if missing:
            raise RunnerError(f"{task['id']}: unknown dependencies: {', '.join(missing)}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str, trail: list[str]) -> None:
        if task_id in visiting:
            start = trail.index(task_id)
            raise RunnerError("Task dependency cycle: " + " -> ".join(trail[start:]))
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in by_id[task_id]["depends_on"]:
            visit(dependency, [*trail, dependency])
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in by_id:
        visit(task_id, [task_id])


def plan_order(repo: Path, tasks: list[dict]) -> dict[str, int]:
    plan = (repo / PLAN_REL).read_text(encoding="utf-8")
    headings = re.findall(
        r"^###\s+Task\s+([A-Za-z0-9][A-Za-z0-9._-]*)\s*[:：]",
        plan,
        re.MULTILINE,
    )
    if len(headings) != len(set(headings)):
        raise RunnerError(f"{PLAN_REL.as_posix()} contains duplicate Task headings")
    heading_order = {task_id: index for index, task_id in enumerate(headings)}
    missing = [task["id"] for task in tasks if task["id"] not in heading_order]
    if missing:
        raise RunnerError(
            f"Tasks missing from {PLAN_REL.as_posix()} headings: {', '.join(missing)}"
        )
    return heading_order


def ready_tasks(tasks: list[dict], order: dict[str, int]) -> list[dict]:
    by_id = task_map(tasks)
    ready = [
        task
        for task in tasks
        if task.get("status") == "todo"
        and all(by_id[item].get("status") == "done" for item in task["depends_on"])
    ]
    return sorted(ready, key=lambda task: order[task["id"]])


def changed_paths(repo: Path) -> list[str]:
    result = git(repo, "status", "--porcelain=v1", "--untracked-files=all", "-z")
    entries = result.stdout.split("\0")
    paths: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        status = entry[:2]
        path = entry[3:].replace("\\", "/")
        paths.append(path)
        if "R" in status or "C" in status:
            if index < len(entries) and entries[index]:
                paths.append(entries[index].replace("\\", "/"))
                index += 1
    return sorted(set(paths))


def path_allowed(path: str, patterns: list[str]) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    for raw_pattern in patterns:
        pattern = raw_pattern.replace("\\", "/").lstrip("./")
        if pattern.endswith("/**"):
            base = pattern[:-3].rstrip("/")
            if normalized == base or normalized.startswith(base + "/"):
                return True
        elif normalized == pattern or fnmatch.fnmatchcase(normalized, pattern):
            return True
    return False


def paths_within_repository(repo: Path, paths: list[str]) -> bool:
    repository = repo.resolve()
    for path in paths:
        candidate = (repository / path).resolve()
        try:
            candidate.relative_to(repository)
        except ValueError:
            return False
    return True


def task_allowed_paths(task: dict) -> list[str]:
    allowed = list(task.get("allowed_paths", []))
    allowed.extend([TASKS_REL.as_posix(), STATE_REL.as_posix()])
    if task.get("execution_mode") == "human_gate":
        allowed.append(handoff_path(task).as_posix())
    return allowed


def assert_clean(repo: Path) -> None:
    dirty = changed_paths(repo)
    if dirty:
        rendered = "\n  - ".join(dirty)
        raise RunnerError(
            "Git working tree has uncommitted user changes; refusing to run.\n"
            f"  - {rendered}\n"
            "Commit or stash them first. Use --continue only to resume an interrupted runner task."
        )


def continue_task_id(repo: Path, tasks: list[dict]) -> str | None:
    state = repo / STATE_REL
    if state.exists():
        match = re.search(r"^- current_task:\s*`?([^`\s]+)`?\s*$", state.read_text(encoding="utf-8"), re.MULTILINE)
        if match and match.group(1).lower() not in {"none", "null", "-"}:
            return match.group(1)
    blocked = [task["id"] for task in tasks if task.get("status") == "blocked"]
    if len(blocked) == 1:
        return blocked[0]
    return None


def assert_continue_scope(repo: Path, task: dict) -> None:
    allowed = task_allowed_paths(task)
    outside = [path for path in changed_paths(repo) if not path_allowed(path, allowed)]
    if outside:
        rendered = "\n  - ".join(outside)
        raise RunnerError(
            f"Cannot continue {task['id']}; working tree changes escape its allowed paths:\n  - {rendered}"
        )


def automatic_verify_commands(task: dict) -> list[str]:
    commands: list[str] = []
    for item in task.get("verify", []):
        if not isinstance(item, str):
            raise RunnerError(
                f"{task['id']} has an invalid verify step: {item!r}"
            )
        if COMMAND_PREFIX.match(item.strip()):
            commands.append(item.strip())
        elif task.get("execution_mode") != "human_gate":
            raise RunnerError(
                f"{task['id']} is auto but has a non-automatic verify step: {item!r}"
            )
    if not commands:
        raise RunnerError(f"{task['id']} has no automatic verify commands")
    return commands


def render_prompt(repo: Path, task: dict, diff: str = "", verify_error: str = "") -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    payload = {field: task.get(field) for field in TASK_FIELDS}
    repair = ""
    if diff or verify_error:
        repair = (
            "## Fresh repair attempt\n\n"
            "The previous independent attempt did not pass Runner verification. Inspect and repair the current worktree.\n\n"
            "### Current Git diff\n\n```diff\n"
            + bounded_text(diff or "(no diff)", MAX_DIFF_CHARS)
            + "\n```\n\n### Verification error summary\n\n```text\n"
            + bounded_text(verify_error or "(not available)", 8000)
            + "\n```"
        )
    prompt = template.replace(
        "{{TASK_JSON}}", json.dumps(payload, ensure_ascii=False, indent=2)
    ).replace("{{REPAIR_CONTEXT}}", repair)
    if task.get("execution_mode") == "human_gate":
        relative_handoff = handoff_path(task).as_posix()
        prompt += (
            "\n\n## Human gate preparation\n\n"
            f"Implement the task and create the review handoff at `{relative_handoff}`. "
            "Mark the handoff as `Pending Review`, never `Accepted`; only the human reviewer "
            "may record acceptance after inspecting the real implementation and verification results.\n"
        )
    return prompt


def append_log(log_path: Path, heading: str, content: str) -> None:
    timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
    with log_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"\n## {heading} [{timestamp}]\n\n{content.rstrip()}\n")


def bounded_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    half = (limit - 100) // 2
    omitted = len(value) - (half * 2)
    return value[:half] + f"\n... {omitted} characters omitted by HarnessFlow ...\n" + value[-half:]


def runtime_root(repo: Path) -> Path:
    result = git(repo, "rev-parse", "--git-path", "harnessflow")
    candidate = Path(result.stdout.strip())
    return (candidate if candidate.is_absolute() else repo / candidate).resolve()


def codex_command() -> list[str]:
    configured = CODEX_COMMAND[0]
    executable = shutil.which(configured)
    if not executable and Path(configured).is_file():
        executable = str(Path(configured).resolve())
    if not executable:
        raise RunnerError(f"Codex command was not found: {configured}")
    return [executable, *CODEX_COMMAND[1:]]


def invoke_codex(repo: Path, task: dict, prompt: str, log_path: Path) -> tuple[dict | None, str]:
    context_root = runtime_root(repo) / "contexts"
    context_root.mkdir(parents=True, exist_ok=True)
    context_dir = Path(tempfile.mkdtemp(prefix=f"{task['id']}-", dir=context_root))
    result_path = context_dir / "task-result.json"
    command = [
        *codex_command(),
        "exec",
        *CODEX_EXEC_ARGS,
        "--ephemeral",
        "--sandbox",
        CODEX_SANDBOX,
        "--cd",
        str(repo),
        "--output-schema",
        str(SCHEMA_PATH),
        "--output-last-message",
        str(result_path),
        "--color",
        "never",
    ]
    if CODEX_MODEL:
        command.extend(["--model", CODEX_MODEL])
    command.append("-")
    append_log(log_path, "Codex command", " ".join(command[:-1]) + " < prompt")
    try:
        try:
            result = run_streaming_process(
                command,
                cwd=repo,
                input_text=prompt,
                label=f"Codex {task['id']}",
                shell=os.name == "nt" and Path(command[0]).suffix.lower() in {".cmd", ".bat"},
            )
        except OSError as exc:
            return None, f"Could not start codex exec: {exc}"
        append_log(log_path, "Codex stdout", result.stdout or "(empty)")
        append_log(log_path, "Codex stderr", result.stderr or "(empty)")
        if result.returncode != 0:
            return None, f"codex exec exited with {result.returncode}: {tail(result.stderr or result.stdout)}"
        if not result_path.exists():
            return None, "codex exec did not write the structured final result"
        try:
            structured = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return None, f"Codex final result was not valid JSON: {exc}"
        if structured.get("task_id") != task["id"]:
            return structured, f"Codex returned task_id={structured.get('task_id')!r}, expected {task['id']}"
        return structured, ""
    finally:
        shutil.rmtree(context_dir, ignore_errors=True)


def tail(text: str, limit: int = 4000) -> str:
    cleaned = text.strip()
    return cleaned[-limit:] if len(cleaned) > limit else cleaned


def current_diff(repo: Path) -> str:
    unstaged = git(repo, "diff", "--no-ext-diff", "--binary").stdout
    staged = git(repo, "diff", "--cached", "--no-ext-diff", "--binary").stdout
    untracked = git(repo, "ls-files", "--others", "--exclude-standard").stdout.splitlines()
    untracked_diffs: list[str] = []
    for path in untracked:
        result = run_process(
            ["git", "diff", "--no-index", "--no-ext-diff", "--binary", "--", "/dev/null", path],
            cwd=repo,
        )
        if result.returncode not in {0, 1}:
            raise RunnerError(result.stderr.strip() or f"Could not diff untracked file {path}")
        untracked_diffs.append(result.stdout)
    return staged + unstaged + "".join(untracked_diffs)


def verify_task(repo: Path, task: dict, log_path: Path) -> tuple[bool, str]:
    initial_head = git(repo, "rev-parse", "HEAD").stdout.strip()
    allowed = task_allowed_paths(task)
    paths = changed_paths(repo)
    if not paths_within_repository(repo, paths):
        summary = "A changed path resolves outside the repository"
        append_log(log_path, "Verification failure", summary)
        return False, summary
    outside = [path for path in paths if not path_allowed(path, allowed)]
    if outside:
        summary = "Files changed outside allowed_paths: " + ", ".join(outside)
        append_log(log_path, "Verification failure", summary)
        return False, summary

    for command in automatic_verify_commands(task):
        append_log(log_path, "Verify command", command)
        invocation, use_shell = shell_invocation(command)
        result = run_streaming_process(
            invocation,
            cwd=repo,
            label=f"Verify {task['id']}",
            shell=use_shell,
        )
        output = f"exit={result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        append_log(log_path, "Verify result", output)
        if result.returncode != 0:
            return False, f"`{command}` exited with {result.returncode}\n{tail(result.stdout + result.stderr)}"
        if git(repo, "rev-parse", "HEAD").stdout.strip() != initial_head:
            return False, f"Verification command changed Git HEAD: {command}"
        paths = changed_paths(repo)
        outside = [path for path in paths if not path_allowed(path, allowed)]
        if outside:
            return False, "Verification command changed files outside allowed_paths: " + ", ".join(outside)
    return True, "All HarnessFlow verification commands passed"


def read_last_verified_commit(repo: Path) -> str:
    state = repo / STATE_REL
    if state.exists():
        match = re.search(
            r"^- last_verified_commit:\s*`?([^`\s]+)`?\s*$",
            state.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        if match and match.group(1).lower() not in {"none", "null", "pending"}:
            return match.group(1)
    return "none"


def write_state(
    repo: Path,
    tasks: list[dict],
    *,
    current_task: str,
    issues: list[str],
    last_verified_commit: str,
) -> None:
    completed = [task["id"] for task in tasks if task.get("status") == "done"]
    blocked = [task["id"] for task in tasks if task.get("status") == "blocked"]
    completed_text = ", ".join(completed) if completed else "none"
    blocked_text = ", ".join(blocked) if blocked else "none"
    issues_text = "; ".join(item.replace("\n", " ") for item in issues) if issues else "none"
    text = (
        "# Execution State\n\n"
        f"- current_task: `{current_task}`\n"
        f"- completed: {completed_text}\n"
        f"- blocked: {blocked_text}\n"
        f"- current_known_issues: {issues_text}\n"
        f"- last_verified_commit: `{last_verified_commit}`\n"
    )
    (repo / STATE_REL).write_text(text, encoding="utf-8", newline="\n")


def stage_and_commit(repo: Path, paths: list[str], message: str, *, allow_empty: bool = False) -> str:
    unique_paths = sorted(set(paths))
    if unique_paths:
        git(repo, "add", "--", *unique_paths)
    args = ["commit"]
    if allow_empty:
        args.append("--allow-empty")
    args.extend(["-m", message])
    git(repo, *args)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def complete_task(repo: Path, tasks: list[dict], task: dict) -> str:
    task["status"] = "done"
    save_tasks(repo, tasks)
    if not AUTO_COMMIT:
        write_state(
            repo,
            tasks,
            current_task="none",
            issues=["verified changes await a manual Git commit"],
            last_verified_commit="uncommitted",
        )
        return "uncommitted"
    write_state(
        repo,
        tasks,
        current_task="none",
        issues=[],
        last_verified_commit="pending",
    )
    paths = changed_paths(repo)
    allowed = task_allowed_paths(task)
    if not paths_within_repository(repo, paths):
        raise RunnerError("A changed path resolves outside the repository")
    outside = [path for path in paths if not path_allowed(path, allowed)]
    if outside:
        raise RunnerError("Working tree changed after verification: " + ", ".join(outside))
    implementation_commit = stage_and_commit(
        repo,
        paths,
        f"task({task['id']}): {task['title']}",
        allow_empty=True,
    )
    write_state(
        repo,
        tasks,
        current_task="none",
        issues=[],
        last_verified_commit=implementation_commit,
    )
    stage_and_commit(
        repo,
        [STATE_REL.as_posix()],
        f"chore(harnessflow): record {task['id']} verification",
    )
    return implementation_commit


def handoff_path(task: dict) -> Path:
    return HANDOFFS_REL / f"{task['id']}.md"


def handoff_status(path: Path) -> str | None:
    if not path.exists():
        return None
    pattern = r"^\s*(?:#{1,6}\s*)?(?:[-*]\s*)?(?:\*\*)?Status(?:\*\*)?\s*:\s*(?:\*\*)?([^*\r\n]+?)(?:\*\*)?\s*$"
    values = [value.strip().lower() for value in re.findall(
        pattern,
        path.read_text(encoding="utf-8"),
        re.IGNORECASE | re.MULTILINE,
    )]
    if len(values) > 1:
        raise RunnerError(f"{path.as_posix()} must contain exactly one Status field")
    return values[0] if values else None


def human_gate_record_path(repo: Path, task_id: str) -> Path:
    return runtime_root(repo) / "human-gates" / f"{task_id}.json"


def write_human_gate_record(repo: Path, task: dict, prepared_commit: str) -> None:
    path = human_gate_record_path(repo, task["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"task_id": task["id"], "prepared_commit": prepared_commit}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")


def read_human_gate_record(repo: Path, task_id: str) -> dict:
    path = human_gate_record_path(repo, task_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunnerError(f"No valid Runner preparation record for {task_id}") from exc
    if payload.get("task_id") != task_id or not isinstance(payload.get("prepared_commit"), str):
        raise RunnerError(f"Invalid Runner preparation record for {task_id}")
    return payload


def prepare_human_gate(repo: Path, tasks: list[dict], task: dict) -> str:
    if not AUTO_COMMIT:
        raise RunnerError("human_gate tasks require runner.auto_commit=true")
    relative_handoff = handoff_path(task)
    absolute_handoff = repo / relative_handoff
    if handoff_status(absolute_handoff) != "pending review":
        raise RunnerError(
            f"{relative_handoff.as_posix()} must exist with `Status: Pending Review` before human review"
        )

    paths = changed_paths(repo)
    allowed = task_allowed_paths(task)
    if not paths_within_repository(repo, paths):
        raise RunnerError("A changed path resolves outside the repository")
    outside = [path for path in paths if not path_allowed(path, allowed)]
    if outside:
        raise RunnerError("Working tree changed after verification: " + ", ".join(outside))

    previous_status = task.get("status")
    previous_tasks = (repo / TASKS_REL).read_bytes()
    previous_state = (repo / STATE_REL).read_bytes() if (repo / STATE_REL).exists() else None
    task["status"] = "awaiting_human"
    save_tasks(repo, tasks)
    write_state(
        repo,
        tasks,
        current_task=task["id"],
        issues=["awaiting human review"],
        last_verified_commit="pending",
    )
    try:
        prepared_commit = stage_and_commit(
            repo,
            changed_paths(repo),
            f"task({task['id']}): prepare human review",
        )
    except RunnerError:
        task["status"] = previous_status
        (repo / TASKS_REL).write_bytes(previous_tasks)
        if previous_state is not None:
            (repo / STATE_REL).write_bytes(previous_state)
        raise
    write_human_gate_record(repo, task, prepared_commit)
    return prepared_commit


def accept_human_gate(repo: Path, tasks: list[dict], task_id: str) -> str:
    task = task_map(tasks).get(task_id)
    if not task:
        raise RunnerError(f"Unknown task id: {task_id}")
    if task.get("execution_mode") != "human_gate":
        raise RunnerError(f"{task_id} is not a human_gate task")
    if task.get("status") != "awaiting_human":
        raise RunnerError(f"{task_id} has status={task.get('status')!r}; expected 'awaiting_human'")

    relative_handoff = handoff_path(task)
    if handoff_status(repo / relative_handoff) != "accepted":
        raise RunnerError(
            f"Review {relative_handoff.as_posix()} and change its status to `Accepted` first"
        )
    record = read_human_gate_record(repo, task_id)
    current_head = git(repo, "rev-parse", "HEAD").stdout.strip()
    if current_head != record["prepared_commit"]:
        raise RunnerError(
            f"HEAD changed after {task_id} verification; restore the preparation commit before acceptance"
        )
    dirty = changed_paths(repo)
    outside = [path for path in dirty if path != relative_handoff.as_posix()]
    if outside:
        raise RunnerError(
            "Human acceptance may only change the handoff after automatic verification: "
            + ", ".join(outside)
        )

    previous_tasks = (repo / TASKS_REL).read_bytes()
    previous_state = (repo / STATE_REL).read_bytes() if (repo / STATE_REL).exists() else None
    task["status"] = "done"
    save_tasks(repo, tasks)
    write_state(
        repo,
        tasks,
        current_task="none",
        issues=[],
        last_verified_commit=record["prepared_commit"],
    )
    try:
        commit = stage_and_commit(
            repo,
            [relative_handoff.as_posix(), TASKS_REL.as_posix(), STATE_REL.as_posix()],
            f"chore(harnessflow): accept {task_id}",
        )
    except RunnerError:
        task["status"] = "awaiting_human"
        (repo / TASKS_REL).write_bytes(previous_tasks)
        if previous_state is not None:
            (repo / STATE_REL).write_bytes(previous_state)
        raise
    human_gate_record_path(repo, task_id).unlink(missing_ok=True)
    return commit


def block_task(repo: Path, tasks: list[dict], task: dict, reason: str) -> None:
    task["status"] = "blocked"
    save_tasks(repo, tasks)
    write_state(
        repo,
        tasks,
        current_task=task["id"],
        issues=[tail(reason, 1000)],
        last_verified_commit=read_last_verified_commit(repo),
    )


def print_human_gate(task: dict, *, prepared: bool = False) -> None:
    print(f"HUMAN GATE: {task['id']} - {task['title']}")
    print(f"Goal: {task['goal']}")
    commands = [step for step in task.get("verify", []) if COMMAND_PREFIX.match(step.strip())]
    manual = [step for step in task.get("verify", []) if not COMMAND_PREFIX.match(step.strip())]
    if commands:
        heading = "Automatic checks completed by Runner:" if prepared else "Automatic checks Runner will execute:"
        print(f"\n{heading}")
    for step in commands:
        print(f"  - {step}")
    if manual:
        print("\nRequired human actions / checks:")
    for step in manual:
        print(f"  - {step}")
    print("\nAcceptance criteria to confirm:")
    for item in task.get("acceptance", []):
        print(f"  - {item}")
    if prepared:
        print("\nImplementation and review artifacts were saved in a verified preparation commit.")
    else:
        print("\nRunner will implement this task and run its automatic checks before pausing.")
    print("Record the real human result in the task artifacts; do not infer or fabricate it.")


def select_task(
    repo: Path,
    tasks: list[dict],
    order: dict[str, int],
    requested_id: str | None,
    continuing: bool,
) -> dict | None:
    by_id = task_map(tasks)
    if requested_id:
        task = by_id.get(requested_id)
        if not task:
            raise RunnerError(f"Unknown task id: {requested_id}")
        candidates = [task]
    elif continuing:
        task_id = continue_task_id(repo, tasks)
        if task_id:
            task = by_id.get(task_id)
            if not task:
                raise RunnerError(f"STATE current_task does not exist: {task_id}")
            candidates = [task]
        else:
            candidates = ready_tasks(tasks, order)
    else:
        candidates = ready_tasks(tasks, order)

    if not candidates:
        return None
    task = candidates[0]
    if task.get("status") not in ({"todo", "blocked"} if continuing else {"todo"}):
        raise RunnerError(f"{task['id']} has status={task.get('status')!r}, so it cannot be selected")
    by_id = task_map(tasks)
    incomplete = [item for item in task["depends_on"] if by_id[item].get("status") != "done"]
    if incomplete:
        raise RunnerError(f"{task['id']} is not ready; dependencies not done: {', '.join(incomplete)}")
    return task


def print_status(tasks: list[dict], order: dict[str, int]) -> None:
    counts: dict[str, int] = {}
    for task in tasks:
        status = str(task.get("status", "missing"))
        counts[status] = counts.get(status, 0) + 1
    print("Task status: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    ready = ready_tasks(tasks, order)
    awaiting = [task["id"] for task in tasks if task.get("status") == "awaiting_human"]
    print("Ready: " + (", ".join(task["id"] for task in ready) if ready else "none"))
    print("Awaiting human: " + (", ".join(awaiting) if awaiting else "none"))


def execute_task(repo: Path, tasks: list[dict], task: dict, log_path: Path) -> str:
    try:
        automatic_verify_commands(task)
    except RunnerError as exc:
        block_task(repo, tasks, task, str(exc))
        append_log(log_path, "Task blocked", str(exc))
        print(f"BLOCKED {task['id']}: {exc}", file=sys.stderr)
        return "failed"
    initial_head = git(repo, "rev-parse", "HEAD").stdout.strip()
    verification_error = ""
    for attempt in range(1, MAX_REPAIR_ATTEMPTS + 2):
        diff = current_diff(repo) if attempt > 1 else ""
        prompt = render_prompt(repo, task, diff=diff, verify_error=verification_error)
        append_log(log_path, f"Attempt {attempt} task", json.dumps({field: task.get(field) for field in TASK_FIELDS}, ensure_ascii=False, indent=2))
        append_log(log_path, f"Attempt {attempt} prompt", prompt)
        structured, codex_error = invoke_codex(repo, task, prompt, log_path)
        if structured is not None:
            append_log(log_path, "Structured agent result (not authoritative)", json.dumps(structured, ensure_ascii=False, indent=2))
        current_head = git(repo, "rev-parse", "HEAD").stdout.strip()
        if current_head != initial_head:
            block_task(repo, tasks, task, "Codex changed Git history; refusing to verify or commit")
            append_log(log_path, "Task blocked", "Codex changed Git history")
            print(f"BLOCKED {task['id']}: Codex changed Git history", file=sys.stderr)
            return "failed"
        if codex_error:
            verification_error = codex_error
        else:
            try:
                passed, verification_error = verify_task(repo, task, log_path)
            except RunnerError as exc:
                passed, verification_error = False, str(exc)
            if passed:
                if task.get("execution_mode") == "human_gate":
                    try:
                        commit = prepare_human_gate(repo, tasks, task)
                    except RunnerError as exc:
                        block_task(repo, tasks, task, f"Human gate preparation failed: {exc}")
                        append_log(log_path, "Task blocked", str(exc))
                        print(f"BLOCKED {task['id']}: preparation failed: {exc}", file=sys.stderr)
                        return "failed"
                    append_log(log_path, "Human gate prepared", f"verified preparation commit: {commit}")
                    print(f"PREPARED {task['id']} -> {commit}; awaiting human review")
                    return "awaiting_human"
                try:
                    commit = complete_task(repo, tasks, task)
                except RunnerError as exc:
                    block_task(repo, tasks, task, f"Commit failed after verification: {exc}")
                    append_log(log_path, "Task blocked", str(exc))
                    print(f"BLOCKED {task['id']}: commit failed: {exc}", file=sys.stderr)
                    return "failed"
                append_log(log_path, "Task completed", f"verified implementation commit: {commit}")
                print(f"PASS {task['id']} -> {commit}")
                return "completed"
        append_log(log_path, f"Attempt {attempt} failed", verification_error)
        if attempt <= MAX_REPAIR_ATTEMPTS:
            print(f"FAIL {task['id']} attempt {attempt}; starting a fresh repair context")

    block_task(repo, tasks, task, verification_error)
    append_log(log_path, "Task blocked", verification_error)
    print(f"BLOCKED {task['id']}: {verification_error}", file=sys.stderr)
    return "failed"


def init_project(repo: Path, force: bool) -> list[Path]:
    sources = {
        REQUIREMENTS_REL: SCRIPT_DIR / "templates/00_REQUIREMENTS.md",
        DESIGN_REL: SCRIPT_DIR / "templates/01_DESIGN.md",
        PLAN_REL: SCRIPT_DIR / "templates/02_IMPLEMENTATION_PLAN.md",
        TASKS_REL: SCRIPT_DIR / "templates/03_TASKS.json",
        STATE_REL: SCRIPT_DIR / "templates/04_STATE.md",
        HANDOFFS_REL / "_TEMPLATE.md": SCRIPT_DIR / "templates/HANDOFF.md",
    }
    missing = [str(source) for source in sources.values() if not source.is_file()]
    if missing:
        raise RunnerError("HarnessFlow template files are missing: " + ", ".join(missing))
    destinations = [repo / relative for relative in sources]
    conflicts = [path for path in destinations if path.exists()]
    if conflicts and not force:
        rendered = ", ".join(path.relative_to(repo).as_posix() for path in conflicts)
        raise RunnerError(
            "Initialization would overwrite existing files: " + rendered + ". "
            "Use --force only when replacement is intentional."
        )
    for relative, source in sources.items():
        destination = repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    (repo / HANDOFFS_REL).mkdir(parents=True, exist_ok=True)
    return destinations


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repo", metavar="PATH", help="target Git repository; defaults to the current repository")
    result.add_argument("--config", metavar="PATH", help="config path relative to the target repository")
    result.add_argument("--init", action="store_true", help="create requirements, design, plan, task and state templates")
    result.add_argument("--force", action="store_true", help="allow --init to replace generated project files")
    result.add_argument("--validate", action="store_true", help="validate configuration and task graph without changing files")
    result.add_argument("--dry-run", action="store_true", help="show the next action without changing files or starting Codex")
    result.add_argument("--task", metavar="TASK_ID", help="run only this ready task")
    result.add_argument("--continue", dest="continuing", action="store_true", help="resume the task recorded in STATE; acknowledges its in-scope dirty files")
    result.add_argument("--accept", metavar="TASK_ID", help="record human acceptance for a prepared human_gate task")
    result.add_argument("--max-tasks", type=int, metavar="N", help="stop after at most N auto tasks")
    result.add_argument("--status", action="store_true", help="print task counts and ready tasks")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.max_tasks is not None and args.max_tasks < 1:
        raise RunnerError("--max-tasks must be at least 1")
    repo_start = Path(args.repo).resolve() if args.repo else None
    repo = repository_root(repo_start)
    selected_config = config_path(repo, args.config)
    if args.init:
        incompatible = any((args.validate, args.dry_run, args.task, args.continuing, args.accept, args.max_tasks, args.status))
        if incompatible:
            raise RunnerError("--init cannot be combined with execution actions")
        load_config(repo, selected_config, require_project_files=False)
        created = init_project(repo, args.force)
        print("Initialized HarnessFlow project files:")
        for path in created:
            print(f"  - {path.relative_to(repo).as_posix()}")
        print("Next: complete the requirements, design, implementation plan and task graph, then commit them.")
        return 0
    if args.force:
        raise RunnerError("--force is only valid with --init")
    load_config(repo, selected_config)
    other_action = any(
        (args.validate, args.dry_run, args.task, args.continuing, args.max_tasks, args.status)
    )
    if args.accept and other_action:
        raise RunnerError("--accept cannot be combined with other actions")
    tasks = load_tasks(repo)
    validate_dependencies(tasks)
    order = plan_order(repo, tasks)

    if args.validate:
        print(f"HarnessFlow configuration is valid: {selected_config}")
        print(f"Tasks: {len(tasks)}")
        return 0

    if args.accept:
        commit = accept_human_gate(repo, tasks, args.accept)
        print(f"ACCEPTED {args.accept} -> {commit}")
        return 0

    if args.status:
        print_status(tasks, order)
        return 0

    task = select_task(repo, tasks, order, args.task, args.continuing)
    if task is None:
        print("No ready tasks.")
        return 0

    if args.dry_run:
        print(f"Next task: {task['id']} [{task.get('execution_mode')}] {task['title']}")
        if task.get("execution_mode") == "human_gate":
            print_human_gate(task)
        return 0

    if args.continuing:
        assert_continue_scope(repo, task)
    else:
        dirty = changed_paths(repo)
        recorded_task = continue_task_id(repo, tasks)
        if dirty == [STATE_REL.as_posix()] and recorded_task == task["id"]:
            print(f"RESUME {task['id']} from Runner state")
        else:
            assert_clean(repo)

    completed_this_run = 0
    log_dir = runtime_root(repo) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]

    while task is not None:
        previous_verified_commit = read_last_verified_commit(repo)
        write_state(
            repo,
            tasks,
            current_task=task["id"],
            issues=["awaiting human gate"] if task.get("execution_mode") == "human_gate" else [],
            last_verified_commit=previous_verified_commit,
        )
        if task.get("execution_mode") not in {"auto", "serial", "parallel", "human_gate"}:
            raise RunnerError(f"{task['id']} has unsupported execution_mode={task.get('execution_mode')!r}")

        log_path = log_dir / f"{run_id}-{task['id']}.md"
        print(f"RUN {task['id']} (log: {log_path})")
        outcome = execute_task(repo, tasks, task, log_path)
        if outcome == "failed":
            return 1
        if outcome == "awaiting_human":
            print_human_gate(task, prepared=True)
            return 2
        completed_this_run += 1
        if not AUTO_COMMIT:
            print("auto_commit=false; commit the verified work before running another task.")
            return 0

        if args.task or (args.max_tasks is not None and completed_this_run >= args.max_tasks):
            return 0
        task = select_task(repo, tasks, order, None, False)

    print("No more ready tasks.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RunnerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
