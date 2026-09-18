# HarnessFlow-CC

面向 Claude Code 的三阶段 AI 开发流程编排。是 `AiRunner` / `AiRunnerV3` / `Skills/quant-orchestrator`
三套 Codex 方案的原生移植：保留它们的核心不变量，但把 Scheduler、AgentPool、WorkspaceManager
这些 Python 模块换成 Claude Code 自带的原语（subagent 定义、`Agent` 工具并行调用、hooks）。

## 三个阶段

| 阶段 | 入口 | 产出 | 上下文 |
| --- | --- | --- | --- |
| 1. 设计 | `/hf-design` | `01_DESIGN.md`（含 `00_REQUIREMENTS.md`） | 与人交互，主会话 |
| 2. 规划 | `/hf-plan` | `02_IMPLEMENTATION_PLAN.md` + `03_TASKS.json` | 主会话 + 只读探索子代理 |
| 3. 执行 | `/hf-run` | 代码 + 各阶段交付文档 + `04_STATE.md` | 每阶段一个独立子代理上下文，批内并行 |

阶段 3 不带参数就是全自动，一路跑完所有阶段。上下文不会随阶段数变糊——每个阶段整体交给
一个 `hf-phase-orchestrator` 子代理，主会话只累积一页摘要：

```
主会话                        ← 只有各阶段摘要
  ├── phase-orchestrator P01  ← 独立上下文
  │     ├── task-worker ×3    ← 同一消息发出，真并行
  │     └── verifier          ← 独立重跑 verify
  ├── phase-orchestrator P02  ← 全新上下文
  └── ...
```

## 与三套 Codex 方案的对应关系

| Codex 侧 | HarnessFlow-CC 侧 |
| --- | --- |
| `ai_runner.py` 主循环 | `/hf-run` 命令 + 主会话作为唯一 orchestrator |
| `scheduler.py` DAG / ready tasks | `03_TASKS.json` 的 `batch` 字段，规划阶段预计算 |
| `agent_pool.py` 角色路由 | `.claude/agents/hf-*.md`，`agent_type` → 子代理定义 |
| `workspace_manager.py` worktree | 同工作树 + `allowed_paths` 路径分区 + hook 拦截 |
| `merge_controller.py` | 不需要（批内路径不相交，无合并） |
| Runner 独立 verify | `hf-verifier` 子代理 + hook，Agent 不能自判完成 |
| `codex.model` 单一模型 | 每阶段/每任务双档模型推荐（primary / economy） |
| quant-orchestrator 的 Phase subagent | `hf-phase-orchestrator`，一阶段一实例，嵌套派 worker |
| `multi_agent.parallel_limit` | 批内并发上限 4 + `budget.json` 的每阶段 worker 派发上限 |

## 安装

```bash
cd /path/to/your-project
bash /path/to/HarnessFlow-CC/install.sh .
```

复制文件 + 检查 hook 注册 + 5 项自检确认守卫真的在拦。不覆盖目标仓库已有文件；
已有 `settings.json` 时会提示手工追加 hook 那一项。

不要手工 `cp`——目标缺 `docs/` 目录时 `cp -r src/docs/harnessflow docs/` 会静默把源目录
重命名成 `docs`，路径全错且不报错。

```
/hf-design <目标>   # 交互产出需求书+设计书，人工批准后进入下一步
/hf-plan            # 产出分阶段实施书 + 任务图，人工批准
/hf-run             # 从第一个未完成阶段开始执行
/hf-run P03         # 只跑指定阶段（推荐每阶段开新会话）
/hf-status          # 只读进度报告，不执行
```

完整走一遍的操作细节、每步你要检查什么、阻塞怎么处理：**[USAGE.md](USAGE.md)**。

## 硬约束落在哪里

Agent 的自我评估只是建议。真正的判定来自三处，都不依赖模型自觉：

1. **`.claude/hooks/hf_scope_guard.py`**（PreToolUse）：拦截当前批次 `allowed_globs` 之外的写入，
   拦截对任务图 / 状态文件 / `.git` 的直接改写，拦截 `git push`、`reset --hard`、历史重写。
