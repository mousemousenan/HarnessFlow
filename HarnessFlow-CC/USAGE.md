# 使用说明

从零到跑完第一个阶段的完整流程。假设目标项目在 `D:/work/myapp`。

## 一、安装（一次性）

用安装脚本，别手工 `cp`：

```bash
cd D:/work/myapp        # 目标项目
bash D:/vibecoding/harnessflow/HarnessFlow-CC/install.sh .
```

它做四件事：检查是不是 git 仓库（不是就停，不留垃圾文件）、逐文件复制（**跳过已存在的，
不覆盖你的配置**）、检查 hook 是否注册、跑 5 项自检确认守卫真的在拦。

全过会打印「安装完成，自检全过」。有 `[FAIL]` 就先修完，退出码是 1。

### 为什么不手工 cp

我最初给的 `cp -r .../docs/harnessflow docs/` 有个静默 bug：目标仓库没有 `docs/` 目录时，
`cp` 会把源目录**重命名**成 `docs`，结果文件落在 `docs/03_TASKS.json` 而不是
`docs/harnessflow/03_TASKS.json`。路径全错，而且不报错——命令要到运行时才说找不到文档。

### 目标仓库已有 .claude/settings.json

安装脚本不会覆盖它，会提示你手工把这一项**追加**进 `hooks.PreToolUse` 数组
（数组已存在就追加，别替换整个文件）：

```json
{"matcher": "Write|Edit|NotebookEdit|MultiEdit|Bash",
 "hooks": [{"type": "command",
            "command": "bash \"$CLAUDE_PROJECT_DIR/.claude/hooks/hf_guard.sh\"",
            "timeout": 20}]}
```

改完重跑一次 install.sh 确认第 3 项变成 `[ok]`。

注意：hook 没注册时，自检的 5 项**仍然会全过**——因为自检直接调脚本，绕过了 Claude Code
的 hook 机制。脚本会明确警告这一点。只有第 3 项 `[ok]` 才说明守卫真的会被调用。

### 关于 Python

你这台机器上 `python` / `python3` 是 Microsoft Store 占位程序（退出码 49），
但包装脚本会识别并跳过它，自动命中 `~/miniconda3/python.exe`。我实测过，**你不用配
`HF_PYTHON`**。

只有 install.sh 报「找不到 Python 3.10+」时才需要在 `.claude/settings.json` 填绝对路径：

```json
"env": { "HF_PYTHON": "C:/Users/saisn/miniconda3/python.exe" }
```

### 装完提交基线

```bash
git add .claude docs/harnessflow
git commit -m "chore: 接入 HarnessFlow-CC"
```

运行时状态在 `.git/harnessflow/`（`active_scope.json`、`budget.json`），本来就不被 git 跟踪，
不用加 `.gitignore`。

## 二、阶段 1：出设计书

在项目根目录启动 Claude Code，然后：

```
/hf-design 给订单模块加导出 CSV 的能力
```

接下来会发生什么：

1. 它读 `docs/harnessflow/` 现有文档、`CLAUDE.md`、git 状态，派只读子代理并行调研相关代码。
2. **弹出选择题问你**。只会问不同答案会导致不同设计的问题——比如导出走同步还是异步、
   大数据量怎么处理、要不要支持字段筛选。每题有推荐项标了「(推荐)」。选就行，
   也可以选「Other」自己写。
3. 写出 `00_REQUIREMENTS.md` 和 `01_DESIGN.md`，都是 `Status: Draft`。
4. 报一份自检结果给你。

**你要做的**：读这两份文档。设计不对就直接说哪里不对，让它改。满意后**手工**把两份文档顶部的
`Status: Draft` 改成 `Status: Approved`。

这一步故意不让 Agent 自己改——批准是你的责任，不是它的。`/hf-plan` 会检查这个字段，
不是 `Approved` 就拒绝往下走。

## 三、阶段 2：出实施书

```
/hf-plan
```

它会：

1. 检查上游 `Status`，不是 `Approved` 直接停。
2. 派子代理调研代码现状，**实际读你项目的 `package.json` / `pyproject.toml` / `Makefile`**
   来确认真实的构建测试命令。这一步决定 `verify` 命令能不能用。
3. 切阶段 → 阶段内切并行批次 → 给模型档位 → 写 `02_IMPLEMENTATION_PLAN.md` + `03_TASKS.json`。
4. 跑结构自检并把结果报给你：

