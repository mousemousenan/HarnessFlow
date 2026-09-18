# OPT 长会话中断优化 — 验证记录

记录日期：2026-09-18  
实施目录：`D:\vibecoding\harnessflow\HarnessFlow-CC`  
依据：`docs/OPTIMIZATION_IMPLEMENTATION.md`

## 实施基线 / 目标文件差异

- Git 根是父仓库，不是本项目目录。HEAD：`d8346c8359b4d3cb332b654ddc856be73c1704eb`（`main`）。
- 开工时工作区已有未提交文件：`docs/OPTIMIZATION_IMPLEMENTATION.md`、`docs/OPTIMIZATION_PROPOSAL.md`。本轮保留它们，未改源提案、产品需求书、设计书、实施书或任务图。
- 解释器：`C:\Users\saisn\miniconda3\python.exe`（Conda `base`，Python 3.13.5）。
- 回归：`python -m unittest discover -s tests -p "test_scope_guard.py" -v` → 28 tests OK（约 9s）。
- 五个目标文件本轮差异（`git diff --stat`）：348 insertions, 41 deletions。

| 文件 | 本轮要点 |
| --- | --- |
| `.claude/skills/harnessflow/SKILL.md` | 不变量 2 区分取证/判定；台账与验证日志契约；恢复顺序；看门狗共享判定 |
| `.claude/skills/harnessflow/MODELS.md` | 第 5 条：`single_model` 确定性 verify 直跑取证 |
| `.claude/agents/hf-phase-orchestrator.md` | 单写者心跳、直跑取证、verifier 证据包、预算延续 |
| `.claude/agents/hf-verifier.md` | 单模型读原始日志；保留全部实质判定；Sensor exit 0 不等于通过 |
| `.claude/commands/hf-run.md` | 派发记录、§3.2b 看门狗、台账复核、机械恢复与重派计数 |

未改 hook / 安装器 / 命令体系。未把 `ScheduleWakeup`、`CronCreate`、`TaskStop` 写入 `allowed-tools`。

## 测试项目 / 模式 / 阶段 / 宿主版本 / 实际可用工具

- 测试项目：`C:\Users\saisn\AppData\Local\Temp\hf-opt-validation-20260918`（独立 `git init`，避免写入父仓库 `.git/`）。摘录见 `test-project-excerpt.txt`。
- 模式：规则按 `single_model` 与 `multi_tier` 双路径写入；本宿主未启动 `/hf-run`。
- 阶段：受控样例使用虚构 `P01`，不是产品任务图中的真实阶段。
- 宿主：Codex CLI 编码会话，不是 Claude Code `/hf-run` 会话。
- 本会话可用：文件读写、Bash/Python、现有 unittest。
- 本会话不可用、因此未写入命令工具表：Claude Code 的会话级定时唤醒、后台任务状态查询、停止与取消定时任务。源提案候选名 `ScheduleWakeup` / `CronCreate` / `TaskStop` 未在本宿主实测，不能假定可用。
- 本轮未创建定时任务，未停止任何现存代理，未对用户现有会话做终止。

## 验收分项

| 分项 | 结果 | 说明 |
| --- | --- | --- |
| 规则已写入 | PASS | 五个目标文件已按 O3→O2→O1 补齐，交叉表述一致 |
| 完整阶段通过 | NOT_RUN | 需要 Claude Code 会话执行 `/hf-run` |
| 异常恢复通过 | 部分 | 受控样例覆盖台账/日志/Sensor 判定；活体中断与看门狗停止未跑 |
| 时延目标达成 | NOT_RUN / 未达成保证 | 规则采用 20 分钟轮询 + 连续两轮不健康；不保证源提案 ≤20 分钟发现。见 §2.2 |

**没有满足原始 ≤20 分钟目标，不写「源提案全部目标已达成」。**

## 用例编号 / 结果 / 实际步骤

命令：`python docs/optimization-evidence/ledger_protocol_check.py`  
工作目录：`D:\vibecoding\harnessflow\HarnessFlow-CC`  
退出码：0  
日志：`docs/optimization-evidence/protocol_check_output.txt`

