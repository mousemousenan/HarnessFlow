# HarnessFlow 优化方案 — 长会话中断的检测、止损与恢复

Status: Applied（2026-09-18 用户批准后落地；O3 → O2 → O1 已写入对应文件，
待下一次 /hf-run 按第 6 节判据验证）
日期：2026-09-18
作者：/hf-run 主会话（P06 恢复过程中形成）
证据来源：P06 阶段 2026-09-17 ～ 09-18 的六次尝试实录（`04_STATE.md` 执行历史与阻塞记录）

---

## 1. 问题定义

### 1.1 实录：P06 六次尝试

| # | 时间 | 现象 | 中断到发现耗时 | 损失 |
| --- | --- | --- | --- | --- |
| 1 | 09-17 | provider temporarily unavailable，编排器 86 分钟后被终止 | 立即（报错） | 无产物落盘 |
| 2 | 09-17 | 同上，103 分钟后被终止 | 立即（报错） | B1 产物已落盘存活 |
| 3 | 09-17 | 空流（StreamNoEventsError），起步即终止 | 立即（报错） | 无改动 |
| 4 | 09-18 | ENOTFOUND，起步即终止 | 立即（报错） | 无改动 |
| 5 | 09-18 | **API 连接挂起（无报错、无超时）**，实例存活但零活动 | **约 3 小时（人工发现）** | 实现已完成，仅收尾停滞 |
| 6 | 09-18 | 收尾重派（用户确认），正常完成 | — | — |

### 1.2 根因与放大器的区分

- **根因（hf-run 管不了）**：GLM 中转端不稳定——provider unavailable、空流、ENOTFOUND、连接挂起。这是基础设施问题，换编排方案无效。
- **放大器（hf-run 设计可补）**：
  1. 中断 #5 暴露：运行时对「连接挂起」无超时，实例无限等待 → **没有停滞检测**，靠人等 4 小时发现。
  2. 确定性验证（pytest 重跑）也走 agent API 往返 → 每次多轮 API 调用都是一次中转故障的暴露机会。
  3. 每次恢复都要主会话人工考古（盘点盘面产物、推断进度、手写恢复简报）→ 恢复成本高且易漏。

本方案只解决放大器，不承诺解决根因。目标：**挂掉之后 ≤20 分钟自动发现，损失收敛到分钟级，恢复不需要考古。**

---

## 2. 优化项 O1 — 主会话停滞看门狗

**改动位置**：`.claude/skills/harnessflow/SKILL.md`（主会话职责节，§3.2 与 §3.3 之间新增小节）

**现状缺口**：hf-run 的预算只有 token 维度（worker 数 / 修复次数），没有时间维度。实例卡死时没有任何机制触发检查。

**规则草案**（写入 SKILL.md）：

```
### 3.2b 派发后看门狗

派出 phase-orchestrator 后，主会话安排周期唤醒（建议 20 分钟，Session 级即可）。
每次唤醒只做只读活性检查，全部满足才算「健康」：

1. 实例仍在运行（后台任务状态非 failed/killed）；
2. 盘面有活动迹象之一（近 20 分钟内有文件改动、或有 pytest/python 子进程在跑）：
   - 检查对象：.git/harnessflow/、.git/harnessflow/phase_ledger.jsonl、
     本阶段 allowed_paths 涉及目录、docs/harnessflow/deliverables/；
3. phase_ledger.jsonl 的最新心跳时间戳距今 ≤ 40 分钟（O3 落地后启用本条）。

判定：
- 连续 2 轮（约 40 分钟）不健康 → 视为实例卡死：
  TaskStop 终止 → 清理 active_scope.json 残留 → 按 §3.3 恢复规则重派，
  恢复简报只需转写 phase_ledger.jsonl 的最后状态（O3）。
- 健康 → 不打扰，继续等下一个唤醒点。
- 收到正常完成通知 → 删除看门狗任务。

看门狗的终止与重派同样计入阶段级重派计数，不因「卡死」豁免。
```

**实现注记**：主会话用 ScheduleWakeup（/loop dynamic）或 CronCreate（session 级、20 分钟间隔、错开整分）实现周期唤醒；不新增基础设施。

**权衡**：
- 收益：#5 类故障的发现时间从 3 小时+ → ≤40 分钟，且无需人在场。
- 风险：误杀「长时跑测试但磁盘无改动」的实例 → 用「有活跃子进程」作为豁免条件（pytest 运行时必然有 python 进程）。
- 成本：每 20 分钟一次极轻量检查，token 开销可忽略。

---

## 3. 优化项 O2 — 确定性 verify 直跑（单模型模式补偿）

**改动位置**：`.claude/skills/harnessflow/MODELS.md`（单模型补偿规则新增一条）

**现状缺口**：`pytest tests -q` 这类确定性命令（实测 ~160 秒、exit code 即结论）被派给 hf-verifier 经多轮 API 调用「重跑并转述」。验证链路上每一次 API 往返都是中转故障的暴露点；agent 转述还引入「转述失真」风险。

**规则草案**（写入 MODELS.md）：

```
单模型补偿之四 —— 确定性验证直跑：

verify 数组中不依赖模型判断的确定性命令（pytest、lint、typecheck、build、
脚本 exit code 类），编排器可直接用 Bash 重跑并留存原始输出到
.git/harnessflow/verify-logs/<任务ID>.log，以 exit code + 日志路径作为证据，
不必派 hf-verifier 转述。

hf-verifier 保留给需要判断力的部分：
- acceptance 逐条判定（哪些证据支持哪条验收，需要对照设计书裁量）；
- expected_outputs 的内容抽查（不是存在性——存在性用 ls 即可）；
- 改动范围归属核对中「边界文件属于哪个任务」的裁量。

判定原则：命令能吐出客观 pass/fail 的，不消耗 agent 会话；
需要「对照文本裁量」的，必须独立验证方。
```

