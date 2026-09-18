# Implementation Plan

Status: Draft

由 `/hf-plan` 产出。机器可读依赖图是 `03_TASKS.json`。
每个阶段 ID 在本文件中以 `## Phase <ID>:` 出现恰好一次，
每个任务 ID 以 `### Task <ID>:` 出现恰好一次。

## Phase P01: <可独立验证的里程碑>

- 依赖：none
- 推荐模型：primary=opus / economy=sonnet — <这个阶段的判断密度与出错传播面>
- 交付文档：`docs/harnessflow/deliverables/P01.md`

Definition of Done:

- <跑完这个阶段，项目处于什么可验证状态>
- 所有任务通过独立验证
- 交付文档已产出

并行结构：

- `P01-B1` (parallel)：P01-T01、P01-T02 — 路径不相交
- `P01-B2` (serial)：P01-T03 — 收口，改动共享入口文件

### Task P01-T01: <标题>

- 任务内容：<做什么，边界在哪，一段话说清>
- 角色/模型：coding / sonnet
- 依赖：none
- 允许路径：`src/<module>/**`
- 产出：
  - `src/<module>/<file>` — <是什么>
- 测试内容：<新增或更新哪些测试，覆盖哪些行为，含异常路径>
- 验收标准：
  - <可观察、可判定的条件，避免"合理""可接受"这类词>
- 验证命令：
  - `<非交互命令>`

### Task P01-T02: <标题>

- 任务内容：
- 角色/模型：testing / haiku
- 依赖：none
- 允许路径：`tests/<module>/**`
- 产出：
- 测试内容：
- 验收标准：
- 验证命令：

### Task P01-T03: <收口任务>

- 任务内容：<集成、统一导出、跨模块联调这类必须串行的工作>
- 角色/模型：coding / opus
- 依赖：P01-T01、P01-T02
- 允许路径：`src/index.*`
- 产出：
- 测试内容：
- 验收标准：
- 验证命令：

## Dependency Notes

关键路径：<哪条链决定了总时长>

阻止进一步并行的文件：

- `<共享文件>` — 被 <哪些任务> 需要，已收口到 <某个串行任务>
