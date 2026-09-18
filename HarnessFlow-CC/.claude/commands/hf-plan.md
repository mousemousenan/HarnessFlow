---
description: 阶段 2 — 由设计书产出分阶段实施书与任务图（02_IMPLEMENTATION_PLAN.md + 03_TASKS.json），含并行批次与模型推荐
argument-hint: [可选：只重新规划某个阶段 ID，如 P03]
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(git status:*), Bash(git log:*), Bash(python:*), Agent, AskUserQuestion, Skill
---

先调用 `Skill(harnessflow)` 载入共享契约。本命令的批次划分规则、任务字段、模型档位定义全部以
该 skill 为准，不在这里重复。

范围：`$1`（为空则规划全部阶段）

## 前置检查

读 `docs/harnessflow/00_REQUIREMENTS.md` 与 `01_DESIGN.md`。两者的 `Status` 都必须是
`Approved`；否则停下，告诉用户先批准设计或先跑 `/hf-design`，不要基于草稿规划。

## 步骤

### 1. 摸清代码现状

派 `hf-explorer` 子代理并行调研设计书涉及的每个模块：现有实现在哪、有哪些既有约定、
测试怎么组织、构建与测试命令是什么。这一步的产出决定了 `allowed_paths` 和 `verify` 能不能写准。

必须实际确认项目的构建/测试命令（读 `package.json`、`pyproject.toml`、`Makefile`、
`pom.xml`、`Cargo.toml` 等），不要凭猜写 `verify`。写不出可执行命令的任务，说明调研不够。

### 2. 贯通交互契约

读 `01_DESIGN.md` 的「原型与交互契约」。每个已确认的关键交互都必须落到任务验收条件和
UI 测试场景：优先使用 `tests.ui_interactive`，为每条关键交互声明对应的 REQ-ID、页面状态、
操作反馈和期望结果。加载、空数据、错误状态也要有明确场景，不能只测正常路径。

如果设计契约写 `None`，不要虚构 UI 测试。如果契约信息不足以写成可判定场景，不要擅自
补设计；回到 `/hf-design`。

### 3. 切阶段

按可独立验证的里程碑切分，不按文件切。每个阶段：

- 有一个能独立验证的目标，跑完这个阶段项目处于可工作状态
- 有明确的 `definition_of_done`
- 依赖关系只指向更早的阶段

阶段数量随项目规模走，不硬凑。宁可一个阶段稍大，也不要切出一堆彼此强耦合、
必须来回跳的小阶段。

### 4. 阶段内切并行批次

这是本命令的核心。按 skill 的批次划分规则执行：文件边界 → 契约方向 → 测试同批条件 →
收口串行 → 批内上限 4。

做法：先列出该阶段的全部任务，为每个任务写出它要写入的路径集合，然后按路径相交关系分组。
不相交的进同一 `parallel` 批次，相交的排到不同批次。

写完每个阶段后自查这几件事，不通过就重切：

- 同一 `parallel` 批次内任意两个任务的 `allowed_paths` 是否真的不相交（含 glob 展开后的实际重叠，
  例如 `src/**` 和 `src/api/**` 是相交的）
- 是否有任务的 `depends_on` 指向了同批次内的任务（不允许）
- 共享文件是否被拆到了独立的收口任务里
- 是否为了追求并行度而把一个内聚的改动拆成了互相打补丁的碎片（这是反模式，宁可合并成一个任务）

### 5. 为每个阶段给模型推荐

每个阶段填 `model_recommendation`：`primary`（默认走这档）、`economy`（成本敏感时的降档方案）、
`rationale`（为什么）。依据 skill 的选档规则。`rationale` 要说清这个阶段的判断密度——
需要做取舍的地方多不多、出错的传播面有多大。

然后为每个任务落一个具体的 `model` 档位。同一阶段内不同任务可以不同档：
接口定义用 `opus`，按接口填实现用 `sonnet`，测试骨架用 `haiku`。这比整阶段一档更省也更准。

`review` 类任务（验证）固定 `opus`，不随 economy 降档。

### 5.5 单模型模式：加严 verify

读 `.git/harnessflow/models.json`。`mode` 为 `single_model` 时（第三方中转，只有一个模型），
上面的档位仍然照写进任务图——它记录"这个任务需要多强的模型"，换回官方端点直接生效。
但执行时所有任务跑同一个模型，**验证方和实现方是同一个模型**，"更强模型复核"这一层不存在了。

补偿办法是把闸门做成客观的：

- 每个任务的 `verify` 除了测试，尽量再加类型检查、lint、覆盖率门槛。
  客观命令越多，判定越不依赖判断力。
- `acceptance` 里需要判断的条目（「接口行为正确」「实现合理」）改写成能被命令验证的形式。
  改不了的，把该任务标成 `execution_mode: human_gate` 交给人。
- 阶段批次数超过 4 时考虑拆成两个阶段——中转端点的上下文窗口通常更小。

`multi_tier` 模式下按正常标准写即可。

### 6. 写实施书

写入 `docs/harnessflow/02_IMPLEMENTATION_PLAN.md`。结构：

