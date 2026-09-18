---
description: 阶段 3 — 按实施书执行开发。每阶段独立上下文，批内并行子代理，独立验证后才推进
argument-hint: [可选：阶段 ID，如 P03。省略则从第一个未完成阶段开始]
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Agent, AskUserQuestion, Skill
---

先调用 `Skill(harnessflow)` 载入共享契约。执行判定规则、子代理路由、返回契约、停止条件
全部以该 skill 为准。

参数：`$1`

| 参数 | 行为 |
| --- | --- |
| 空 | **全自动**：从第一个未完成阶段起，连续跑完所有阶段 |
| `P03` | 只跑 P03 一个阶段，跑完停下 |
| `P03+` | 从 P03 起连续跑完后续所有阶段 |

## 你的角色：唯一 orchestrator

你负责：建立基线、按依赖顺序推进阶段、把每个阶段交给一个独立子代理、复核它的摘要、
写状态、提交。

你**不**负责：任何阶段的代码分析、实现、调试、跑业务测试。这些交给子代理。
你自己动手写实现代码，就等于放弃了上下文隔离——这是本方案存在的理由。

例外：写 `04_STATE.md`、执行 git 提交、必要的只读复核，这些由你做。

## 上下文隔离怎么做到的

每个阶段交给一个新建的 `hf-phase-orchestrator` 子代理，它在自己的上下文里跑完整个阶段
（调度 worker、验证、写交付文档），只返回一页摘要。你的上下文里只累积摘要，不累积实现细节。

```
主会话（你）               ← 只有各阶段摘要
  └── hf-phase-orchestrator（P01）  ← 独立上下文，跑完即释放
        ├── hf-task-worker ×3       ← 同一消息发出，并行
        └── hf-verifier
  └── hf-phase-orchestrator（P02）  ← 全新上下文
        └── ...
```

所以全自动跑十个阶段，你在第十个阶段的判断质量和第一个一样。

**深度纪律**：你在第 0 层，phase-orchestrator 在第 1 层，worker 在第 2 层。
worker 的定义里没有 `Agent` 工具，到此为止。任何情况下不要让 worker 再派子代理。

## 1. 建立事实基线

读这些，顺序固定：

1. `docs/harnessflow/01_DESIGN.md` — 设计事实
2. `docs/harnessflow/02_IMPLEMENTATION_PLAN.md` — 阶段与任务定义
3. `docs/harnessflow/03_TASKS.json` — 依赖图与状态
4. `docs/harnessflow/04_STATE.md` — 运行账本
5. 仓库根 `CLAUDE.md`（若有）
6. `git status` 与 `git log --oneline -5`

实施书 `Status` 不是 `Approved` 就停下，让用户先跑 `/hf-plan`。

按 skill 的结构校验规则自检任务图。不通过就停下报错，不要带着坏图执行。

工作区必须干净。有未提交改动时：如果 `04_STATE.md` 记录了对应的进行中任务，视为中断恢复，
按 skill 的「状态与恢复」规则处理，不要复用旧编排器上下文；否则停下，告诉用户这些改动
不属于本流程，请先处理。不要覆盖或清理不属于当前任务的改动。

## 2. 确认运行模式与预算

读 `.git/harnessflow/models.json`。`mode` 为 `single_model` 时，先读
`.claude/skills/harnessflow/MODELS.md` 并按其规则执行——它改变四件事：不传 `model` 参数、
修复不上调档位、验证弱一档需要补偿、确定性 `verify` 由编排器直跑取证。
文件不存在按 `multi_tier` 处理。

把当前模式在本轮开始时告诉用户一句，让他知道走的是哪套规则。

写 `.git/harnessflow/budget.json`（已存在则沿用，用户本轮指定了别的值则按用户的）：

```json
{"max_worker_spawns_per_phase": 24, "max_repair_attempts": 2}
```

phase-orchestrator 读它并自己记账，超限就停下返回 `BLOCKED`。全自动模式下这是防止
一个坏任务图把 token 烧穿的唯一闸门，不要省掉这一步。

## 3. 阶段循环

按依赖顺序逐个阶段执行。每轮一个阶段，循环直到全部 `done` 或命中停止条件。

### 3.1 选定本轮阶段

以 `04_STATE.md` 为账本，与 `03_TASKS.json` 的 `status` 交叉核对，取第一个非 `done` 的阶段。
两者不一致时按 skill 的恢复规则保守处理。

确认 `depends_on` 全部 `done`。有未完成依赖时沿依赖链回到最早的未完成阶段执行它，
不要跳过，也不要仅因依赖未完成就停下。

