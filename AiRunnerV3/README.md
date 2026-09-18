# HarnessFlow

HarnessFlow 是一个可拷贝到任意 Git 项目的 Codex 自动化开发流水线。它把已经批准的需求、设计和分阶段任务图交给 Codex，逐项实施、独立校验、限制改动范围，并在通过后记录 Git 提交。

当前版本刻意只支持 Codex CLI，不抽象其他 AI 提供商。这样保留原项目 `ai_runner.py` 的执行方式，同时提供 opt-in 的 `multi_runner.py` 编排入口；项目路径、提示词、任务图、校验命令和运行参数移出代码，成为可移植配置。

## 前置条件

- Python 3.10 或更高版本，仅使用标准库。
- Git，且目标目录已经是 Git 仓库并配置了提交用户名和邮箱。
- 已安装并登录 Codex CLI，终端中可以运行 `codex exec --help`。
- 目标项目自身的构建和测试工具已经安装。

HarnessFlow 会调用任务里的 `verify` 命令，并可自动创建 Git 提交。任务文件等同于受信任的项目配置，不应执行来自不可信来源的任务图。

## 安装到项目

将整个 `harnessflow` 目录复制到目标 Git 仓库根目录，保留内部目录结构：

```text
your-project/
├── harnessflow/
│   ├── ai_runner.py
│   ├── harnessflow.json
│   ├── prompts/
│   ├── schemas/
│   └── templates/
└── ...
```

在目标仓库根目录运行：

```bash
python harnessflow/ai_runner.py --init
```

也可以进入该目录，使用用户期望的短命令：

```bash
cd harnessflow
python ai_runner.py --init
python ai_runner.py
```

只要 `harnessflow` 是目标 Git 仓库内的普通目录，Runner 会自动找到上级仓库根目录。

命令会创建 `docs/harnessflow/` 下的需求、设计、实施计划、任务图、执行状态和人工交接模板。初始化不会覆盖已有文件；只有明确使用 `--force` 才会替换这些生成文件。

完成并审核文档后，先提交初始基线：

```bash
python harnessflow/ai_runner.py --validate
git add harnessflow docs/harnessflow
git commit -m "chore: initialize HarnessFlow"
python harnessflow/ai_runner.py
```

也可以在 `harnessflow` 独立仓库目录内运行，并用 `--repo` 指向目标项目：

```bash
python ai_runner.py --repo D:/path/to/your-project --init
```

## 四阶段流程

### 1. 初始需求

编辑 `00_REQUIREMENTS.md`，写清背景、目标、非目标、可观察的功能行为、质量约束、失败语义和验收场景。需求应描述“系统必须表现为什么”，不要提前指定无必要的实现细节。

进入下一步前需要做到：

- 每项需求有稳定编号和可验证结果。
- 边界、异常和缺失数据的行为明确。
- 性能、安全、兼容性和运维要求按项目风险补齐。
- 会实质改变方案的问题已经由负责人决定，并把状态改为 `Approved`。

### 2. 设计书

编辑 `01_DESIGN.md`，把已批准需求映射到模块、接口、状态变化和数据流。记录现有代码证据、关键不变量、迁移与回滚、安全边界、验证策略和重要取舍。

进入下一步前需要做到：

- 每条需求能追溯到设计组件。
- 外部契约、内部接口和错误语义没有关键空白。
- 数据迁移、兼容和回滚条件明确。
- 验证策略足以证明设计成立，并由负责人批准。

### 3. 分阶段实施书

同时编辑 `02_IMPLEMENTATION_PLAN.md` 和 `03_TASKS.json`。Markdown 说明阶段目标和完成定义；JSON 是 Runner 实际读取的依赖图。JSON 中的每个任务 ID 必须在实施计划里恰好出现一次，格式为 `### Task <ID>:`。

任务应足够小，能在一次独立 Codex 上下文中完成并验证。每项任务至少包含：

- `id`：稳定且唯一的任务 ID。
- `execution_mode`：`auto` 或 `human_gate`。
- `agent_type`：`coding`、`testing`、`review` 或 `research`，用于 Agent Pool 角色路由。
- `execution_mode`：新任务可用 `serial`、`parallel` 或 `human_gate`；旧 `auto` 继续兼容。
- `workspace`：默认 `isolated`，多 Agent 任务必须使用隔离 worktree。
- `status`：初始为 `todo`。
- `goal`：单一、可观察的目标。
- `depends_on`：必须先完成的任务 ID。
- `context_queries`：建议 Codex 先执行的聚焦搜索。
- `read_first`：必须优先阅读的项目文件。
- `allowed_paths`：本任务允许修改的仓库相对路径或 glob。
- `expected_outputs` 和 `acceptance`：产物与可观察验收条件。
- `verify`：至少一个非交互验证命令。

`allowed_paths` 不需要列出任务图和状态文件，Runner 会自动管理它们；`human_gate` 的交接文件也会自动纳入范围。依赖图不能有缺失 ID 或循环依赖。

### 4. 实施

运行：

```bash
python harnessflow/ai_runner.py
```

