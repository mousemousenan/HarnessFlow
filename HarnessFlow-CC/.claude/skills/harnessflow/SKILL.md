---
name: harnessflow
description: HarnessFlow 三阶段 AI 开发流程的共享不变量与数据契约。当需要产出或修改 docs/harnessflow/ 下的设计书、分阶段实施书、任务图、执行状态，或需要判断阶段推进、并行批次划分、模型档位选择、验收判定规则时使用。/hf-design、/hf-plan、/hf-run、/hf-status 均以本文件为唯一规则来源。
---

# HarnessFlow 共享契约

三个阶段共用的规则。任何命令或子代理在做判断时以本文件为准，不从聊天历史补充需求。

## 核心不变量

这五条在任何阶段都不允许放松：

1. **文档是唯一事实来源。** 需求来自 `00_REQUIREMENTS.md`，设计来自 `01_DESIGN.md`，
   范围来自 `02_IMPLEMENTATION_PLAN.md` + `03_TASKS.json`，进度来自 `04_STATE.md`。
   聊天历史不是事实来源；代码只是现状证据，不是需求依据。
2. **Agent 不能自我宣布完成。** 子代理返回的 `result` 字段是建议。任务变为 `done` 必须经过
   独立验证：路径归属核对 + `verify` 命令重跑 + 验收标准逐条判定。
3. **写入范围受 `allowed_paths` 约束。** 越界写入是失败，不是"顺手修一下"。
   需要改范围外文件时返回 `blocked` 并说明，由主会话决定是改任务定义还是新增任务。
4. **失败用全新上下文修复。** 不在失败的子代理里反复试。收集 diff + 错误摘要 + 日志路径，
   交给一个新建的子代理，最多 `max_repair_attempts`（默认 2）次，之后置 `blocked`。
5. **人工门不可代签。** `human_gate` 任务由 Agent 完成实现和自动校验，写好交接文件后停下。
   只有人能把交接文件的 `Status` 改为 `Accepted`。

## 阶段推进闸门

```
需求 Approved ──► 设计 Approved ──► 实施书 Approved ──► 执行
                                                        │
                                          ┌─────────────┴─────────────┐
                                          │ 每阶段：实现 → 独立验证    │
                                          │ → 交付文档 → 状态 → 提交   │
                                          └─────────────┬─────────────┘
                                                        ▼
                                                   下一阶段
```

上游文档的 `Status` 不是 `Approved` 时，不进入下游阶段。这个批准动作由人做，不由 Agent 代做。

## 任务图数据契约

`03_TASKS.json` 是 `{"phases": [...]}` 结构。每个 phase：

| 字段 | 含义 |
| --- | --- |
| `id` | 阶段 ID，如 `P02`，全局唯一 |
| `title` | 阶段目标一句话 |
| `depends_on` | 前置阶段 ID 列表 |
| `status` | `todo` / `in_progress` / `blocked` / `awaiting_human` / `done` |
| `model_recommendation` | `{"primary": "...", "economy": "...", "rationale": "..."}` |
| `definition_of_done` | 阶段级完成定义，字符串数组 |
| `deliverable` | 本阶段交付文档路径，如 `docs/harnessflow/deliverables/P02.md` |
| `batches` | 并行批次数组，见下 |

每个 batch：

| 字段 | 含义 |
| --- | --- |
| `id` | 批次 ID，如 `P02-B1` |
| `mode` | `parallel`（批内任务同时启动）或 `serial`（批内逐个执行） |
| `tasks` | 任务数组 |

每个 task：

| 字段 | 含义 |
| --- | --- |
| `id` | 任务 ID，如 `P02-T03`，全局唯一 |
| `title` | 一句话标题 |
| `agent_type` | `coding` / `testing` / `review` / `research`，决定子代理路由 |
| `execution_mode` | `parallel` / `serial` / `human_gate` |
| `model` | `opus` / `sonnet` / `haiku`，该任务实际使用的档位 |
| `status` | `todo` / `running` / `blocked` / `failed` / `awaiting_human` / `done` |
| `depends_on` | 同阶段内前置任务 ID（跨批依赖必须体现为更靠后的批次） |
| `goal` | 单一、可观察的目标 |
| `context.read_first` | 必须先读的文件 |
| `context.queries` | 建议先做的聚焦搜索 |
| `allowed_paths` | 本任务允许写入的仓库相对路径或 glob，非空 |
| `expected_outputs` | 必须产出的文件或产物 |
| `acceptance` | 可观察验收条件，逐条可判定 |
| `verify` | 非交互验证命令，非空，由验证方独立重跑 |
| `tests` | 测试矩阵对象，键为 `unit` / `integration` / `e2e` / `ui_interactive`。前三个键的值是测试文件数组，每个文件项含 `file`、`covers`（需求 ID 数组）和 `scenarios`（关键测试场景数组）；`ui_interactive` 的值是 playwright-mcp 场景数组，每项含 `description`、`covers`、`tool`、`mode` 和 `scenarios`。 |
| `coverage_matrix` | 每个被本任务覆盖的需求 ID 到覆盖状态的映射，状态含 `unit`、`integration`、`e2e`、`ui` 布尔值和 `confidence`（`high` / `medium` / `low`）。 |