把该阶段标为 `in_progress`，在 `04_STATE.md` 写入本轮记录（阶段 ID、开始时间、
批次计划、各任务将用的档位、本次尝试次数、阶段重派已用次数、worker/修复已用预算）。
这些是现有状态账本中的运行记录，不新增摘要字段。

### 3.2 交给 phase-orchestrator

派**一个新建的** `hf-phase-orchestrator`，`model` 取该阶段 `model_recommendation.primary`
（用户要求 economy 档时取 `economy`）。prompt 给它：

```
阶段 ID：<id>
阶段目标：<title>
交付文档路径：<deliverable>

Definition of Done：
- <definition_of_done 逐条>

本阶段批次与任务定义（从 03_TASKS.json 原样摘出这个阶段的 batches）：
<JSON>

上游阶段的 NEXT_PHASE_NOTES：
<前一阶段返回的 NEXT_PHASE_NOTES，无则写 无>

上游交付文档（需要时自行读取）：
- docs/harnessflow/deliverables/<已完成阶段>.md

适用的仓库指令：
<CLAUDE.md 中与本阶段相关的条目，无则写 无>

预算：worker 派发上限 <n>，修复上限 <m>

按你的定义跑完这个阶段，返回一页摘要。不要创建 git 提交，
不要改 03_TASKS.json 和 04_STATE.md——那两件事由主会话做。

若这是恢复重派，附恢复简报（按 skill 格式）以及：
- 上次实例 / 尝试次数 / 台账边界
- 已用预算：阶段重派 <n>/2，worker <used>/<max>，修复 <used>/<max>
- 只做剩余动作；已通过独立验证的任务不要重做实现
```

派发必须使用可被状态查询和停止的执行方式。记录实际后台任务标识、派发时间、
本次台账起始位置（现有 `phase_started` 边界；新实例由编排器启动时写入）。
**一次只派一个阶段。** 阶段之间有依赖，并行跑阶段等于放弃依赖约束。
同一时间只允许一个活动阶段编排器和一个台账写入者。

### 3.2b 派发后看门狗

派出阶段编排器后，按 skill「主会话看门狗」建立会话级唤醒检查。绑定阶段 ID、
当前后台任务标识、派发时间与本次台账边界，记录实际定时任务 ID。
`allowed-tools` 只使用本环境已实测可用的定时、查询和停止工具；未验证的名称不得照抄。

看门狗只读检查，不写源码、台账或运行中的 scope。每轮结果写入 `04_STATE.md` 运行记录：
实际检查时间、实例状态、活动证据、最后心跳时间、异常计数和处理动作。

判定与处置以 skill 为准：健康则清零计数；连续两轮不健康才停滞处置；
明确失败不必等两轮；HUMAN_BLOCKER / 预算用尽 / 最终失败取消看门狗并停止自动派发；
过期唤醒只核对本实例绑定，忽略旧回调。

停滞处置顺序固定：再确认仍是当前实例 → 停止该编排器及其仍会写文件的 worker/命令 →
确认停止后，仅当 `active_scope.json` 属于被终止实例才清理这一份残留 →
取消旧看门狗 → 把中断证据、已用预算和重派计数写入 `04_STATE.md` →
按 skill 生成恢复简报并派全新编排器，为新实例建立新看门狗。

停止失败或归属不明时：不删 scope，不启动第二个写入者，返回明确恢复条件。
不得递归删除 `.git/harnessflow/`，不得删除台账和验证日志。
同阶段最多重派 2 次（初次不计）；看门狗停滞、异常退出和摘要复核失败共用该计数。

若定时唤醒或停止能力不可用，记录 O1 未启用，不执行自动清理和重派，也不声称自动保护已生效。

### 3.3 复核摘要

不要直接采信 phase-orchestrator 的 `RESULT: PASS`。做这些只读复核：

- 摘要字段是否完整（缺字段就是证据不足，不接受 PASS）
- `multi_tier` 模式下：`MODELS_USED` 是否与任务图的 `model` 字段一致。
  子代理定义里是 `model: inherit`，档位只能靠传参落实——全都等于主会话模型说明漏传了，
  指出来并在下一阶段修正。`single_model` 模式下跳过这一项
- `git diff --name-only` 的实际改动是否都落在本阶段任务的 `allowed_paths` 并集内
- `git log --oneline -3` 确认 HEAD 未被改动、无历史重写
- 交付文档存在且内容与摘要一致（抽查验收证据那一节，不是只看文件在不在）
- `WORKER_SPAWNS` 是否在预算内；与台账 `worker_dispatched` 对照，缺记录时保守核对宿主记录
- `.git/harnessflow/active_scope.json` 是否已被清理
- 读取 `.git/harnessflow/phase_ledger.jsonl`：按本次实例边界和阶段筛选，从尾部定位，
  必要时向前读完未完成任务，不能只看文件末行。显著步骤是否完整，是否与摘要和独立验证证据一致