| 编号 | 结果 | 实际步骤 |
| --- | --- | --- |
| V01 | NOT_RUN | 无 Claude Code `/hf-run` 完整阶段 |
| V02 | NOT_RUN | 无多模型宿主实跑。规则保留 `multi_tier` 原路径 |
| V03 | NOT_RUN | 无超过 40 分钟的真实验证命令。规则要求编排器续报，进程存在不豁免心跳 |
| V04 | NOT_RUN | 无活体编排器可停。规则要求连续两轮不健康后停止并重派 |
| V05 | NOT_RUN | 无跨项目进程对照。规则禁止把其他项目 Python 进程当成本实例活动 |
| V06 | NOT_RUN | 未做真实 20 分钟唤醒。边界规则：20/40 分钟恰好等于边界按健康；不可用缩短时间冒充唤醒证据 |
| V07 | NOT_RUN | 无真实完成/人工门/旧回调。规则要求终态取消看门狗，人工门不代签 |
| V08 | NOT_RUN | 无真实停止失败。规则：停止失败不删 scope、不启动第二写入者 |
| V09 | NOT_RUN | 无混合重派实跑。规则：阶段重派共用上限 2，预算延续 |
| V10 | PASS | 受控台账：缺失/空文件/截断尾行/缺时区/未来时间/旧阶段。不伪造进度；残行隔离后 `phase_started` 可解析 |
| V11 | PASS（规则+样例） | 健康台账可重建「已独立验证」；V10 在只有 `phase_started`/`scope_written` 时不把任务标完成。活体「产物已写事件未写」未跑 |
| V12 | PASS | 多样例日志追加三段命令（含预期非零 exit 2 与重试），不覆盖旧证据 |
| V13 | PASS | 无 `end`/`exit` 的开放日志不得算命令完成 |
| V14 | PASS | `sensor-report-P01-B1.json` 含 `fail`；`run-sensors.py` 源码在写出报告后固定 `return 0`。空壳文件 `empty_shell.py` 视为不合格产物 |
| V15 | PASS（能力限制已记录） | 本宿主无定时/停止能力。O1 记为未启用，不能把静态规则检查记为运行通过 |

## 台账实例边界 / 事件完整性 / verifier 结论位置

- 健康样例边界：`phase_started attempt=1 task=orch-A`；必要事件齐全；`verifier_returned` 指向 `.git/harnessflow/verify-logs/P01-T01.log#verdict`。
- V10 边界：当前阶段最后一次 `phase_started attempt=2`；P00 旧记录、缺时区、未来时间、截断行均不进入当前心跳。
- 退化原因明确写成「台账恢复不可用：文件不存在 / 空文件」，不编造中断点。

## 唤醒时间 / 活动证据 / 心跳年龄 / 连续异常计数 / 实际检测时延

- 未做真实 20 分钟会话唤醒。
- 受控时钟 `2026-09-18T16:00:00+08:00`：健康样例最后心跳年龄 18 分钟（健康）；V10 当前实例 11 分钟（健康，因为非法行被丢弃）。
- 连续异常计数、停止确认、看门狗取消：无运行证据。
- 源提案「挂掉之后 ≤20 分钟自动发现」在本参数下尚未满足；按实施口径，两轮确认的处置时延可到约 60 分钟，且依赖主会话能被唤醒。

## 停止确认 / scope 清理 / 重派与预算 / 定时任务取消证据

无运行证据。规则已写入：确认停止后才清理属于该实例的 `active_scope.json`；不删台账和验证日志；重派计入上限 2；终态取消看门狗。

## 恢复简报 / 是否退化恢复 / 已知限制与未达目标

- 恢复简报格式已写入 `SKILL.md` 与 `hf-run.md`。
- 受控样例中，缺失/空台账走退化恢复；截断台账保留有效行。
- 已知限制：
  1. 本轮宿主不是 Claude Code，O1 定时唤醒与停止能力未启用。
  2. 未跑完整 `/hf-run` 阶段，完整阶段通过与活体异常恢复为未验证。
  3. 长调用若不能返回控制权，防误杀健康长任务的要求未在运行中验证。
  4. 原提案 ≤20 分钟发现目标未达成，且本轮参数下不能声称已达成。
  5. Sensor 仍可能重复跑测试；未宣称 API 暴露面减半。
- 未达目标：O1 运行保护、完整阶段证据、时延目标。

## 回退说明

回退只撤销五个规则文件中的对应修改，保留台账样例与本证据目录。不用 `git reset --hard` 回退。