2. **`hf-verifier` 子代理**：只读 + Bash，用 `git diff --name-only` 逐任务核对越界，
   独立重跑 `verify` 命令，逐条判定验收标准。
3. **`/hf-run` 的阶段闸门**：verifier 返回 PASS 才写 `04_STATE.md`、才提交、才进入下一阶段。

hook 是粗粒度（批次并集），verifier 是细粒度（逐任务归属）。两者职责不同，都需要。

## 模型档位

每个阶段给 `primary` / `economy` 两档，每个任务落一个实际档位，由 `Agent` 工具的
`model` 参数传入。选档规则在 skill 里，摘要：

| 档位 | 适用 |
| --- | --- |
| `opus` | 架构决策、并发/状态机/协议、安全边界、跨模块重构、根因不明的调试、独立验证 |
| `sonnet` | 明确规格下的常规实现、单模块 CRUD、有先例的重构 |
| `haiku` | 样板代码、机械改名、配置文件、测试骨架、只读信息收集 |

同一阶段内可混档：接口定义 `opus`，按接口填实现 `sonnet`，测试骨架 `haiku`。
验证方（`hf-verifier`）固定 `opus`，不随 economy 降档——判定环节降档等于放弃闸门意义。

## 前置条件

- Git 仓库，已配置提交用户名和邮箱。
- Python 3.10+（仅 hook 脚本使用，编排层不需要）。
- 目标项目自身的构建与测试工具可用。

### 第三方中转（GLM 等）

端点只有一个模型可用时，切到单模型模式：

```bash
mkdir -p .git/harnessflow
echo '{"mode":"single_model"}' > .git/harnessflow/models.json
```

它改三件事：不给 `Agent` 工具传 `model` 参数（`opus`/`sonnet`/`haiku` 是 Claude Code
内部别名，对着 Anthropic 目录解析，中转下不可靠）、修复重试不再"上调一档"（没有更高档，
改的是信息量）、验证方与实现方同模型所以要求 `verify` 更硬。规则见
`.claude/skills/harnessflow/MODELS.md`。

任务图里的 `model` 字段照旧保留——它记录"这个任务需要多强的模型"，换回官方端点直接生效。

## 测试

```bash
cd HarnessFlow-CC/tests && python test_scope_guard.py -v
```

28 个用例，只依赖 Python 标准库和 git，在临时仓库里跑。覆盖 glob 语义
（`**` 跨目录 / `*` 不跨 `/` / 前缀相似路径不误匹配）、受保护路径、仓库外逃逸、
危险命令拦截、畸形事件不误伤。

任务图与 `verify` 命令等同于受信任的项目配置。不要执行来源不可信的任务图。

## 目录

```text
.claude/
├── skills/harnessflow/SKILL.md     # 共享不变量与数据契约
├── commands/hf-design.md           # 阶段 1
├── commands/hf-plan.md             # 阶段 2
├── commands/hf-run.md              # 阶段 3
├── commands/hf-status.md           # 只读进度
├── agents/hf-phase-orchestrator.md # 单阶段编排器    opus  ← 第 1 层
├── agents/hf-phase-lead.md         # 跨模块判断任务  opus
├── agents/hf-task-worker.md        # 并行实现 worker  sonnet
├── agents/hf-test-worker.md        # 测试/样板 worker haiku
├── agents/hf-verifier.md           # 独立验证        opus
├── agents/hf-explorer.md           # 只读探索        haiku
├── hooks/hf_guard.sh               # 解析可用 Python，无则 fail-closed
├── hooks/hf_scope_guard.py         # 范围与危险命令拦截
└── settings.json                   # hook 注册 + HF_PYTHON

docs/harnessflow/
├── 00_REQUIREMENTS.md
├── 01_DESIGN.md
├── 02_IMPLEMENTATION_PLAN.md
├── 03_TASKS.json
├── 04_STATE.md
├── deliverables/                   # 每阶段交付文档
└── handoffs/                       # 人工门交接文件
```