Runner 按实施计划顺序选择依赖已完成的 `todo` 任务，然后：

1. 要求干净的 Git 工作区并记录当前任务。
2. 用一次隔离的 `codex exec --ephemeral` 上下文实施任务。
3. 拒绝 Codex 创建提交或修改 Git 历史。
4. 检查所有改动是否落在任务允许路径内。
5. 独立执行 `verify` 命令，并确认校验过程未改变 Git HEAD 或越界写文件。
6. 失败时把当前 diff 和错误摘要交给新的 Codex 上下文修复，次数由配置决定。
7. 成功后更新任务状态，创建实现提交和验证状态提交。

运行日志和临时上下文位于目标仓库的 Git 元数据目录 `.git/harnessflow/`，不会污染工作树。临时上下文在每次调用后删除，日志保留用于追溯。日志可能包含提示词、命令输出和失败修复时的代码 diff；分享日志前应按项目的数据安全要求检查和脱敏。

## 常用命令

```bash
# 只校验配置、任务字段、依赖图和实施计划映射
python harnessflow/ai_runner.py --validate

# 查看任务统计和当前可执行任务
python harnessflow/ai_runner.py --status

# 预览下一个任务，不修改文件、不启动 Codex
python harnessflow/ai_runner.py --dry-run

# 只运行一个已就绪任务
python harnessflow/ai_runner.py --task P01-T01

# 本次最多完成两个自动任务
python harnessflow/ai_runner.py --max-tasks 2

# 恢复状态文件记录的中断或 blocked 任务
python harnessflow/ai_runner.py --continue

# 按依赖图并行运行独立 worktree，冲突自动暂停到 HUMAN_BLOCKER
python harnessflow/multi_runner.py --max-parallel 3

# 只查看多 Agent 当前 ready tasks
python harnessflow/multi_runner.py --dry-run
```

普通执行要求工作区干净，避免覆盖人的未提交改动。只有在确认现有改动属于记录中的当前任务时才使用 `--continue`；Runner 仍会拒绝允许范围之外的文件。

## 人工确认任务

将需要产品判断、安全复核、迁移确认或真实环境证据的任务设置为 `human_gate`。Runner 仍会先实施并运行所有命令式校验，然后生成一个准备提交并暂停，返回码为 `2`。

人工审核步骤：

1. 检查实现、自动校验结果和 `docs/harnessflow/handoffs/<TASK_ID>.md`。
2. 执行任务中不能自动完成的人工检查。
3. 仅在真实通过后把交接文件中唯一的 `Status` 改为 `Accepted`。
4. 不要修改其他文件，然后运行：

```bash
python harnessflow/ai_runner.py --accept P02-T03
```

Runner 会确认 HEAD 仍是准备提交、除交接文件外没有新改动，再把任务标记为完成并提交审核记录。

## 配置

`harnessflow.json` 的路径相对于目标仓库，资源文件路径相对于该配置文件所在目录。常用配置：

- `paths`：需求、设计、计划、任务、状态和交接目录。
- `codex.command`：Codex 可执行命令，默认 `["codex"]`。
- `codex.exec_args`：附加给 `codex exec` 的参数。
- `codex.sandbox`：`read-only`、`workspace-write` 或 `danger-full-access`。通常保持 `workspace-write`。
- `codex.model`：可选模型；`null` 使用本机 Codex 默认值。
- `runner.max_repair_attempts`：首次失败后的全新上下文修复次数，范围 `0..10`。
- `runner.auto_commit`：通过后是否自动提交。`human_gate` 要求为 `true`。
- `runner.verify_command_prefixes`：允许识别为自动校验的命令前缀。
- `multi_agent.parallel_limit`：多 Agent 默认最大并发数；命令行 `--max-parallel` 可覆盖。
- `multi_agent.workspace_root` / `log_root`：隔离 worktree 和 Agent 日志目录。

如需使用其他配置文件：

```bash
python harnessflow/ai_runner.py --config harnessflow/custom.json --validate
```

配置文件和提示词是通用行为的扩展点；项目特有事实应写入项目文档和任务图，而不是写回 `ai_runner.py`。

## 失败与恢复

验证持续失败、越界修改、Codex 改写 Git 历史或提交失败时，任务会变为 `blocked`，状态文件记录原因，Runner 返回非零状态。先检查 `.git/harnessflow/logs/`，修正任务定义、环境或当前实现后再运行 `--continue`。

若 `auto_commit=false`，Runner 会在验证成功后留下未提交改动并停止，需人工检查和提交后才能继续下一个任务。

## 独立发布文件

发布为单独 Git 项目时，至少保留以下文件：

```text
ai_runner.py
harnessflow.json
prompts/task_prompt.md
schemas/task_result.schema.json
schemas/tasks.schema.json
templates/*.md
templates/03_TASKS.json
README.md
LICENSE
```

## 开发与测试

```bash
python -m unittest discover -s harnessflow/tests -v
```

测试只依赖 Python 和 Git，并在临时仓库中模拟 Codex CLI，验证初始化、配置校验、范围控制、任务执行和自动提交。
