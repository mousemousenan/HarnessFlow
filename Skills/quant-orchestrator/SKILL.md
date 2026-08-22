---
name: quant-orchestrator
description: Orchestrate the repository's quantitative-strategy implementation plan phase by phase, including code analysis, implementation, tests, acceptance checks, state updates, checkpoint commits, and final reporting. Use when asked to execute or continue docs/开发实施.md, resume the first incomplete Phase, or autonomously carry the quantitative strategy project through all valid phases without relying on chat history.
---

# Quant Orchestrator

## 目标

自动执行量化策略开发实施计划（当前文件为 `docs/开发实施.md`）。从第一个未完成阶段开始，完成实现、验证、记录和 checkpoint，然后自动继续后续阶段，直到满足明确的停止条件。

## 执行模型：`/goal` + Main Orchestrator + Phase Subagent

每次执行先创建或恢复一个唯一的 `/goal`，并让它贯穿所有 Phase 直到最终收尾；不要为每个 Phase 创建新 goal。目标范围、成功条件和停止条件必须来自 `docs/DESIGN.md`、`docs/开发实施.md` 以及本文件；不得依赖历史聊天记忆补充目标。

- **Main Agent** 是唯一的 orchestrator，只负责建立事实基线、选择一个当前 Phase、管理执行状态与 Human Actions、调度 Phase subagent、完成 PASS 后的最终验证、更新状态文档和创建 checkpoint。Main Agent 不负责当前 Phase 的代码分析、实现、debug、Tests、Verification Commands 或 Acceptance Criteria 执行。
- **Phase subagent** 必须为每个 Phase 创建一个全新的、独立的、write-capable 实例。它独自负责当前 Phase 的代码分析、实现、debug、Tests、Verification Commands 和 Acceptance Criteria，并只能修改该 Phase 范围内的文件；不得复用上一 Phase 的 subagent。Phase subagent 可使用只读辅助 agent，但同一 Phase 同时最多一个 write-capable subagent，辅助 agent 不得编辑或提交文件。
- **子代理模型选择**：用户可在启动时以 `子代理模型=<MODEL>` 或等价的明确表述指定 Phase subagent 的模型。Main Agent 创建每个 Phase subagent 时必须将该值显式传给 `spawn_agent` 的 `model` 参数；未指定时不传 `model`，让子代理继承 Main Agent 当前模型。用户指定的模型必须原样保留，不得被 skill 擅自替换、升级或降级。若运行时不支持该模型或创建失败，记录具体原因并请求用户改选可用模型；不得静默回退为 Main Agent 模型。结构化 Phase packet 与最终摘要均须记录实际使用的子代理模型。
- Main Agent 启动 Phase subagent 时提供结构化 Phase packet：Phase 目标与范围、权威文档位置、Dependencies、Human Actions、适用的 `AGENTS.md` 指令、当前 Git 状态和必须执行的检查。Phase subagent 不从聊天记录推断需求。
- Phase subagent 结束时只返回结构化摘要，不返回大量 raw logs、stack traces 或 exploration 记录。摘要至少包含：`Phase/result`（`PASS`、`FAIL` 或 `HUMAN_BLOCKER`）、changed files 及用途、Tests/Verification Commands（命令、退出码和单行结果）、Acceptance Criteria 逐项结果、`Reusable lessons`（候选经验或 `NONE`）、剩余风险或 blocker 及准确恢复条件。完整日志应保留在测试产物或文件路径中。
- Main Agent 只有在摘要字段完整、改动范围正确且证据足够时才接受 `PASS`。Main 的 final verification 仅验证摘要、改动范围、要求的证据和文档一致性；可以重跑必要的只读检查，但不得代替 Phase subagent 修复代码或执行其实现工作。发现问题时，为同一 Phase 创建新的 fresh Phase subagent，绝不复用已结束的实例。

## 执行循环