### 结构校验规则

任何命令在读取任务图后先自检，不通过就停下报错，不要带着坏图往下跑：

- 所有 `id` 全局唯一；`depends_on` 引用的 ID 都存在；无环。
- 每个任务 ID 在 `02_IMPLEMENTATION_PLAN.md` 中以 `### Task <ID>:` 恰好出现一次。
- 每个阶段 ID 在实施书中以 `## Phase <ID>:` 恰好出现一次。
- `allowed_paths`、`verify` 非空。
- 实现任务的 `coverage_matrix` 至少覆盖一个 `00_REQUIREMENTS.md` 中的需求 ID；每个需求 ID 至少有一个测试文件在 `tests` 的 `covers` 中声明。
- `confidence` 必须等于实际覆盖测试层数：3 层为 `high`，2 层为 `medium`，1 层为 `low`；层数不足 3 的需求需在实施书中列为风险项。
- `ui_interactive` 中每个测试声明的 `covers` 必须出现在 `coverage_matrix`；`ui=true` 只适用于
  `tool=playwright-mcp` 且 `scenarios` 非空的测试。
- **同一 `parallel` 批次内，任意两个任务的 `allowed_paths` 不得相交。** 这是并行安全的基础。
- 任务的 `depends_on` 只能指向同阶段更早的批次或更早的阶段，不能指向同批次内的任务。

## 并行批次划分规则

目标是最大可并行，但不靠运气。判定顺序：

1. **先按文件边界切。** 两个任务只要写入路径不相交，就是并行候选。相交则必须分批。
   共享文件（如统一导出入口、路由注册表、配置汇总）单独作为一个后续串行任务收口，
   不要让多个并行任务都去改它。
2. **再按契约方向切。** 定义接口 / 类型 / schema 的任务放前一批，消费它们的实现放后一批。
   同一批内不允许一个任务定义、另一个任务同时消费同一符号。
3. **测试可与实现同批的条件**：测试文件路径独立，且被测接口签名在更早批次已冻结。
   否则测试跟在实现之后一批。
4. **收口任务串行。** 集成、跨模块联调、文档汇总、依赖升级、格式化全仓，一律 `serial`。
5. **批内并发上限 4。** 超过就再切一批。并发多于 4 时，主会话对结果的核对质量会下降，
   可靠性优先于并发数量。

判定不确定时，选择更保守的分批。一次串行的代价是一轮时间，一次错误并行的代价是排查冲突。

## 模型档位选择

**先读 `.git/harnessflow/models.json`。** `mode` 为 `single_model` 时（第三方中转、
只有一个模型可用），本节的档位区分不适用——按 `MODELS.md` 的单模型规则走，
那里说明了不传 `model` 参数、修复不上调档位、验证弱一档需要如何补偿。

以下是 `multi_tier`（默认，Claude 官方端点）的规则。

每个阶段给两档推荐，每个任务落一个实际档位。`.claude/agents/` 下的子代理定义带默认档位，
任务的 `model` 字段可覆盖（通过 `Agent` 工具的 `model` 参数传入）。

| 档位 | 适用 |
| --- | --- |
| `opus` | 架构决策、跨模块重构、并发/状态机/协议实现、安全边界、根因不明的调试、独立验证判定 |
| `sonnet` | 明确规格下的常规实现、单模块 CRUD、有先例可循的重构、常规测试编写 |
| `haiku` | 样板代码、机械化改名、格式与配置文件、按模板生成测试骨架、只读信息收集 |

选档依据写进 `rationale`，说明为什么这个阶段配得上或配不上高档位。判断线索：

- 该阶段是否需要在多个可行方案之间做取舍 → 是则 `opus`。
- 规格是否已经细到不需要再判断 → 是则可以降到 `sonnet` 或 `haiku`。
- 出错是否会污染后续所有阶段（数据模型、公共接口、并发原语）→ 是则 `opus`，不为省钱冒险。
- 验证方（`hf-verifier`）不降档。判定环节降档等于放弃闸门意义。