- `single_model` 下每个完成任务是否有收口的 verify 日志和 `verifier_returned` 指向的独立结论

首次遗漏心跳记入 LESSONS，不单独因此判失败。若同时缺少验证证据，仍不能接受 PASS。
完成通知本身不能直接把阶段标为 `done`。

复核通过或进入终态后，取消本实例看门狗。复核发现问题时，为**同一阶段**新建一个
phase-orchestrator，把问题点和恢复简报写进 prompt。
不要 SendMessage 复用已结束的实例——那是带着已失败假设的旧上下文。
同一阶段最多重派 2 次（含看门狗停滞与异常退出），之后置 `blocked` 停下。

### 3.4 落状态并提交

复核通过后：

1. `03_TASKS.json` 中该阶段与其任务标 `done`
2. `04_STATE.md` 追加执行记录：批次结论、改动文件数、实际档位、worker 派发数
3. 两个提交：一个实现提交 + 一个状态提交。提交信息说明阶段 ID 与主要改动
4. **不要 `git push`**，不碰远端

### 3.5 决定是否继续

- 参数是单个阶段 ID（如 `P03`）→ 停下，报告本阶段结果
- 参数为空或带 `+` → 回到 3.1 跑下一个阶段，**不要询问用户「是否继续」**
- 全部阶段 `done` → 进入第 5 节最终收尾

phase-orchestrator 返回 `HUMAN_BLOCKER` 或 `BLOCKED` 时按第 4 节处理。

## 4. 中断处理

任何终态（正常完成、HUMAN_BLOCKER、预算耗尽、FAIL、复核不通过、看门狗停滞处置后）
都先取消本实例看门狗。人工门不得自动续跑或代签。旧看门狗回调到达时只核实例绑定，
不得停止后来派出的编排器。

| 返回 | 你要做的 |
| --- | --- |
| `HUMAN_BLOCKER` | 取消看门狗，阶段标 `awaiting_human`，报告交接文件路径和需要人做什么，停下 |
| `BLOCKED`（预算耗尽） | 取消看门狗，阶段标 `blocked`，报告已完成批次和剩余批次，问用户是提额还是改任务图 |
| `FAIL`（修复用尽） | 取消看门狗，阶段标 `blocked`，把摘要里的 `RISKS` 和失败命令原样报给用户，停下 |
| 复核不通过或看门狗停滞 | 计入同一阶段重派计数；仍有预算则按 skill 恢复顺序重派全新编排器，否则标 `blocked` 停下 |
| 复核不通过累计 3 次尝试（初派 + 2 次重派） | 阶段标 `blocked`，说明每次复核或停滞发现的问题，停下 |

恢复顺序与 skill「状态与恢复」相同：

1. 确认旧实例及其写入者已停止，再清理属于旧实例的 scope。
2. 按本次实例边界读取台账，重建已派发 / 已返回 / 已取证 / 已独立验证 / 待收尾。
3. 按台账读取日志、交付和 verifier 结论，并保留 `git status`、HEAD 与路径归属核对。
4. 把恢复简报交给全新编排器，只做剩余动作；继承重派计数与剩余 worker/修复预算。

不要把 worker PASS、命令 exit 0、产物存在直接转换成 `done`。
台账缺失、截断或损坏时走 skill 的退化恢复，记录原因，不编造中断点。

以上都要在 `04_STATE.md` 写下准确的阻塞点和恢复条件——用户处理完重跑 `/hf-run` 要能接上。

停下时给用户一份可操作的报告：卡在哪、为什么、改什么能解开。不要只说"失败了"。

## 附：单阶段模式的批内细节

以下内容是 `hf-phase-orchestrator` 的职责，写在这里供参考与调试。
主会话在全自动模式下**不**直接做这些——直接做就等于把实现细节拉回主上下文。

### 每批开始前：声明范围

启动 worker 之前，写 `.git/harnessflow/active_scope.json`（目录不存在先建）：

```json
{
  "batch": "<批次 ID>",
  "allowed_globs": ["<本批全部任务 allowed_paths 的并集>"],
  "tasks": {"<任务 ID>": ["<该任务的 allowed_paths>"]}
}
```

`hf_scope_guard.py` hook 读这个文件拦截越界写入。不写它，hook 就没有范围可依据，
越界写入只能靠事后 diff 发现，修复成本高一个数量级。

`.git/harnessflow/phase_ledger.jsonl` 与 `verify-logs/` 同属运行基础设施，
不放进任务 `allowed_paths`。只有阶段编排器追加台账。