严格按以下顺序循环执行。一个 Phase 未完成 PASS、记录和 checkpoint 前，不得创建或运行下一 Phase 的 subagent。

### 1. 建立当前事实基线

在修改任何文件前，读取：

1. `docs/DESIGN.md`
2. `docs/开发实施.md`
3. `docs/EXECUTION_STATE.md`
4. `docs/HUMAN_ACTIONS.md`
5. `AGENTS.md`
6. 当前 Git 状态，包括分支和未提交改动

如果仓库根目录不存在 `AGENTS.md`，记录该事实并继续遵守当前会话中生效的 Agent 指令；不要仅因文件缺失而停止或创建该文件。只有第 6 节出现满足全部登记条件的经验时，Main Agent 才可创建它。

只把 `docs/DESIGN.md` 和 `docs/开发实施.md` 作为需求与实施范围的事实来源。不要依赖历史聊天记忆补充需求。把当前代码和代码分析工具的结果仅作为代码结构与现状证据；把 `docs/EXECUTION_STATE.md`、`docs/HUMAN_ACTIONS.md` 和 Git 状态用于判断执行进度、人工依赖与工作区边界。

遵守仓库中的 `AGENTS.md`。保留进入本轮前已经存在且不属于当前 Phase 的改动，不覆盖、不清理、不提交这些改动。

### 2. 选择唯一当前 Phase

以 `docs/EXECUTION_STATE.md` 的 Phase 总览作为运行状态账本，并与 `docs/开发实施.md` 中的 Phase 顺序和 Status 交叉核对。找到第一个尚未为 `COMPLETE` 的 Phase；两份文档状态不一致时不要跳过该 Phase，依据已有验证证据保守恢复并同步状态。

开始前确认该 Phase 的 Dependencies 均为 `COMPLETE`。如果存在未完成依赖，沿依赖链回到计划中最早的未完成 Phase 并执行它；不要启动被依赖项，也不要仅因依赖未完成而停止。检查 `docs/HUMAN_ACTIONS.md` 中已经到达 `Required Before` 的事项。条件满足后，Main Agent 把当前 Phase 标记为 `IN_PROGRESS` 并填写当前执行记录，然后为该 Phase 创建唯一的全新独立 write-capable Phase subagent。只执行这个 Phase；在它通过全部检查前，不进入后续 Phase，也不提前实现后续需求。

如果所有 Phase 都是 `COMPLETE`，直接执行最终收尾。

### 3. 理解代码与影响面

当当前 Phase 涉及代码结构、符号定位、调用链、依赖关系或修改影响面时，由当前 Phase subagent 执行以下流程：

1. 如果 Codegraph 可用，由 Phase subagent 优先直接使用 Codegraph 获取当前代码证据，再修改代码。
2. 如果仓库已有可索引源码但 Codegraph 尚未初始化，可以初始化索引。
3. 如果 Codegraph 不可用、初始化失败或结果不足，立即降级为 `rg`、直接读取文件或 subagents；不要因此阻塞当前 Phase。
4. 不要为 Codegraph 可以直接回答的代码探索重复创建 subagent。
5. 对大量日志分析、测试分析、独立代码 review，或 Codegraph 无法覆盖的广泛探索，Phase subagent 可使用只读 subagents；不得新增 write-capable Phase subagent。

不要用 Codegraph 结果替代设计文档、实施计划、测试、Verification Commands 或 Acceptance Criteria。

### 4. 实现当前 Phase

Phase subagent 根据设计文档和实施计划实现当前 Phase 所需的最小改动。保持修改范围与该 Phase 的目标一致，不添加计划外功能。Main Agent 不直接实现或修复 Phase 代码。

### 5. 完成验证闭环

Phase subagent 实现后执行当前 Phase 列出的全部项目：

- Tests
- Verification Commands
- Acceptance Criteria