`economy` 档是给用户的成本选项，不是默认。默认走 `primary`。

## 子代理路由与层级

```
第 0 层  主会话（/hf-run）        ← 只累积各阶段摘要
第 1 层  hf-phase-orchestrator    ← 一个阶段一个实例，独立上下文
第 2 层  hf-task-worker / hf-test-worker / hf-phase-lead / hf-verifier
         ← 这一层的定义里没有 Agent 工具（hf-phase-lead 例外，只能派只读 hf-explorer）
```

嵌套到此为止。Claude Code 默认允许深度 3、最多可配到 5，但更深没有收益，
只会让 token 消耗失控且难以追溯。

| `agent_type` | 子代理 | 默认档位 | 层级 |
| --- | --- | --- | --- |
| （阶段整体） | `hf-phase-orchestrator` | opus | 1 |
| `coding`（批内并行任务） | `hf-task-worker` | sonnet | 2 |
| `coding`（需跨模块判断的串行任务） | `hf-phase-lead` | opus | 2 |
| `testing` | `hf-test-worker` | haiku | 2 |
| `review` | `hf-verifier` | opus | 2 |
| `research` | `hf-explorer` | haiku | 2 或 3 |

## 预算

`.git/harnessflow/budget.json`，全自动模式下必须存在：

```json
{"max_worker_spawns_per_phase": 24, "max_repair_attempts": 2}
```

phase-orchestrator 自己记账，达到上限立即停止派发并返回 `BLOCKED`。
无声地把一个坏任务图跑成 token 黑洞，比停下让人看一眼糟糕得多。

## 子代理返回契约

子代理只返回结构化摘要，不返回大段原始日志、栈回溯或探索过程。完整日志留在测试产物或文件里，
摘要中给路径。字段：

```
TASK: <任务 ID>
RESULT: PASS | FAIL | BLOCKED | HUMAN_BLOCKER
CHANGED_FILES:
  - <路径> — <这个文件为什么改>
COMMANDS:
  - <命令> → exit <码> — <单行结果>
ACCEPTANCE:
  - <验收条件> → 满足 | 不满足 — <证据>
UI_TESTS:
  - <scenario> → PASS | FAIL | NOT_AVAILABLE
SCREENSHOTS:
  - <路径，或 NONE>
EXPECTED_OUTPUTS:
  - <产物> → 已产出 | 缺失
LESSONS: <可复用经验，或 NONE>
RISKS: <剩余风险或 blocker，含准确恢复条件，或 NONE>
```

没有 `ui_interactive` 测试时省略 `UI_TESTS` 和 `SCREENSHOTS`。playwright-mcp 不可用时，
把每个 scenario 标为 `NOT_AVAILABLE`，并在 `RISKS` 中提供手工测试清单。

## 阶段质量门禁

- **设计阶段**：需求文档必须通过 `scripts/validate-ears.sh`；每个 REQ-ID 都有可判定验收标准。
- **规划阶段**：运行 `scripts/test-coverage-report.js`；所有 REQ-ID 必须出现在 coverage matrix 中，
  LOW confidence 的关键需求必须列为风险项。
- **实施批次**：除基础验证外，执行 Adequacy Review 和 Sensor 扫描；阶段结束产出
  `docs/harnessflow/LESSONS-<Phase>.md`。
- **最终交付**：所有 sensor 无 `fail`，测试覆盖率满足阶段目标（默认 > 80%），所有 REQ-ID 验证通过。

字段缺失、改动范围不符、证据不足时，主会话不接受 PASS，为同一任务新建子代理，
不复用已结束的实例。

## 停止条件

只允许在这些情况下停下来问人：

- 所有阶段 `done`，走最终收尾。
- 出现 `HUMAN_BLOCKER`：模型无法解决的阻塞。
- 文档之间存在互相矛盾的要求，必须产品决策。
- 下一步需要真实资金操作、真实密钥授权、生产环境变更或不可逆外部操作。
- 修复次数用尽，任务 `blocked`。

不要把常规阶段推进包装成确认请求。不要问"是否继续"、"是否开始下一阶段"。

## 状态与恢复

`04_STATE.md` 是运行账本，与 `03_TASKS.json` 的 `status` 交叉核对。两者不一致时，
以已有验证证据为准保守恢复：有通过证据的算 `done`，无证据的退回 `todo`，不猜。

进程中断留下 `running` 状态时，重新读图 + `git status` + `git log` 判断实际进度，
显式重置或继续该任务，绝不复用旧聊天上下文。
