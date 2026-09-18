#!/usr/bin/env bash
# HarnessFlow-CC 安装 + 自检
#
#   bash /path/to/HarnessFlow-CC/install.sh /path/to/target-repo
#
# 目标目录省略时用当前目录。不覆盖已有文件，只报告冲突。
set -uo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$(cd "${1:-.}" 2>/dev/null && pwd)" || { echo "目标目录不存在：${1:-.}"; exit 1; }

fail=0
note() { printf '  %s\n' "$1"; }
ok()   { printf '  [ok]   %s\n' "$1"; }
bad()  { printf '  [FAIL] %s\n' "$1"; fail=1; }

echo "源：  $SRC"
echo "目标：$DEST"
echo

echo "1. 前置检查"
[ "$SRC" != "$DEST" ] || { bad "源和目标是同一目录"; exit 1; }
if git -C "$DEST" rev-parse --git-dir >/dev/null 2>&1; then
  ok "是 git 仓库"
else
  # 硬停：scope guard 用 git rev-parse 定位仓库根，没有仓库它会退回 CWD，
  # 范围判定就不可靠了。复制了也不能用，不如现在停下。
  bad "不是 git 仓库。先在目标目录 git init 再重跑本脚本"
  exit 1
fi
if [ -n "$(git -C "$DEST" status --porcelain 2>/dev/null)" ]; then
  note "[warn] 工作区有未提交改动。装完建议先提交基线，再跑 /hf-run"
else
  ok "工作区干净"
fi

echo
echo "2. 复制文件"
# 关键：先建目标目录再用 /. 复制内容，否则目标缺 docs/ 时 cp 会把 harnessflow
# 重命名成 docs，文档路径全错而且不报错。
for pair in ".claude:.claude" "docs/harnessflow:docs/harnessflow"; do
  from="$SRC/${pair%%:*}"
  to="$DEST/${pair##*:}"
  mkdir -p "$to"
  # 逐文件复制，跳过已存在的，避免覆盖目标仓库自己的配置
  while IFS= read -r rel; do
    if [ -e "$to/$rel" ]; then
      note "[skip] 已存在，未覆盖：${pair##*:}/$rel"
    else
      mkdir -p "$to/$(dirname "$rel")"
      cp "$from/$rel" "$to/$rel" && note "[copy] ${pair##*:}/$rel"
    fi
  done < <(cd "$from" && find . -type f -not -path "*__pycache__*" | sed 's|^\./||')
done

echo
echo "3. hook 注册"
registered=0
if grep -q 'hf_guard.sh' "$DEST/.claude/settings.json" 2>/dev/null; then
  registered=1
  ok "settings.json 已注册 hook"
else
  bad "settings.json 未注册本流程的 hook——守卫不会被 Claude Code 调用。
         把这一项追加进 hooks.PreToolUse 数组（数组已存在就追加，不要替换）：
           {\"matcher\": \"Write|Edit|NotebookEdit|MultiEdit|Bash\",
            \"hooks\": [{\"type\": \"command\",
                       \"command\": \"bash \\\"\$CLAUDE_PROJECT_DIR/.claude/hooks/hf_guard.sh\\\"\",
                       \"timeout\": 20}]}
         参考完整文件：$SRC/.claude/settings.json"
fi

echo
echo "4. 自检：守卫脚本本身是否在拦"
if [ "$registered" = 0 ]; then
  note "[warn] 下面测的是脚本本身。hook 未注册，所以实际运行时它不会被调用——"
  note "       这几项全过也不代表守卫生效。先修第 3 步。"
fi
mkdir -p "$DEST/.git/harnessflow"
scope="$DEST/.git/harnessflow/active_scope.json"
had_scope=0; [ -f "$scope" ] && { had_scope=1; cp "$scope" "$scope.bak"; }
echo '{"batch":"SELFTEST","allowed_globs":["src/**"],"tasks":{}}' > "$scope"

probe() { # 事件 JSON、期望退出码、说明
  local got
  echo "$1" | CLAUDE_PROJECT_DIR="$DEST" bash "$DEST/.claude/hooks/hf_guard.sh" >/dev/null 2>&1
  got=$?
  [ "$got" = "$2" ] && ok "$3" || bad "$3（期望 exit $2，实际 $got）"
}

probe '{"tool_name":"Write","tool_input":{"file_path":"src/ok.py"}}'        0 "范围内写入被放行"
probe '{"tool_name":"Write","tool_input":{"file_path":"nope/bad.py"}}'      2 "越界写入被拒绝"
probe '{"tool_name":"Write","tool_input":{"file_path":"docs/harnessflow/04_STATE.md"}}' 2 "状态文件受保护"
probe '{"tool_name":"Bash","tool_input":{"command":"git push"}}'            2 "git push 被拒绝"
probe '{"tool_name":"Bash","tool_input":{"command":"pytest -q"}}'           0 "普通命令被放行"

rm -f "$scope"
[ "$had_scope" = 1 ] && mv "$scope.bak" "$scope"

echo
if [ "$fail" = 0 ]; then
  cat <<EOF
安装完成，自检全过。

下一步：
  git -C "$DEST" add .claude docs/harnessflow
  git -C "$DEST" commit -m "chore: 接入 HarnessFlow-CC"

然后在该目录启动 Claude Code：
  /hf-design <你要做的事>
EOF
else
  cat <<EOF
自检有失败项，先修完再用。

守卫拦不住时最危险的不是报错，而是并行任务互相越界写入却无人发现。
若失败信息提到找不到 Python 3.10+，在 .claude/settings.json 里填绝对路径：
  "env": { "HF_PYTHON": "C:/Users/<you>/miniconda3/python.exe" }
EOF
  exit 1
fi