逐项记录命令、退出码、结果和验收证据，并在返回摘要中只保留精简结果。按实施计划为每条命令规定的预期结果判断成功；不要把计划明确预期的非零退出码机械地判为失败。只有全部通过才把 Phase 判定为 PASS。

如果任一项失败，当前仍由正在运行的 Phase subagent 负责定位、修复并重跑完整验证集合；它在完成这一循环后才返回摘要：

1. 保持当前 Phase 为未完成状态。
2. 定位失败原因。
3. 修复原因。
4. 重新执行受影响检查，并再次执行该 Phase 要求的完整验证集合。
5. 循环直到全部 PASS，或确认出现允许的真正 blocker；不得把失败交给下一 Phase。

如果 Phase subagent 已结束并返回 `FAIL`、摘要不完整或 Main Agent 的 final verification 发现问题，Main Agent 保持当前 Phase 未完成，等待旧实例结束后再创建一个新的 fresh Phase subagent；不得复用旧实例，且不得与旧实例并发写入。

失败时绝不进入下一 Phase。

### 6. 筛选并登记可复用经验

每次发生“实现或验证失败 -> 定位根因 -> 修复 -> 完整验证通过”的闭环后，Phase subagent 评估是否存在以后仍可能踩中的重要问题。它只提出候选经验，不直接修改 `AGENTS.md`；候选须在结构化摘要的 `Reusable lessons` 中包含失败证据、根因、适用场景、建议规则和验证方式。没有合格候选时明确写 `NONE`。

当前 Phase 全部 PASS 后，由 Main Agent 复核候选。只有同时满足以下条件才登记：

1. 经验来自本轮实际发生的失败，修复已由测试或 Verification Commands 证明有效；只有推测而没有闭环证据的内容不登记。
2. 同一机制会在多个 Phase、模块或重复执行的开发流程中再次出现，并且遗漏它会造成错误行为、测试失败、不安全操作、改动丢失或错误的 PASS 结论；一次性输入、临时环境故障、偶发外部服务错误和单纯拼写失误不登记。
3. 能写成项目相关、可执行的防错规则，明确“在什么条件下，必须做什么，如何验证”；泛泛的工程常识、事故叙述和仅对当前实现有用的细节不登记。
4. 内容属于 Agent 的开发行为约束。产品需求或架构决策写入权威设计文档或 Decision Log，执行进度写入 `docs/EXECUTION_STATE.md`，人工依赖写入 `docs/HUMAN_ACTIONS.md`，不要转写到 `AGENTS.md`。
5. 与根目录现有 `AGENTS.md`、本 skill 和权威文档不重复、不矛盾。已有等价规则时不新增；候选揭示原规则不完整时，只做最小补强。

满足条件时，仅由 Main Agent 更新仓库根目录的 `AGENTS.md`：

- 保留所有已有内容、结构和非当前 Phase 改动，仅在最匹配的现有章节补充；没有匹配章节时使用 `## 项目经验规则`。
- 每条规则使用简短祈使句，包含必要的适用范围和验证动作；不要写日期、事故经过、长日志、临时文件路径、secret 或重复证据。
- 如果文件不存在，创建 UTF-8（无 BOM）的最小 `AGENTS.md`，只包含标题和 `## 项目经验规则`；没有合格经验时不得创建或修改它。
- 更新后重新读取相关段落并检查 diff，确认规则可执行、无重复、未覆盖已有指令。把 `AGENTS.md` 变更和依据记入当前 Phase 摘要，并在后续 Phase packet 中传递更新后的指令。

`AGENTS.md` 的修改视为触发该经验的当前 Phase 改动，可随该 Phase checkpoint 提交。不要为了积累数量而登记；一次实际失败只要有明确的跨阶段复发机制即可登记，同类候选应合并为一条规则。

### 7. 记录通过结果

当前 Phase 全部 PASS 后：