**权衡**：
- 收益：P06-B1 这类收尾批次少一整条 agent 链路（验证时长从 agent 会话的不可控 → ~3 分钟命令）；API 故障暴露面减半。
- 风险：编排器「既当运动员又当裁判」→ 不变量 2（Agent 不能自我宣布完成）要求判定环节独立。缓解：**命令执行可以直跑，但 acceptance 判定仍必须派 hf-verifier**——直跑的只是「取证」，不是「判定」。此条规则文本已把这一点写成硬边界。
- 前提：verify 命令本身必须是确定性的。任务图契约已要求 verify 为「非交互验证命令」，成立。

---

## 4. 优化项 O3 — phase_ledger 心跳与机械恢复

**改动位置**：
- `.claude/agents/hf-phase-orchestrator.md`（定义中追加心跳义务）
- `.claude/skills/harnessflow/SKILL.md`（§3.3 复核与 §4 中断处理引用该文件）

**现状缺口**：中断后主会话只能靠「读 04_STATE.md + git status + 盘面 mtime 考古」推断进度，再手写恢复简报。P06 第 5 次恢复时这套考古花了可观的只读核查。且看门狗（O1）没有区分「慢」和「死」的信号源。

**规则草案**：

```
编排器心跳义务（写入 agent 定义）：

编排器在自己的上下文里，每完成一个显著步骤，向
.git/harnessflow/phase_ledger.jsonl 追加一行 JSON：

  {"ts": "<ISO时间>", "phase": "P06", "batch": "P06-B1", "step": "<步骤>",
   "detail": "<一行说明，含关键产物路径>"}

显著步骤枚举（最低要求，允许更细）：
  scope_written / worker_dispatched(<任务ID>) / worker_returned(<任务ID>, PASS|FAIL)
  / verifier_dispatched / verify_command_done(<命令>, exit <码>)
  / deliverable_written / scope_cleared / phase_summary_ready

规则：
- 只追加不重写；单行 ≤ 500 字符；不写大段日志（日志放产物文件，这里给路径）。
- 该文件不属于任何任务的 allowed_paths 约束（基础设施文件，与 active_scope.json 同类）。
- 主会话恢复时：读本文件最后 N 行即可精确知道中断点，恢复简报改为机械转写，
  不再考古盘面 mtime。
- 看门狗（O1）以此文件的最新 ts 作为活性信号之一。
```

**权衡**：
- 收益：恢复从「人工考古 + 手写简报」变成「读台账 + 转写」；看门狗获得廉价活性信号。
- 风险：编排器忘记写心跳 → 把「心跳义务未履行」列为主会话复核摘要的检查项（§3.3 追加：`phase_ledger.jsonl 是否与摘要叙述一致`），首次违例记入 LESSONS，不直接判失败。
- 成本：每步骤一次文件追加，可忽略。

---

## 5. 明确不做的事

- **不解决中转端不稳定本身**。那是基础设施问题；可选的用户侧缓解是换官方端点或更稳的中转，不属于 harnessflow 范围。
- **不给 worker 加看门狗**。worker 单任务上下文小、生命周期短，卡死概率与损失都远小于编排器；预算机制已兜底。
- **不让主会话接管实现**。看门狗只做「杀 + 清 + 重派」，恢复仍走全新编排器；上下文隔离不变量不动。
- **不改任务图契约与 allowed_paths 机制**。`phase_ledger.jsonl` 与 `verify-logs/` 作为基础设施豁免路径，白名单仅此两项。

---

## 6. 实施顺序

| 步骤 | 内容 | 前置 |
| --- | --- | --- |
| 1 | O3 心跳协议写入 orchestrator 定义 + SKILL.md（最便宜、被 O1 依赖，先落） | 无（当前 P06-B1 已收尾） |
| 2 | O2 直跑规则写入 MODELS.md | 无 |
| 3 | O1 看门狗写入 SKILL.md（依赖 O3 的心跳信号） | 步骤 1 |
| 4 | 验证：下一次 /hf-run 观察一个完整阶段（建议 P06-B2/T02），核对心跳行完整性、看门狗唤醒是否干扰正常执行、直跑日志留存 | 步骤 1-3 |

**验证通过的判据**：一个阶段完整跑完且 (a) `phase_ledger.jsonl` 每个显著步骤有心跳行；(b) 主会话恢复简报（若有中断）完全由台账转写生成，未做盘面考古；(c) 确定性 verify 有日志留存且 hf-verifier 仅做 acceptance 判定；(d) 看门狗未误杀健康实例。

---

## 7. 与现有契约的关系

- 五条核心不变量全部不受影响；O2 显式强化了不变量 2（判定独立）。
- 预算机制不变；O1 的重派计入既有重派计数。
- 返回契约不变；`WORKER_SPAWNS` 之外不新增摘要字段（心跳核对在主会话侧做，不进摘要）。
- 本文档是对 **流程工具** 的优化，不是产品阶段，不改 `00_REQUIREMENTS.md` / `01_DESIGN.md` / `02_IMPLEMENTATION_PLAN.md` / `03_TASKS.json`。落地改动仅为 `.claude/skills/harnessflow/` 与 `.claude/agents/` 下文件。