```
阶段数：3   任务数：11   最大批内并发：3
并行批次路径不相交：PASS
ID 唯一性 / 依赖存在性 / 无环：PASS
计划与任务图 ID 一一对应：PASS
verify 命令均可执行且非交互：PASS
```

**你要做的**——这一步值得花时间看，它决定后面所有阶段的质量：

- **`verify` 命令是不是真命令。** 有 `<占位符>` 或猜的命令，说明调研不到位，让它重查。
  验证命令写错等于整个闸门失效。
- **并行批次切得合不合理。** 看每个 `parallel` 批次里的任务路径是否真的不相交。
  也看有没有为了并行把一个内聚改动拆成互相打补丁的碎片——那样并行度上去了，返工也上去了。
- **验收标准可不可判定。** 「性能可接受」不行，「P95 < 200ms，用 `bench.py` 测」才行。
- **模型档位合不合理。** 想省钱就说「P02 用 economy 档」，它会按 `economy` 字段调整。

满意后手工把 `02_IMPLEMENTATION_PLAN.md` 的 `Status` 改成 `Approved`。

## 四、阶段 3：执行

```
/hf-run
```

**不带参数就是全自动**：从第一个未完成阶段起连续跑完所有阶段，中途不问你"是否继续"。
只在命中停止条件时停（人工门、预算耗尽、修复用尽、文档矛盾、需要真实环境操作）。

| 命令 | 行为 |
| --- | --- |
| `/hf-run` | 全自动，跑完所有未完成阶段 |
| `/hf-run P03` | 只跑 P03，跑完停 |
| `/hf-run P03+` | 从 P03 起连续跑完后续所有阶段 |

### 全自动为什么不会让上下文变糊

每个阶段整体交给一个新建的 `hf-phase-orchestrator` 子代理，它在**自己的上下文**里跑完
整个阶段（调度 worker、验证、写交付文档），只向主会话返回一页摘要：

```
主会话（你的会话）                    ← 只累积各阶段一页摘要
  │
  ├── hf-phase-orchestrator  P01  opus       ← 独立上下文，跑完即释放
  │     ├── hf-task-worker   sonnet  P01-T01 ┐
  │     ├── hf-task-worker   sonnet  P01-T02 ├ 同一消息发出，真并行
  │     └── hf-test-worker   haiku   P01-T03 ┘
  │     └── hf-verifier      opus            ← 独立重跑 verify
  │   ↓ 返回一页摘要
  │   主会话复核 → 落状态 → 两个提交
  │
  ├── hf-phase-orchestrator  P02  opus       ← 全新上下文
  └── ...
```

所以跑到第 8 个阶段时，主会话的判断质量和第 1 个阶段一样——它从没见过 P01 的实现细节，
只见过 P01 的摘要。这是嵌套子代理带来的，不是靠你手动分会话换来的。

### 主会话每阶段做的复核

它不会直接采信 phase-orchestrator 的 PASS，会用只读命令核这几项：

- 摘要字段完整性（缺字段就是证据不足）
- `git diff --name-only` 是否都落在本阶段的允许路径并集内
- HEAD 未被改动、无历史重写
- 交付文档存在，且抽查验收证据那一节与摘要一致
- worker 派发数在预算内
- `active_scope.json` 已清理

复核不过就为同一阶段**新建**一个 phase-orchestrator，最多 2 次。

### 走 GLM 中转时先切单模型模式

```bash
mkdir -p .git/harnessflow
echo '{"mode":"single_model"}' > .git/harnessflow/models.json
```

只做一次，之后 `/hf-run` 每轮会读它并告诉你走的是哪套规则。

为什么需要这个开关：`opus`/`sonnet`/`haiku` 是 Claude Code 的内部别名，解析时对着
Anthropic 的模型目录，不是发给端点的字符串。你用 ccswitch 配好了映射，但档位区分在
只有一个模型的端点上本来就没有意义——真正的问题是另外两处逻辑会失效：

1. **修复重试会"上调一档"**。单模型下没有更高档，这条规则变成空操作，
   却仍然消耗一次修复配额。单模型模式改成：重试时增加给新 worker 的信息量
   （完整失败输出 + diff + 明确诊断方向），连续两次同法失败就置 `blocked` 交给人。
2. **验证方比实现方强**这个前提不成立了。`multi_tier` 下是 opus 判 sonnet 写的代码；
   单模型下是同一个模型判自己写的代码。独立性还在（全新上下文、只读工具、重跑命令拿真实
   退出码），但"更强模型复核"这一层没了，对「测试是否真能捕获错误」这类判断的可靠性下降。