1. Main Agent 执行 final verification：核对结构化摘要、changed files、Tests、Verification Commands、Acceptance Criteria 和工作区边界；必要时重跑只读检查。发现问题时回到当前 Phase，并创建新的 fresh Phase subagent。
2. 检查当前 Phase 的 Human Actions；存在已经到达 `Required Before` 且尚未完成的事项时，不要写入 `COMPLETE`，转到 Human Actions 处理流程。
3. Main Agent 在 `docs/EXECUTION_STATE.md` 中记录完成状态、实际修改、测试结果和发现。
4. Main Agent 将 `docs/开发实施.md` 中该 Phase 的 Status 更新为 `COMPLETE`。
5. Main Agent 必要时更新 Decision Log，并写明依据和影响。
6. Main Agent 尽量创建 Git checkpoint commit，消息格式为 `phase(N): <summary>`；只提交属于当前 Phase 的文件。
7. 重新读取状态和根目录 `AGENTS.md` 后，Main Agent 才能创建下一个 Phase 的全新 subagent；同一时刻保持最多一个 write-capable Phase subagent。

只提交属于当前 Phase 的文件。若已有无关改动导致无法安全创建 checkpoint，记录原因并继续，不要把无关改动混入提交。

### 8. 处理 Human Actions

如果当前 Phase 的 Human Actions 为 `NONE`，Main Agent 自动选择下一个未完成 Phase，并为其创建全新的 Phase subagent。

如果为 `REQUIRED`，Main Agent 把可执行的人工步骤、`Required Before`、前置条件、预期结果和验证方式写入 `docs/HUMAN_ACTIONS.md`，且不得写入 secret。如果尚未到达 `Required Before`，保持 `PENDING` 并继续前置工作；到达后仍未完成时，把当前 Phase 标记为 `BLOCKED`，将其认定为 `HUMAN_BLOCKER` 并停止。

### 9. 自动继续

完成记录和 checkpoint 尝试后，Main Agent 重新读取实施状态并自动进入下一个未完成 Phase，创建全新的 Phase subagent。除非满足停止条件，否则不要询问用户：

- 是否继续
- 是否开始下一阶段
- 是否执行 Phase N+1

## 停止条件

只允许在以下情况停止：

A. 所有 Phase 均已 PASS 并标记为 `COMPLETE`。
B. 出现 Agent 无法解决的 `HUMAN_BLOCKER`。
C. 设计文档存在互相矛盾且必须由产品决策解决的要求。
D. 下一步必须执行真实资金交易、真实密钥授权或不可逆外部操作。

对 B、C 或 D，记录当前 Phase、已完成工作、验证证据、准确阻塞点和恢复条件。仅提出解除阻塞所必需的问题；不要把常规阶段推进包装成确认请求。不得执行真实资金交易、索取或使用真实密钥授权，也不得擅自执行不可逆外部操作。

Phase 11 的 24 小时 dry-run 必须由真实连续运行时长和报告验证，不得缩短、模拟或伪造通过证据。只有 H-001、H-002 等 `Required Before` 事项已有不含 secret 的完成证据时，才能把 Phase 12 标记为 `IN_PROGRESS`。进入 Phase 12 后，Agent 只能完成不需要真实密钥授权、真实资金交易或不可逆外部操作的代码、自动测试和 preflight；任何需要这些能力的 preflight 也交由获授权的人执行。真实 mainnet canary、signer 授权和资金操作必须作为 Human Action，由获授权的人执行；Agent 在需要该操作时按 B 或 D 停止。收到不含 secret 的完成证据后，重新读取状态、验证报告并恢复执行。

## 最终收尾

所有 Phase PASS 后，Main Agent 生成或更新 `docs/FINAL_REPORT.md`，至少包含：

- 完成阶段
- 测试结果
- 已知限制
- 未解决问题
- 后续建议

根据最终文档状态执行最后一次一致性检查，确认实施计划、执行状态、Human Actions 和最终报告互相一致，然后报告完成。