```markdown
# Implementation Plan

Status: Draft

机器可读依赖图是 `03_TASKS.json`。下面每个阶段 ID 以 `## Phase <ID>:` 出现恰好一次，
每个任务 ID 以 `### Task <ID>:` 出现恰好一次。

## Phase P01: <阶段目标>

- 依赖：<前置阶段 ID，或 none>
- 推荐模型：primary=<档> / economy=<档> — <理由>
- 交付文档：docs/harnessflow/deliverables/P01.md

Definition of Done:
- <可独立验证的完成条件>

并行结构：
- P01-B1 (parallel)：P01-T01、P01-T02
- P01-B2 (serial)：P01-T03

### Task P01-T01: <标题>

- 任务内容：<要做什么，一段话，说清边界>
- 角色/模型：coding / sonnet
- 依赖：none
- 允许路径：`src/foo/**`
- 产出：<文件或产物>
- 测试内容：<要新增或更新哪些测试，覆盖什么>
- 验收标准：
  - <可观察、可判定的条件>
- 验证命令：
  - `<非交互命令>`

## Dependency Notes

说明关键路径决策，以及哪些文件阻止了进一步并行。
```

每个任务的四要素——任务内容、验收标准、测试内容、交付产出——都要写实。
验收标准必须可判定：「性能可接受」不合格，「P95 延迟 < 200ms，用 `bench.py` 测量」合格。

### 7. 写任务图

写入 `docs/harnessflow/03_TASKS.json`，结构与字段严格按 skill 的数据契约。
两份文档必须一致：JSON 里的每个阶段和任务 ID 在 Markdown 里都能找到对应标题。

### 7.5 生成 Test Coverage Matrix

为每个实现任务生成结构化的 `tests` 与 `coverage_matrix`：

1. 从 `00_REQUIREMENTS.md` 提取所有需求 ID（兼容 `REQ-001` 与现有 `R-001` 两种格式）。
2. 规划测试层级：Unit 覆盖函数/类行为，Integration 覆盖模块间交互，E2E 覆盖完整用户流程，UI 交互覆盖已确认的关键交互；每个需求至少有一种测试覆盖。
3. 为每个需求列出 2-5 个关键测试场景，并写入对应测试文件的 `scenarios`。
4. 按覆盖层数计算 `confidence`：3 层为 `high`，2 层为 `medium`，1 层为 `low`。

测试矩阵对象示例如下：

```json
{
  "id": "impl-auth",
  "description": "实现用户认证",
  "tests": {
    "unit": [
      {
        "file": "test/unit/auth.test.js",
        "covers": ["REQ-001", "REQ-002"],
        "scenarios": [
          "validatePassword returns true for correct password",
          "validatePassword returns false for wrong password"
        ]
      }
    ],
    "integration": [
      {
        "file": "test/integration/auth-api.test.js",
        "covers": ["REQ-001", "REQ-003"],
        "scenarios": [
          "POST /api/login with valid credentials returns JWT",
          "POST /api/login locks account after 3 failures"
        ]
      }
    ],
    "e2e": [
      {
        "file": "test/e2e/login-flow.spec.js",
        "covers": ["REQ-001"],
        "scenarios": ["user can login and access protected page"]
      }
    ]
  },
  "coverage_matrix": {
    "REQ-001": {"unit": true, "integration": true, "e2e": true, "confidence": "high"},
    "REQ-002": {"unit": true, "integration": false, "e2e": false, "confidence": "medium"},
    "REQ-003": {"unit": false, "integration": true, "e2e": false, "confidence": "low"}
  }
}
```

生成规则：

- 每个需求 ID 必须出现在至少一个测试的 `covers` 中。
- 如果某个需求只有 low confidence，在 `02_IMPLEMENTATION_PLAN.md` 中标注为风险项。
- 写完任务图后运行 `node scripts/test-coverage-report.js`，报告必须能解析所有需求 ID 并显示覆盖状态；存在未覆盖或 LOW confidence 需求时不要宣称矩阵已完备。

### 8. 结构自检

写完后逐条核对 skill 中的「结构校验规则」，尤其是并行批次内路径不相交这一条。
把自检结果报给用户，格式：

```
阶段数：N   任务数：M   最大批内并发：K
并行批次路径不相交：PASS/FAIL（FAIL 时列出相交的任务对）
ID 唯一性 / 依赖存在性 / 无环：PASS/FAIL
计划与任务图 ID 一一对应：PASS/FAIL
verify 命令均可执行且非交互：PASS/FAIL
测试矩阵需求覆盖与 confidence 一致：PASS/FAIL
交互契约到任务验收与 UI 测试场景已贯通：PASS/FAIL
```

FAIL 项必须修完再交回。

### 9. 交回

给用户一份简表：每阶段的目标、任务数、批次结构、推荐档位、预计并行度。
然后说明：把 `02_IMPLEMENTATION_PLAN.md` 的 `Status` 改为 `Approved` 后运行 `/hf-run`。
建议每个阶段开新会话跑 `/hf-run <阶段ID>`，避免长会话上下文累积。

不要自己把 `Status` 改成 `Approved`。

## 边界

- 不写产品代码。本阶段只产出两份文档。
- 不改 `04_STATE.md`。
- 遇到设计书里的空白，不要在规划阶段擅自补设计。列出来问用户，或标注为需要回到 `/hf-design`。
