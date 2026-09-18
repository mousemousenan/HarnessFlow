#!/usr/bin/env bash
# Resolves a working Python and runs the scope guard.
#
# Why a wrapper: on Windows, `python` is often a Microsoft Store stub that prints an
# install message and exits non-zero. Pointing the hook straight at `python` makes the
# guard silently ineffective while the flow looks fine — the worst failure mode for a
# safety check. This resolves a real interpreter, and fails closed (exit 2) when there
# is none, so a missing interpreter surfaces immediately instead of mid-run.
#
# Override the search with HF_PYTHON=/path/to/python in .claude/settings.json env.

set -uo pipefail

GUARD="${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/hf_scope_guard.py"

works() {
  [ -n "${1:-}" ] || return 1
  "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

for candidate in \
  "${HF_PYTHON:-}" \
  python3 \
  python \
  "$HOME/miniconda3/python.exe" \
  "$HOME/anaconda3/python.exe" \
  "$HOME/AppData/Local/Programs/Python/Python313/python.exe" \
  "$HOME/AppData/Local/Programs/Python/Python312/python.exe" \
  /usr/bin/python3
do
  if works "$candidate"; then
    exec "$candidate" "$GUARD"
  fi
done

# py launcher takes an argument, so it needs its own attempt.
if py -3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
  exec py -3 "$GUARD"
fi

cat >&2 <<'EOF'
HarnessFlow scope guard 无法运行：找不到 Python 3.10+。

守卫是并行任务的写入边界，它不运行就等于没有边界，因此这次操作被拒绝。

修复（任选一种）：
  1. 安装 Python 3.10+ 并确保 `python3 --version` 可用；
  2. 在 .claude/settings.json 里指定解释器：
       "env": { "HF_PYTHON": "C:/Users/<you>/miniconda3/python.exe" }
EOF
exit 2