所以单模型模式下 `/hf-plan` 会主动加严 `verify`——多加类型检查、lint、覆盖率门槛，
把闸门做成客观的；需要人判断的验收条目改成 `human_gate`。客观命令越多，
越不依赖那个弱化了的判断环节。

换回官方端点：改成 `{"mode":"multi_tier"}` 或删掉这个文件。任务图不用动。

### 预算闸门

`/hf-run` 开始时会写 `.git/harnessflow/budget.json`：

```json
{"max_worker_spawns_per_phase": 24, "max_repair_attempts": 2}
```

全自动模式下这是防止一个坏任务图把 token 烧穿的唯一闸门。想改就直接说
「worker 上限设 12」，或自己编辑这个文件。

嵌套子代理有失控烧 token 的真实案例（递归 spawn 几分钟耗掉数百万 token）。
这套方案的防线是结构性的：worker 的定义里**没有** `Agent` 工具，第 2 层就是底，
加上每阶段的派发上限。不要给 worker 加 `Agent` 工具。

### 想要更省心

配合 `/loop` 可以让它在阻塞解除后自己接上，但**不建议**——阻塞通常意味着需要你做判断，
自动重试只会重复撞墙。人工门更是必须你看。

### 中途查看进度

任何时候开个会话跑：

```
/hf-status
```

只读，不会动任何东西。给阶段进度、下一批任务、阻塞项、一致性检查结果。

### 遇到人工门

任务标了 `human_gate` 时，它会实现完、跑完自动校验，然后停下：

```
任务 P02-T05 需要人工确认
交接文件：docs/harnessflow/handoffs/P02-T05.md
需要你检查：<具体步骤>
```

你做完检查，**手工**把交接文件里那行 `Status: Pending Review` 改成 `Status: Accepted`，
别改文件里其他内容，然后重跑 `/hf-run` 继续。

### 遇到阻塞

修复两次仍失败的任务会置 `blocked` 并停下，`04_STATE.md` 里有准确的阻塞点和恢复条件。
常见原因和处理：

| 现象 | 通常原因 | 怎么办 |
| --- | --- | --- |
| 子代理返回 `BLOCKED`，说需要改范围外文件 | `allowed_paths` 切得不对 | 改 `03_TASKS.json` 的路径，或拆一个新任务 |
| verifier 报越界 | 并行批次路径实际相交 | 回 `/hf-plan` 重切那个批次 |
| verify 命令跑不起来 | 命令是猜的 | 手工确认真实命令，改任务图 |
| 反复实现不对 | 设计书有空白 | 回 `/hf-design` 补设计，别在执行阶段硬凑 |

改完任务图后重跑 `/hf-run`，它会重读状态继续。

## 五、常见问题

**Q：能跳过设计和规划，直接执行吗？**
不能，`/hf-run` 要求 `02_IMPLEMENTATION_PLAN.md` 是 `Approved`。小改动本来也不该走这套流程——
直接跟 Claude Code 说就行，这套编排是给需要分阶段、需要并行、需要留下验证证据的工作用的。

**Q：`Status` 能让 Agent 自己改吗？**
技术上你可以让它改，但那等于取消了三个批准闸门。这套方案的价值恰恰在于每个阶段推进前
有一个人看过。

**Q：并行度上不去怎么办？**
看 `02_IMPLEMENTATION_PLAN.md` 的 `Dependency Notes`，那里写了哪些共享文件阻止了并行。
通常是某个统一导出入口或配置汇总文件。真要提并行度，就重构掉那个瓶颈文件，
或者接受串行——一次串行的代价是一轮时间，一次错误并行的代价是排查冲突。

**Q：想改模型档位配置？**
两个地方：`.claude/agents/hf-*.md` 的 `model:` 字段改默认档位；`03_TASKS.json` 里
每个任务的 `model` 字段改单个任务。任务级覆盖子代理默认值。

**Q：怎么确认 hook 真的在拦？**
`/hf-run` 执行中的任何时刻，`.git/harnessflow/active_scope.json` 都应该存在且内容是当前批次。
它不存在说明 `/hf-run` 没写——那时 hook 只拦受保护路径和危险命令，不拦越界写入。

**Q：跑完全部阶段之后？**
`docs/harnessflow/FINAL_REPORT.md` 里有完成清单、测试汇总、与设计的偏离、已知限制、后续建议。
各阶段的 `deliverables/P*.md` 是详细证据链。
