#!/usr/bin/env python3
"""HarnessFlow scope guard (PreToolUse hook).

Blocks, before the tool runs:
  1. writes outside the active batch's allowed globs;
  2. direct edits to the task graph / state ledger / .git internals;
  3. dangerous git commands (push, history rewrite, hard reset, worktree/branch delete).

Active scope is read from .git/harnessflow/active_scope.json, written by /hf-run at the
start of each batch:

    {"batch": "P02-B1",
     "allowed_globs": ["src/api/**", "tests/api/**"],
     "tasks": {"P02-T04": ["src/api/**"], "P02-T05": ["tests/api/**"]}}

No scope file means no batch is running: writes are allowed (design/plan phases), but the
protected-path and dangerous-command rules still apply.

Exit 0 = allow. Exit 2 = block, stderr goes back to the model.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

SCOPE_REL = ".git/harnessflow/active_scope.json"

WRITE_TOOLS = {"Write", "Edit", "NotebookEdit", "MultiEdit"}

# Editing these through the normal write tools is never right: the orchestrator owns the
# ledger, and .git internals are off limits to every agent.
PROTECTED = (
    "docs/harnessflow/03_TASKS.json",
    "docs/harnessflow/04_STATE.md",
)

# Carve-out: the guard's own scope file lives under .git/harnessflow/.
GIT_CARVE_OUT = ".git/harnessflow/"

DANGEROUS_GIT = (
    (r"\bgit\s+push\b", "git push（本流程不推送远端；由人决定何时推送）"),
    (r"\bgit\s+reset\s+--hard\b", "git reset --hard（会丢弃未提交改动）"),
    (r"\bgit\s+clean\s+-[a-zA-Z]*f", "git clean -f（会删除未跟踪文件）"),
    (r"\bgit\s+(rebase|filter-branch|filter-repo)\b", "改写 git 历史"),
    (r"\bgit\s+commit\b.*--amend", "git commit --amend（改写已有提交）"),
    (r"\bgit\s+branch\s+-[a-zA-Z]*D", "强制删除分支"),
    (r"\bgit\s+worktree\s+remove\b", "删除 worktree"),
    (r"\bgit\s+config\b", "修改 git config"),
)


def repo_root() -> Path:
    """Git toplevel, falling back to CWD when git is unavailable."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip()).resolve()
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.cwd().resolve()


def rel_posix(target: str, root: Path) -> str | None:
    """Repo-relative POSIX path, or None when the target escapes the repo."""
    try:
        resolved = (root / target).resolve() if not os.path.isabs(target) else Path(target).resolve()
        return resolved.relative_to(root).as_posix()
    except (ValueError, OSError):
        return None


def matches(path: str, pattern: str) -> bool:
    """Glob match where `**` spans directories and `*` stays inside one segment.

    `fnmatch` is deliberately not used: its `*` also matches `/`, so `src/api/*.ts`
    would wrongly cover `src/api/v2/handler.ts` and let a task write outside its slice.
    """
    pattern = pattern.strip().lstrip("./")
    if not pattern:
        return False
    # A bare directory prefix covers everything under it.
    if pattern.endswith("/"):
        return path.startswith(pattern)
    if pattern.endswith("/**"):
        return path.startswith(pattern[:-2])
    parts = [
        re.escape(p).replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
        for p in pattern.split("**")
    ]
    return re.fullmatch(".*".join(parts), path) is not None


def load_scope(root: Path) -> dict | None:
    scope_file = root / SCOPE_REL
    if not scope_file.is_file():
        return None
    try:
        data = json.loads(scope_file.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        # An unreadable scope file must not silently disable the guard.
        return {"batch": "<unreadable>", "allowed_globs": []}


def block(message: str) -> None:
    print(f"HarnessFlow scope guard 拒绝了这次操作。\n{message}", file=sys.stderr)
    sys.exit(2)


def check_write(payload: dict, root: Path) -> None:
    target = (
        payload.get("file_path")
        or payload.get("notebook_path")
        or payload.get("path")
        or ""
    )
    if not target:
        return

    path = rel_posix(str(target), root)
    if path is None:
        block(f"目标在仓库之外：{target}\n本流程只允许改动仓库内的文件。")

    if path.startswith(GIT_CARVE_OUT):
        # The orchestrator's own bookkeeping (scope file, logs). Exempt from the batch
        # scope too: declaring the next batch must not require being inside the current one.
        return

    if path.startswith(".git/"):
        block(f"{path} 属于 git 内部目录，任何 agent 都不得直接改写。")

    for protected in PROTECTED:
        if path == protected:
            block(
                f"{path} 是编排层状态文件，只能由 /hf-run 主会话更新。\n"
                "子代理如需变更任务定义，返回 BLOCKED 并说明原因。"
            )

    scope = load_scope(root)
    if scope is None:
        return  # No batch running (design/plan phase).

    globs = [g for g in scope.get("allowed_globs", []) if isinstance(g, str)]
    if any(matches(path, g) for g in globs):
        return

    batch = scope.get("batch", "<unknown>")
    tasks = scope.get("tasks", {})
    owner = next(
        (tid for tid, pats in tasks.items()
         if isinstance(pats, list) and any(matches(path, p) for p in pats)),
        None,
    )
    detail = f"该路径属于任务 {owner}，但它不在当前批次的允许范围内。" if owner else \
        "当前批次的任何任务都不拥有这个路径。"
    allowed = "\n".join(f"  - {g}" for g in globs) or "  （当前批次未声明允许路径）"
    block(
        f"{path} 超出当前批次 {batch} 的允许写入范围。\n{detail}\n"
        f"允许的范围是：\n{allowed}\n"
        "如果任务确实需要改这个文件，返回 BLOCKED 说明原因，由 orchestrator 调整任务定义。"
    )


def check_bash(payload: dict) -> None:
    command = str(payload.get("command", ""))
    if not command:
        return
    for pattern, label in DANGEROUS_GIT:
        if re.search(pattern, command):
            block(
                f"命令包含 {label}。\n命令：{command}\n"
                "提交与远端操作由 orchestrator 或人执行，agent 不做这类不可逆动作。"
            )


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # Malformed event: stay out of the way rather than block everything.

    tool = event.get("tool_name", "")
    payload = event.get("tool_input", {})
    if not isinstance(payload, dict):
        return 0

    root = repo_root()
    if tool in WRITE_TOOLS:
        check_write(payload, root)
    elif tool == "Bash":
        check_bash(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