批次验证通过后删除该文件，再写下一批的。阶段收尾时确保它已被删除——
残留的旧范围会在下次运行时错误地限制或放宽写入。

### 并行批次

`mode: parallel` 的批次，**在同一条消息里发出该批次全部任务的 `Agent` 调用**，
这样它们才真正并发。分成多条消息发就变成串行了。

每个 `Agent` 调用：

- `subagent_type`：按 skill 的路由表，由任务的 `agent_type` 决定
- `model`：`multi_tier` 模式下传任务的 `model` 字段值；`single_model` 模式下**省略这个参数**
  （见 `MODELS.md`）。用户在本轮明确指定过模型时，用用户指定的值原样传递，不擅自升降档
- `description`：任务 ID + 短标题
- `prompt`：结构化任务包，见下

任务包内容（不要让子代理去猜，也不要让它读聊天历史）：

```
任务 ID：<id>
标题：<title>
目标：<goal>

必读文件（先读完再动手）：
- <context.read_first 逐条>

建议先做的搜索：
- <context.queries 逐条>

允许写入路径（唯一可写范围，越界即失败）：
- <allowed_paths 逐条>

必须产出：
- <expected_outputs 逐条>

需要的测试：
- <tests>

验收标准（逐条可判定）：
- <acceptance 逐条>

自查命令（你可以跑，但最终由独立验证方依据原始证据判定；`multi_tier` 下由 verifier 重跑）：
- <verify 逐条>

设计约束摘录：
<从 01_DESIGN.md 摘出与本任务相关的不变量与接口契约，只摘相关部分>

适用的仓库指令：
<CLAUDE.md 中与本任务相关的条目，无则写 无>

同批并行的其他任务正在改这些路径，绝对不要碰：
- <同批其他任务的 allowed_paths>

按 skill 的返回契约返回结构化摘要。不要返回大段日志。
不要创建 git 提交。不要改 docs/harnessflow/03_TASKS.json 和 04_STATE.md。
```

最后一段很重要：并行任务必须知道邻居的边界在哪。

### 串行批次

`mode: serial` 的批次逐个执行，同样用 `Agent` 调用，一次一个。收口类任务走这里。

### 人工门任务

`execution_mode: human_gate` 的任务，子代理完成实现和自动校验后，写
`docs/harnessflow/handoffs/<任务ID>.md`，其中恰好一行 `Status: Pending Review`。
子代理绝不能写 `Accepted`。

你在这里停下，报告：实现摘要、自动校验结果、交接文件路径、需要人做什么检查。
把任务标为 `awaiting_human`。用户改完 `Status: Accepted` 后重跑 `/hf-run` 继续。

### 批内验证

批次内全部 worker 返回后，**不要**直接采信它们的 PASS。

先做形式检查（只读命令）：

- 每个返回的字段是否完整
- `git diff --name-only` 的实际改动集合，逐个文件核对属于哪个任务的 `allowed_paths`；
  有文件不属于本批任何任务的允许范围，就是越界
- `git log --oneline` 确认 HEAD 未被 worker 改动，无历史重写

形式检查过了，按运行模式取证后再派**一个** `hf-verifier` 做实质判定：

- `single_model`：编排器直跑确定性 `verify`，把原始日志写入
  `.git/harnessflow/verify-logs/<任务ID>.log`，再把日志定位和代码基线交给 verifier。
  verifier 读取原始日志并保留全部实质判定职责，不采信编排器口头结论。
- `multi_tier`：verifier 独立重跑原命令。

给它：本批次全部任务的 `verify` 命令、日志段落定位（若已直跑）、`acceptance` 条目、
`expected_outputs` 清单、以及 `git diff --name-only` 的结果。
每批仍需独立 verifier PASS 才能推进。

验证不通过时按 skill 的失败模型处理：收集 diff + 错误摘要 + 失败命令输出，
派**新建**的 worker 修复（同 `agent_type`；`multi_tier` 下档位可上调一档，
`single_model` 下改为补充失败输出、diff 和诊断方向），上限见预算。
不要在失败的 worker 上追加消息反复试——那是旧上下文，带着已经失败的假设。

### 批内收尾

该阶段所有批次通过后，写 `docs/harnessflow/deliverables/<阶段ID>.md`，
逐条核对 `definition_of_done`，删除 `active_scope.json`。
状态与提交交给主会话。

## 5. 最终收尾

全部阶段 `done` 后写 `docs/harnessflow/FINAL_REPORT.md`：完成阶段清单、
测试结果汇总、与原设计的偏离、已知限制、未解决问题、后续建议。
做一次一致性检查：实施书、任务图、状态、各阶段交付文档、最终报告互相一致。
