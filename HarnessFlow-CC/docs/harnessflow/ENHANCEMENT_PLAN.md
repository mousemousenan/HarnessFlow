# HarnessFlow 测试质量增强实施计划

## 文档元信息

- **创建时间**: 2026-09-17
- **方案来源**: 对比 tlc 与 HarnessFlow 改造成本后的推荐方案
- **核心决策**: 保留 HarnessFlow 的并行架构，移植 tlc 的质量增强机制
- **预估工作量**: 5-8 人日
- **改造类型**: 增量改进（向后兼容，低破坏性）

---

## 一、方案背景与决策依据

### 1.1 为什么选择改 HarnessFlow 而不是 tlc

**成本对比**:

| 改造方向 | 核心改动 | 难度 | 风险 | 预估工作量 |
|---------|---------|------|------|-----------|
| **tlc → 加并行** | 重写 Execute 流程支持 parallel 批次<br>改任务图数据结构加 batches<br>加文件路径交叉检查<br>改子代理派发逻辑支持同时启动多个<br>处理并行失败收集与汇总 | 极高 | 架构级重构，tlc 的顺序执行是深入骨髓的设计假设 | **15-20 人日** |
| **HarnessFlow → 加测试质量** | 在任务图加 tests 详细结构<br>写 Test Coverage Matrix 生成逻辑<br>升级 hf-verifier 加 sensor<br>加 EARS 格式模板和校验脚本 | 中等 | 增量改进，HarnessFlow 的架构能容纳这些增强 | **5-8 人日** |

**功能对齐分析**:

你的 5 个核心需求与两个方案的满足难度：

| 需求 | tlc 现状 | 加到 tlc 的难度 | HarnessFlow 现状 | 加到 HF 的难度 |
|-----|---------|----------------|-----------------|---------------|
| 1. 交互设计（需求澄清/设计） | ✅ 已有 | - | ⚠️ 弱 | ⭐ 低（加模板） |
| 2. **阶段内并行** | ❌ 无 | ⭐⭐⭐⭐⭐ 极高 | ✅ 已有 | - |
| 3. 验收/测试/提交 | ✅ 已有且强 | - | ✅ 已有但弱 | ⭐⭐ 中 |
| 4. **任务上下文独立** | ❌ 无 | ⭐⭐⭐⭐ 高 | ✅ 已有 | - |
| 5. 模型分配 | ⚠️ 有但不强制 | ⭐ 低 | ✅ 已有 | - |

**结论**: 
- 你最强调的"阶段内并行"和"任务上下文独立"是架构级能力，HarnessFlow 天生具备，tlc 需要推倒重来
- tlc 的优势（测试质量机制）可以作为"质量增强包"移植到 HarnessFlow
- 改造成本是反向的 **2.5-3 倍**

---

## 二、增强目标

### 2.1 保留 HarnessFlow 的核心优势

✅ **保持不变**:
1. **并行架构**: `hf-phase-orchestrator` 在阶段内调度批次并行 worker
2. **任务隔离**: 每个 `hf-task-worker` 运行在独立上下文，互不干扰
3. **模型分配**: 任务元数据中已有 `recommended_model` 字段
4. **阶段推进**: 通过 `hf-verifier` 独立验证后才推进下一阶段

### 2.2 移植 tlc 的质量机制

🎯 **新增能力**:

| 能力 | 来源 | 当前 HarnessFlow 状态 | 目标状态 |
|-----|------|---------------------|---------|
| **Test Coverage Matrix** | tlc | ❌ 无 | ✅ 在实施书中生成，覆盖所有功能点 |
| **Adequacy Review** | tlc | ❌ 无 | ✅ `hf-verifier` 判断测试充分性 |
| **EARS 需求格式** | tlc | ⚠️ 需求书无标准格式 | ✅ 需求书强制 EARS 模板 |
| **Sensor 机制** | tlc | ❌ 无 | ✅ `hf-verifier` 加 7 类传感器检查 |
| **Lessons Learned** | tlc | ❌ 无 | ✅ 每阶段结束写 LESSONS.md |

---

## 三、灵活流程支持 (新增)

### 3.0 问题：当前的硬性阶段依赖

**当前限制**（来自 `harnessflow/SKILL.md` 第 26-39 行）：

```
需求 Approved ──► 设计 Approved ──► 实施书 Approved ──► 执行

上游文档的 `Status` 不是 `Approved` 时，不进入下游阶段。
```

**问题**：
- 简单任务也必须走完整的三阶段流程
- 无法跳过 design 直接生成 plan
- 无法快速原型验证（prototype-first 模式）

### 3.1 解决方案：三种流程模式

支持用户根据任务复杂度选择流程：

| 模式 | 适用场景 | 阶段 | 命令 |
|-----|---------|------|------|
| **完整模式** | 复杂项目、多人协作、需要严格设计评审 | Design → Plan → Run | `/hf-design` → `/hf-plan` → `/hf-run` |
| **快速模式** | 中等复杂度、需求明确、设计简单 | Plan → Run | `/hf-plan --fast` 或 `/hf-plan-fast` |
| **最小模式** | 简单任务、快速原型、单文件修改 | Run | `/hf-run --minimal` 或 `/hf-quick` |

---

### 3.2 实施细节

#### 3.2.1 修改阶段推进闸门规则

**当前规则**（`harnessflow/SKILL.md`）：
```markdown
## 阶段推进闸门

上游文档的 `Status` 不是 `Approved` 时，不进入下游阶段。
这个批准动作由人做，不由 Agent 代做。
```

**新增规则**：
```markdown
## 阶段推进闸门

### 完整模式（默认）
需求 Approved ──► 设计 Approved ──► 实施书 Approved ──► 执行

上游文档的 `Status` 不是 `Approved` 时，不进入下游阶段。

### 快速模式（跳过设计）
用户输入 ──► 实施书 Approved ──► 执行

触发方式：
- `/hf-plan --fast "user requirement"`
- `/hf-plan-fast "user requirement"`

行为：
1. 将用户输入作为需求，直接生成 02_IMPLEMENTATION_PLAN.md + 03_TASKS.json
2. 自动生成简化版 00_REQUIREMENTS.md（仅记录需求，标记为 `Mode: fast`）
3. 跳过 01_DESIGN.md
4. 实施书 Approved 后可进入执行

### 最小模式（直接执行）
用户输入 ──► 执行

触发方式：
- `/hf-run --minimal "do something"`
- `/hf-quick "do something"`

行为：
1. 将用户输入转换为单任务或小任务集（≤3 个任务）
2. 自动生成最小化的 03_TASKS.json（仅包含一个 phase，一个 batch）
3. 跳过所有文档，直接执行
4. 完成后生成简化的交付报告

**模式选择建议**：
- 任务涉及 > 5 个文件或 > 2 个模块 → 完整模式
- 任务需求明确，涉及 2-5 个文件 → 快速模式
- 任务是单文件修改、bug 修复、配置调整 → 最小模式
```

---

#### 3.2.2 创建快速模式技能

**文件**: `.claude/skills/hf-plan-fast.md`

```markdown
---
name: hf-plan-fast
description: 快速模式 — 跳过设计阶段，从用户需求直接生成实施书与任务图
---

# HarnessFlow 快速模式

## 触发条件

用户执行以下命令之一：
- `/hf-plan-fast "requirement description"`
- `/hf-plan --fast "requirement description"`

## 与完整模式的区别

| 完整模式 | 快速模式 |
|---------|---------|
| 需要先 `/hf-design` 生成 01_DESIGN.md | 跳过设计，直接生成实施书 |
| 严格的 EARS 格式需求 | 简化的需求记录 |
| 详细的架构设计 | 在实施书中合并设计要点 |
| 适合复杂项目 | 适合需求明确的中等任务 |

## 执行流程

### 1. 生成简化版需求书

**文件**: `docs/harnessflow/00_REQUIREMENTS.md`

**内容结构**（简化版，不强制 EARS）：
```markdown
# 需求规格书（快速模式）

**Mode**: fast
**Created**: YYYY-MM-DD HH:MM
**Source**: 用户直接输入

## 用户需求

<用户的原始需求描述>

## 核心目标

<从需求中提炼的 2-5 个核心目标>

## 范围限定

**包含**:
- <明确要做的>

**不包含**:
- <明确不做的>

## 快速验收标准

- <可观察的验收条件 1>
- <可观察的验收条件 2>

**Status**: Approved (auto, fast mode)
```

**注意**：
- 不需要 EARS 格式
- 不需要详细的 REQ-ID
- Status 自动设为 Approved
- 在文件头标记 `Mode: fast`，让后续流程知道这是快速模式

---

### 2. 生成实施书（合并设计要点）

**文件**: `docs/harnessflow/02_IMPLEMENTATION_PLAN.md`

**与完整模式的区别**：
- 在开头添加 "Design Summary" 小节，简要说明关键设计决策
- 不引用 01_DESIGN.md（因为它不存在）
- 阶段划分更粗粒度（2-3 个阶段 vs 完整模式的 4-6 个）

**结构**：
```markdown
# 实施计划（快速模式）

**Mode**: fast
**Based on**: 00_REQUIREMENTS.md (fast mode)

## Design Summary

<关键设计决策的 3-5 条要点>
<例如：使用 REST API、状态存储用 Redis、前端用 React>

## Phase Breakdown

<后续与完整模式相同>
```

---

### 3. 生成任务图

**文件**: `docs/harnessflow/03_TASKS.json`

**与完整模式的区别**：
- 任务粒度可以更粗（快速模式下优先速度）
- 测试覆盖矩阵简化（如果启用了测试增强功能）
- 批次数量较少（合并可以合并的）

**结构**（标准 JSON，但 metadata 中标记模式）：
```json
{
  "metadata": {
    "mode": "fast",
    "generated_from": "user_input",
    "skip_adequacy_review": true
  },
  "phases": [...]
}
```

**注意**：
- `skip_adequacy_review: true` 告诉 hf-verifier 跳过严格的测试充分性检查
- 仍然生成基础的 coverage_matrix，但不强制每个需求都有 3 层测试

---

### 4. 输出提示

生成完成后，告诉用户：

```
✅ 快速模式实施书已生成（跳过了设计阶段）

生成的文件：
- 00_REQUIREMENTS.md (简化版，已自动 Approved)
- 02_IMPLEMENTATION_PLAN.md (包含设计要点)
- 03_TASKS.json

下一步：
/hf-run

💡 如果需要详细设计，可以运行：
/hf-design --retrofit  （为现有需求补充设计文档）
```

---

## 质量保证

快速模式虽然跳过设计，但仍然保留：
- ✅ 并行批次划分
- ✅ 任务路径隔离检查
- ✅ 独立验证（hf-verifier）
- ✅ 基础的 Sensor 检查（如果启用）
- ⚠️ 简化的测试覆盖要求（不强制 3 层）
- ❌ 不生成 EARS 格式需求
- ❌ 不生成详细设计文档

## 退出快速模式

如果快速模式生成的实施书不满足需求，可以：

1. **补充设计**：
   ```
   /hf-design --retrofit
   ```
   为现有需求生成详细的 01_DESIGN.md

2. **重新规划**：
   ```
   /hf-plan --full
   ```
   忽略之前的快速模式产物，按完整流程重新生成
```

---

#### 3.2.3 创建最小模式技能

**文件**: `.claude/skills/hf-quick.md`

```markdown
---
name: hf-quick
description: 最小模式 — 跳过所有文档，直接执行简单任务（≤3 个子任务）
---

# HarnessFlow 最小模式

## 触发条件

用户执行以下命令之一：
- `/hf-quick "do something"`
- `/hf-run --minimal "do something"`

## 适用场景

⚠️ **仅适用于简单任务**：
- 单文件修改或 bug 修复
- 配置文件调整
- 样板代码生成
- 简单的功能添加（不涉及架构变更）

❌ **不适用于**：
- 涉及 > 3 个文件的修改
- 需要跨模块协调
- 有复杂业务逻辑
- 需要详细的验收标准

## 执行流程

### 1. 自动判断是否适合最小模式

**检查**：
```python
if 估计涉及文件数 > 3:
    return "任务过于复杂，建议使用快速模式: /hf-plan-fast"

if 需要架构决策:
    return "任务需要设计决策，建议使用完整模式: /hf-design"

# 否则继续
```

---

### 2. 生成最小化任务图

**文件**: `docs/harnessflow/03_TASKS.json`

**结构**（极简版）：
```json
{
  "metadata": {
    "mode": "minimal",
    "description": "<用户需求一句话>",
    "skip_all_docs": true
  },
  "phases": [
    {
      "id": "P01",
      "title": "Quick Fix",
      "status": "todo",
      "batches": [
        {
          "id": "P01-B1",
          "mode": "serial",
          "tasks": [
            {
              "id": "P01-T01",
              "title": "<从用户需求提炼>",
              "agent_type": "coding",
              "model": "sonnet",
              "goal": "<单一目标>",
              "allowed_paths": ["<推断的文件路径>"],
              "verify": "npm test",
              "acceptance": ["<可观察条件>"]
            }
          ]
        }
      ]
    }
  ]
}
```

**特点**：
- 只有一个 phase
- 只有一个 batch（通常是 serial）
- 1-3 个任务
- 不生成 00/01/02 文档

---

### 3. 直接执行

调用现有的 `/hf-run` 执行逻辑：
- 使用 `hf-task-worker`（简单任务）或 `hf-phase-lead`（需要判断的）
- 运行验证
- 生成简化的交付报告

---

### 4. 交付报告

**文件**: `docs/harnessflow/deliverables/QUICK-<timestamp>.md`

**内容**（极简版）：
```markdown
# 快速任务交付报告

**Mode**: minimal
**Task**: <用户需求>
**Completed**: YYYY-MM-DD HH:MM

## 改动文件

- `<file1>` — <改了什么>
- `<file2>` — <改了什么>

## 验证结果

<verify 命令输出摘要>

## 后续建议

<如果发现任务比预期复杂，建议后续行动>
```

---

## 质量保证

最小模式保留最基础的质量检查：
- ✅ 路径归属检查
- ✅ verify 命令执行
- ✅ 验收条件判定
- ❌ 不做 Sensor 扫描
- ❌ 不做 Adequacy Review
- ❌ 不生成 Lessons Learned

## 示例

### 示例 1：修复 bug

```
用户: /hf-quick "fix the null pointer exception in user.service.ts line 42"

系统:
✅ 最小模式已完成

改动文件:
- src/services/user.service.ts:42 — 添加 null 检查

验证: npm test → 通过

详细报告: docs/harnessflow/deliverables/QUICK-20260917-143022.md
```

### 示例 2：添加配置

```
用户: /hf-quick "add a new config option MAX_RETRIES=3 to config.ts"

系统:
✅ 最小模式已完成

改动文件:
- src/config.ts — 添加 MAX_RETRIES 常量
- src/config.ts — 导出 MAX_RETRIES

验证: npm run build → 通过
```

### 示例 3：任务过于复杂

```
用户: /hf-quick "add user authentication with JWT"

系统:
⚠️ 任务过于复杂，不适合最小模式

估计涉及文件: 5-8 个
需要设计决策: 是（JWT 存储位置、中间件设计）

建议:
- 快速模式: /hf-plan-fast "add user authentication with JWT"
- 完整模式: /hf-design "user authentication system"
```
```

---

#### 3.2.4 修改核心技能文件

**修改**: `.claude/skills/harnessflow/SKILL.md`

在第 26-39 行的 "阶段推进闸门" 部分，替换为 3.2.1 中的新增规则。

在文件开头添加模式说明：

```markdown
## 流程模式

HarnessFlow 支持三种流程模式，根据任务复杂度选择：

| 模式 | 命令 | 适用 | 生成文档 |
|-----|------|------|---------|
| 完整 | `/hf-design` → `/hf-plan` → `/hf-run` | 复杂项目、需要设计评审 | 00/01/02/03 全套 |
| 快速 | `/hf-plan-fast` → `/hf-run` | 需求明确、设计简单 | 00(简化)/02/03 |
| 最小 | `/hf-quick` | 简单任务、≤3 文件 | 仅 03(极简) |

所有模式都保留：并行执行、任务隔离、独立验证。
快速/最小模式简化质量检查以换取速度。
```

---

## 四、详细实施步骤

#### 任务 1.1: 创建 EARS 需求模板
**负责人**: 手工完成  
**产物**: `templates/00_REQUIREMENTS_TEMPLATE.md`

**模板结构**:
```markdown
# 需求规格书

## 1. 功能需求 (EARS 格式)

每条需求按照 EARS 格式书写：

**UBIQUITOUS (普遍需求)**: The system shall [requirement]
- REQ-001: The system shall support user login via email and password

**EVENT-DRIVEN (事件驱动)**: WHEN [event], the system shall [response]
- REQ-002: WHEN a user submits a form, the system shall validate all required fields

**UNWANTED (不期望行为)**: IF [condition], THEN the system shall [response]
- REQ-003: IF a user enters an invalid password 3 times, THEN the system shall lock the account

**STATE-DRIVEN (状态驱动)**: WHILE [state], the system shall [requirement]
- REQ-004: WHILE a file is uploading, the system shall display a progress bar

**OPTIONAL (可选功能)**: WHERE [condition], the system shall [requirement]
- REQ-005: WHERE the user has admin role, the system shall show the settings menu

## 2. 非功能需求

### 2.1 性能
- PERF-001: 95% 的 API 请求响应时间 < 200ms
- PERF-002: 支持 1000 并发用户

### 2.2 安全
- SEC-001: 所有密码必须 bcrypt 加密存储
- SEC-002: API 端点需要 JWT 认证

### 2.3 可维护性
- MAINT-001: 代码测试覆盖率 > 80%
- MAINT-002: 所有公共 API 需要 JSDoc 注释

## 3. 验收标准

每个功能需求需要对应的验收标准：

| 需求 ID | 验收标准 | 测试方法 |
|--------|---------|---------|
| REQ-001 | 用户能成功登录并看到 dashboard | 集成测试 |
| REQ-002 | 缺少必填字段时显示错误信息 | 单元测试 + E2E |
| REQ-003 | 3 次失败后账户锁定 30 分钟 | 集成测试 |
```

**验证方式**: 在 `/hf-design` 中强制使用此模板

---

#### 任务 1.2: 升级 `/hf-design` 技能
**负责人**: 编辑 `.claude/skills/hf-design.md`  
**改动点**:

1. 在 `instructions` 中添加：
```markdown
## 需求规格书格式要求

**必须使用 EARS 格式书写功能需求**：
- Ubiquitous: The system shall [requirement]
- Event-driven: WHEN [event], the system shall [response]
- Unwanted: IF [condition], THEN the system shall [response]
- State-driven: WHILE [state], the system shall [requirement]
- Optional: WHERE [condition], the system shall [requirement]

**每条需求需要**：
- 唯一 ID (REQ-NNN)
- 可测试的验收标准
- 对应的测试方法（单元测试/集成测试/E2E）

在写入 `00_REQUIREMENTS.md` 前，检查：
1. 所有功能需求是否都用 EARS 格式
2. 每条需求是否有验收标准
3. 验收标准是否可测试（避免"用户满意"这种模糊标准）
```

2. 在 `examples` 中添加反例：
```markdown
❌ **错误示例**:
- 系统应该快速响应 (模糊，无法测试)
- 用户界面要好看 (主观，无验收标准)

✅ **正确示例**:
- REQ-005: The system shall respond to user input within 200ms (95th percentile)
  - 验收标准: 压测工具测得 P95 < 200ms
  - 测试方法: 性能测试
```

**验证方式**: 运行 `/hf-design` 后检查 `00_REQUIREMENTS.md` 是否符合 EARS 格式

---

#### 任务 1.3: 创建 EARS 校验脚本
**负责人**: 手工完成  
**产物**: `scripts/validate-ears.sh`

```bash
#!/bin/bash
# 校验需求书是否符合 EARS 格式

REQUIREMENTS_FILE="docs/harnessflow/00_REQUIREMENTS.md"

if [ ! -f "$REQUIREMENTS_FILE" ]; then
  echo "❌ 需求书不存在: $REQUIREMENTS_FILE"
  exit 1
fi

echo "📋 校验需求书格式..."

# 检查是否有 EARS 格式关键词
UBIQUITOUS=$(grep -c "The system shall" "$REQUIREMENTS_FILE" || true)
EVENT=$(grep -c "WHEN.*the system shall" "$REQUIREMENTS_FILE" || true)
UNWANTED=$(grep -c "IF.*THEN the system shall" "$REQUIREMENTS_FILE" || true)

if [ $UBIQUITOUS -eq 0 ] && [ $EVENT -eq 0 ] && [ $UNWANTED -eq 0 ]; then
  echo "⚠️  警告: 未检测到 EARS 格式需求"
fi

# 检查需求 ID
REQ_IDS=$(grep -E "REQ-[0-9]+" "$REQUIREMENTS_FILE" | wc -l)
echo "✅ 发现 $REQ_IDS 个需求 ID"

# 检查验收标准表格
if grep -q "| 需求 ID | 验收标准 |" "$REQUIREMENTS_FILE"; then
  echo "✅ 发现验收标准表格"
else
  echo "⚠️  警告: 缺少验收标准表格"
fi

echo "✅ 校验完成"
```

**使用方式**: 在 `/hf-plan` 开始前自动运行

---

### 阶段 2: 实施书与测试矩阵 (2-2.5 人日)

#### 任务 2.1: 设计 Test Coverage Matrix 数据结构
**负责人**: 手工完成  
**产物**: 在 `03_TASKS.json` 中扩展 `tests` 字段

**当前结构**:
```json
{
  "id": "impl-001",
  "phase": "implementation",
  "tests": ["test/user.test.js"]  // 只有文件路径
}
```

**目标结构**:
```json
{
  "id": "impl-001",
  "phase": "implementation",
  "tests": {
    "unit": [
      {
        "file": "test/unit/user.test.js",
        "covers": ["REQ-001", "REQ-002"],
        "scenarios": [
          "valid login credentials",
          "invalid password",
          "locked account"
        ]
      }
    ],
    "integration": [
      {
        "file": "test/integration/auth.test.js",
        "covers": ["REQ-001", "REQ-003"],
        "scenarios": [
          "full login flow",
          "account lockout after 3 failures"
        ]
      }
    ],
    "e2e": [
      {
        "file": "test/e2e/login.spec.js",
        "covers": ["REQ-001"],
        "scenarios": ["user can login and see dashboard"]
      }
    ]
  },
  "coverage_matrix": {
    "REQ-001": {
      "unit": true,
      "integration": true,
      "e2e": true,
      "confidence": "high"
    },
    "REQ-002": {
      "unit": true,
      "integration": false,
      "e2e": false,
      "confidence": "medium"
    }
  }
}
```

---

#### 任务 2.2: 升级 `/hf-plan` 生成测试矩阵
**负责人**: 编辑 `.claude/skills/hf-plan.md`  
**改动点**:

在 `instructions` 的任务图生成步骤后添加：

```markdown
## 6. 生成 Test Coverage Matrix

**为每个实现任务生成测试矩阵**：

1. **提取验收标准**: 从 `00_REQUIREMENTS.md` 中提取所有 REQ-ID
2. **规划测试层级**: 每个需求至少有一种测试覆盖
   - Unit: 单个函数/类的行为
   - Integration: 模块间交互
   - E2E: 完整用户流程
3. **生成测试场景**: 每个需求列出 2-5 个关键测试场景
4. **计算覆盖度**:
   ```
   confidence = high    (3 层全覆盖)
   confidence = medium  (2 层覆盖)
   confidence = low     (1 层覆盖)
   ```

**示例**:
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
          "validatePassword returns false for wrong password",
          "hashPassword generates bcrypt hash"
        ]
      }
    ],
    "integration": [
      {
        "file": "test/integration/auth-api.test.js",
        "covers": ["REQ-001", "REQ-003"],
        "scenarios": [
          "POST /api/login with valid credentials returns JWT",
          "POST /api/login with invalid password returns 401",
          "POST /api/login locks account after 3 failures"
        ]
      }
    ],
    "e2e": [
      {
        "file": "test/e2e/login-flow.spec.js",
        "covers": ["REQ-001"],
        "scenarios": [
          "user can login and access protected page"
        ]
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

**生成规则**:
- 每个 REQ-ID 必须出现在至少一个测试的 `covers` 中
- 如果某个需求只有 low confidence，在 `02_IMPLEMENTATION_PLAN.md` 中标注为风险项
```

---

#### 任务 2.3: 创建测试矩阵报告脚本
**负责人**: 手工完成  
**产物**: `scripts/test-coverage-report.js`

```javascript
#!/usr/bin/env node
const fs = require('fs');

const TASKS_FILE = 'docs/harnessflow/03_TASKS.json';
const REQUIREMENTS_FILE = 'docs/harnessflow/00_REQUIREMENTS.md';

function generateReport() {
  const tasks = JSON.parse(fs.readFileSync(TASKS_FILE, 'utf-8'));
  const requirements = fs.readFileSync(REQUIREMENTS_FILE, 'utf-8');
  
  // 提取所有 REQ-ID
  const reqIds = [...requirements.matchAll(/REQ-\d+/g)].map(m => m[0]);
  const uniqueReqs = [...new Set(reqIds)];
  
  // 收集覆盖情况
  const coverage = {};
  uniqueReqs.forEach(req => {
    coverage[req] = { unit: false, integration: false, e2e: false, tasks: [] };
  });
  
  tasks.tasks.forEach(task => {
    if (!task.coverage_matrix) return;
    Object.entries(task.coverage_matrix).forEach(([reqId, cov]) => {
      if (coverage[reqId]) {
        coverage[reqId].unit ||= cov.unit;
        coverage[reqId].integration ||= cov.integration;
        coverage[reqId].e2e ||= cov.e2e;
        coverage[reqId].tasks.push(task.id);
      }
    });
  });
  
  // 生成报告
  console.log('\n📊 Test Coverage Matrix Report\n');
  console.log('| Requirement | Unit | Integration | E2E | Confidence | Tasks |');
  console.log('|-------------|------|-------------|-----|------------|-------|');
  
  uniqueReqs.forEach(req => {
    const cov = coverage[req];
    const layers = [cov.unit, cov.integration, cov.e2e].filter(Boolean).length;
    const confidence = layers === 3 ? 'HIGH' : layers === 2 ? 'MEDIUM' : 'LOW';
    const u = cov.unit ? '✅' : '❌';
    const i = cov.integration ? '✅' : '❌';
    const e = cov.e2e ? '✅' : '❌';
    const tasks = cov.tasks.join(', ') || 'none';
    
    console.log(`| ${req} | ${u} | ${i} | ${e} | ${confidence} | ${tasks} |`);
  });
  
  // 统计
  const lowConfidence = Object.values(coverage).filter(c => 
    [c.unit, c.integration, c.e2e].filter(Boolean).length === 1
  );
  
  if (lowConfidence.length > 0) {
    console.log(`\n⚠️  ${lowConfidence.length} requirements have LOW confidence (single layer)`);
  }
}

generateReport();
```

**使用方式**: 
- `/hf-plan` 结束后自动运行
- `/hf-status` 中显示覆盖率统计

---

### 阶段 3: 验证器增强 (1.5-2 人日)

#### 任务 3.1: 设计 Sensor 检查清单
**负责人**: 手工完成  
**产物**: `docs/harnessflow/SENSOR_CHECKLIST.md`

**7 类传感器** (来自 tlc):

```markdown
# Sensor 检查清单

## 1. Correctness Sensor (正确性)
- [ ] 所有单元测试通过
- [ ] 集成测试通过
- [ ] E2E 测试通过
- [ ] 无编译/构建错误

## 2. Completeness Sensor (完整性)
- [ ] 所有 REQ-ID 都有测试覆盖
- [ ] 所有验收标准都有对应测试
- [ ] 所有公共 API 都有文档
- [ ] 所有配置项都有说明

## 3. Consistency Sensor (一致性)
- [ ] 代码风格符合 linter 规则
- [ ] 命名符合项目约定
- [ ] 文件组织符合目录结构规范
- [ ] API 设计风格一致

## 4. Boundary Sensor (边界条件)
- [ ] 空输入测试
- [ ] 大数据量测试
- [ ] 并发场景测试
- [ ] 错误路径测试

## 5. Security Sensor (安全)
- [ ] 输入验证
- [ ] SQL 注入防护
- [ ] XSS 防护
- [ ] 认证/授权检查

## 6. Performance Sensor (性能)
- [ ] 响应时间符合要求
- [ ] 内存使用合理
- [ ] 数据库查询优化
- [ ] 无明显性能瓶颈

## 7. Maintainability Sensor (可维护性)
- [ ] 代码测试覆盖率 > 80%
- [ ] 圈复杂度 < 10
- [ ] 函数长度 < 50 行
- [ ] 注释充分（复杂逻辑有说明）
```

---

#### 任务 3.2: 升级 `hf-verifier` 代理
**负责人**: 编辑 `.claude/agents/hf-verifier.md`  
**改动点**:

在 `instructions` 中添加验证步骤：

```markdown
## 验证流程

### 1. 基础验证 (已有)
- 运行 verify 命令
- 检查改动范围是否在 allowed_paths 内
- 判定验收标准是否满足

### 2. Adequacy Review (新增)

**检查测试充分性**：

1. **读取测试文件**: 从任务的 `tests` 字段获取所有测试文件
2. **检查覆盖率**: 对比 `coverage_matrix` 与实际测试
   - 每个声明的测试文件是否存在？
   - 每个 scenario 是否有对应的测试用例？
   - 是否有测试文件但未在矩阵中声明？

3. **判定充分性**:
   ```
   ADEQUATE: 所有 REQ-ID 都有测试，且测试用例覆盖所有 scenarios
   MARGINAL: 所有 REQ-ID 有测试，但部分 scenarios 未覆盖
   INADEQUATE: 存在未测试的 REQ-ID 或缺失关键 scenarios
   ```

4. **输出**: 在验证报告中添加 `test_adequacy` 字段
   ```json
   {
     "task_id": "impl-001",
     "status": "pass",
     "test_adequacy": "ADEQUATE",
     "missing_coverage": [],
     "未声明测试": ["test/user-extra.test.js"]
   }
   ```

### 3. Sensor 扫描 (新增)

**运行 7 类传感器检查**：

按 `docs/harnessflow/SENSOR_CHECKLIST.md` 逐项检查：

1. **Correctness**: 运行 `npm test` / `pytest` / `go test`
2. **Completeness**: 检查文档、配置完整性
3. **Consistency**: 运行 linter (`npm run lint` / `ruff check`)
4. **Boundary**: 搜索是否有边界测试（关键词: `empty`, `null`, `max`, `concurrent`）
5. **Security**: 搜索是否有安全检查（关键词: `sanitize`, `escape`, `validate`, `auth`）
6. **Performance**: 如果有性能要求，检查是否有性能测试
7. **Maintainability**: 运行覆盖率工具 (`npm run coverage`)

**输出**: 在验证报告中添加 `sensor_results` 字段
```json
{
  "sensor_results": {
    "correctness": "pass",
    "completeness": "pass",
    "consistency": "pass",
    "boundary": "warn",  // 发现 2/5 边界场景未测试
    "security": "pass",
    "performance": "skip",  // 无性能要求
    "maintainability": "pass"
  },
  "warnings": [
    "Boundary Sensor: 缺少空输入测试和并发场景测试"
  ]
}
```

### 4. 判定是否通过

**通过条件**:
- 基础验证 pass
- test_adequacy 为 ADEQUATE 或 MARGINAL
- sensor_results 中没有 fail（warn 可接受）

**如果不通过**: 在报告中列出具体问题，任务状态标记为 `failed_verification`
```

---

#### 任务 3.3: 创建 Sensor 自动化脚本
**负责人**: 手工完成  
**产物**: `scripts/run-sensors.sh`

```bash
#!/bin/bash
# 运行 7 类传感器检查

TASK_ID=$1
SENSOR_REPORT="docs/harnessflow/sensor-report-${TASK_ID}.json"

echo "🔍 Running Sensor Checks for $TASK_ID..."

# 初始化报告
cat > "$SENSOR_REPORT" <<EOF
{
  "task_id": "$TASK_ID",
  "timestamp": "$(date -Iseconds)",
  "sensors": {}
}
EOF

# 1. Correctness
echo "  [1/7] Correctness Sensor..."
if npm test > /dev/null 2>&1; then
  CORRECTNESS="pass"
else
  CORRECTNESS="fail"
fi

# 2. Completeness (检查是否有 TODO/FIXME)
echo "  [2/7] Completeness Sensor..."
if grep -rE "TODO|FIXME" src/ > /dev/null; then
  COMPLETENESS="warn"
else
  COMPLETENESS="pass"
fi

# 3. Consistency (运行 linter)
echo "  [3/7] Consistency Sensor..."
if npm run lint > /dev/null 2>&1; then
  CONSISTENCY="pass"
else
  CONSISTENCY="fail"
fi

# 4-7. 其他传感器...
# (类似逻辑，检查各类问题)

# 生成最终报告
cat > "$SENSOR_REPORT" <<EOF
{
  "task_id": "$TASK_ID",
  "timestamp": "$(date -Iseconds)",
  "sensors": {
    "correctness": "$CORRECTNESS",
    "completeness": "$COMPLETENESS",
    "consistency": "$CONSISTENCY",
    "boundary": "skip",
    "security": "skip",
    "performance": "skip",
    "maintainability": "skip"
  }
}
EOF

echo "✅ Sensor report saved to $SENSOR_REPORT"
```

**集成方式**: `hf-verifier` 在验证前调用此脚本

---

### 阶段 4: 经验教训机制 (0.5-1 人日)

#### 任务 4.1: 创建 Lessons Learned 模板
**负责人**: 手工完成  
**产物**: `templates/LESSONS_TEMPLATE.md`

```markdown
# Lessons Learned - [Phase Name]

## 执行信息
- **阶段**: Phase X - [Name]
- **执行时间**: YYYY-MM-DD HH:MM ~ YYYY-MM-DD HH:MM
- **任务数量**: N 个任务（M 个并行批次）
- **参与代理**: hf-task-worker × K, hf-verifier × 1

---

## 🎯 What Went Well (做得好的)

### 1. [标题]
**Context**: [什么场景]
**Action**: [做了什么]
**Result**: [结果如何]
**Why it worked**: [为什么有效]

---

## 🚨 What Went Wrong (出问题的)

### 1. [标题]
**Context**: [什么场景]
**Problem**: [遇到什么问题]
**Root Cause**: [根本原因]
**Impact**: [造成什么影响]
**How we fixed it**: [如何修复]

---

## 💡 Insights & Recommendations (洞察与建议)

### 1. [标题]
**Observation**: [观察到什么]
**Why it matters**: [为什么重要]
**Recommendation**: [建议后续怎么做]
**Apply to**: [适用于哪些场景]

---

## 📊 Metrics

| 指标 | 值 | 目标 | 状态 |
|-----|---|------|------|
| 任务首次通过率 | 85% | > 80% | ✅ |
| 平均返工次数 | 1.2 | < 1.5 | ✅ |
| Sensor 检查通过率 | 90% | > 90% | ✅ |
| 测试覆盖率 | 82% | > 80% | ✅ |

---

## 🔗 Related

- 相关任务: [链接到 03_TASKS.json]
- 相关问题: [如果有对应的 issue/PR]
```

---

#### 任务 4.2: 升级 `hf-phase-orchestrator` 生成 Lessons
**负责人**: 编辑 `.claude/agents/hf-phase-orchestrator.md`  
**改动点**:

在 `instructions` 的最后添加：

```markdown
## 阶段结束后: 生成 Lessons Learned

**在所有任务验证通过、交付文档写完后**:

1. **收集数据**:
   - 读取本阶段所有任务的执行日志
   - 统计任务首次通过率、返工次数、验证失败原因
   - 读取所有 sensor 报告

2. **识别模式**:
   - 哪些类型的任务容易失败？
   - 哪些 sensor 经常 warn/fail？
   - 哪些并行批次配合得好/差？

3. **写入文件**:
   - 文件路径: `docs/harnessflow/LESSONS-Phase-X.md`
   - 使用模板: `templates/LESSONS_TEMPLATE.md`
   - 必须包含至少 3 个 insights

4. **在交付摘要中引用**:
   ```markdown
   ## 经验教训
   详见 [LESSONS-Phase-2.md](./LESSONS-Phase-2.md)
   
   关键建议:
   - [Insight 1]
   - [Insight 2]
   ```

**示例 Lesson**:
```markdown
## 💡 Insight: 测试文件路径不一致导致重复验证

**Observation**: 
Phase 2 中有 3 个任务的测试文件路径在任务图中写的是 `test/unit/user.test.js`，但实际生成的是 `tests/unit/user.test.js` (多了个 s)。导致 hf-verifier 找不到文件，误报 "测试缺失"。

**Why it matters**: 
路径不一致会让验证器产生误报，浪费返工时间。

**Recommendation**: 
在 `/hf-plan` 阶段，先 `ls test* tests*` 确认项目的测试目录命名，然后在任务图中统一使用。

**Apply to**: 
所有涉及文件路径的任务（测试、配置、文档）
```
```

---

### 阶段 5: 集成与测试 (1-1.5 人日)

#### 任务 5.1: 更新主流程文档
**负责人**: 编辑 `docs/harnessflow/harnessflow.md`  
**改动点**:

在各个阶段的规则中添加新增的质量检查：

```markdown
### 阶段 1: 设计 (Phase 0 + 1)

**产物**:
- ✅ 00_REQUIREMENTS.md (必须符合 EARS 格式)
- ✅ 01_DESIGN.md

**质量门禁**:
- 运行 `scripts/validate-ears.sh`，确保需求符合 EARS 格式
- 每个 REQ-ID 都有验收标准

---

### 阶段 2: 规划 (Phase 2)

**产物**:
- ✅ 02_IMPLEMENTATION_PLAN.md
- ✅ 03_TASKS.json (包含完整的 coverage_matrix)

**质量门禁**:
- 运行 `scripts/test-coverage-report.js`
- 所有 REQ-ID 都在 coverage_matrix 中
- 无 LOW confidence 的关键需求（或已标注为风险）

---

### 阶段 3: 实施 (Phase 3+)

**每个批次验证时**:
1. 基础验证 (已有)
2. Adequacy Review (新增)
3. Sensor 扫描 (新增)

**阶段结束时**:
- 生成 LESSONS-Phase-X.md

**最终交付**:
- 所有 sensor 检查 pass
- 测试覆盖率 > 80%
- 所有 REQ-ID 验证通过
```

---

#### 任务 5.2: 集成 playwright-mcp 支持 UI 测试
**负责人**: 手工完成  
**工作量**: 0.5 人日

**背景**:
playwright-mcp 是一个 MCP 服务器，让 Claude Code 能够真正控制浏览器进行 UI 测试。它使用 Playwright 的可访问性树而非截图，提供确定性的浏览器自动化能力。

**关键优势**:
- ✅ 不依赖截图，使用结构化的可访问性树
- ✅ 确定性操作，避免视觉识别的模糊性
- ✅ 完整的工具集：导航、点击、填表、验证、录制
- ✅ 可以获取 console 日志和网络请求用于调试

---

##### 5.2.1 安装 playwright-mcp

**步骤 1: 添加 MCP 服务器**

```bash
# 使用 Claude Code CLI 添加
claude mcp add playwright npx @playwright/mcp@latest
```

这会在 `.claude/settings.json` 中添加配置：

```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp@latest"]
    }
  }
}
```

**步骤 2: 启用测试能力**（可选）

如果需要验证断言功能，启用 `testing` capability：

```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": [
        "@playwright/mcp@latest",
        "--caps=testing"
      ]
    }
  }
}
```

**步骤 3: 验证安装**

重启 Claude Code 后，测试浏览器控制：

```
用户: 帮我打开 https://example.com 并截图

Claude Code 会调用:
- browser_navigate
- browser_take_screenshot
```

---

##### 5.2.2 扩展测试矩阵数据结构支持 UI 测试

**修改**: `03_TASKS.json` 的 `tests` 结构

**新增字段**:

```json
{
  "id": "impl-login-ui",
  "tests": {
    "unit": [...],
    "integration": [...],
    "e2e": [
      {
        "file": "test/e2e/login.spec.ts",
        "covers": ["REQ-001"],
        "tool": "playwright",
        "mode": "headless",
        "scenarios": ["user can login and see dashboard"]
      }
    ],
    "ui_interactive": [
      {
        "description": "Interactive UI test using playwright-mcp",
        "covers": ["REQ-001", "REQ-002"],
        "tool": "playwright-mcp",
        "mode": "interactive",
        "scenarios": [
          "navigate to login page",
          "fill email and password",
          "click submit button",
          "verify dashboard appears",
          "verify welcome message"
        ],
        "verify_commands": [
          "browser_verify_text_visible('Welcome')",
          "browser_verify_element_visible('dashboard')"
        ]
      }
    ]
  }
}
```

**字段说明**:

| 字段 | 说明 |
|-----|------|
| `tool: "playwright-mcp"` | 标识这是通过 MCP 的交互式测试 |
| `mode: "interactive"` | Claude Code 实时调用浏览器工具 |
| `scenarios` | 分步骤的测试场景 |
| `verify_commands` | 验证断言（需要 `--caps=testing`） |

---

##### 5.2.3 修改 hf-task-worker 支持 UI 测试

**文件**: `.claude/agents/hf-task-worker.md`

**在 `instructions` 中添加**:

```markdown
## UI 测试执行

如果任务的 `tests` 包含 `ui_interactive` 字段：

### 1. 检查 playwright-mcp 是否可用

运行前检查 MCP 工具是否加载：
- 如果工具列表中有 `browser_navigate`，说明 playwright-mcp 已启用
- 如果没有，在结果中说明需要手工运行 UI 测试

### 2. 执行 UI 测试流程

按 `scenarios` 逐步执行：

**示例场景**: 测试登录功能

```
1. browser_navigate("http://localhost:3000/login")
   → 等待页面加载

2. browser_snapshot()
   → 获取页面结构，确认表单元素存在

3. browser_type("#email", "test@example.com")
   → 填写邮箱

4. browser_type("#password", "password123")
   → 填写密码

5. browser_click("button[type=submit]")
   → 点击提交按钮

6. browser_wait_for("text=Dashboard")
   → 等待跳转到 dashboard

7. browser_verify_text_visible("Welcome")
   → 验证欢迎信息（需要 --caps=testing）

8. browser_take_screenshot("test-results/login-success.png")
   → 截图记录最终状态
```

### 3. 错误处理

如果某步失败：

```
1. browser_console_messages("error")
   → 获取控制台错误日志

2. browser_network_requests(static=false)
   → 检查网络请求是否有失败

3. browser_take_screenshot("test-results/login-failed.png")
   → 截图保存失败状态

4. 在返回的 RESULT 中标记 FAIL，附上错误日志路径
```

### 4. 返回格式

```
TASK: impl-login-ui
RESULT: PASS
UI_TESTS:
  - scenario: "navigate to login page" → PASS
  - scenario: "fill email and password" → PASS
  - scenario: "click submit button" → PASS
  - scenario: "verify dashboard appears" → PASS
  - scenario: "verify welcome message" → PASS
SCREENSHOTS:
  - test-results/login-success.png
CONSOLE_LOGS:
  - (no errors)
```

### 5. 限制

- 只在开发环境运行（需要本地服务器启动）
- 如果任务的 `allowed_paths` 不包含 `test-results/`，需要先添加
- UI 测试失败不阻塞代码实现验证，但会降低 `test_adequacy` 评分
```

---

##### 5.2.4 修改 hf-verifier 验证 UI 测试结果

**文件**: `.claude/agents/hf-verifier.md`

**在验证流程中添加**:

```markdown
## UI 测试验证

如果任务包含 `ui_interactive` 测试：

### 1. 检查截图产物

```bash
# 检查截图是否存在
ls test-results/*.png

# 如果缺失，标记为警告（不是失败）
```

### 2. 检查场景覆盖

对比任务定义的 `scenarios` 与 worker 返回的 `UI_TESTS`：
- 所有 scenarios 都有对应的测试结果？
- 是否有 scenarios 被跳过？

### 3. 判定 UI 测试充分性

```
ADEQUATE: 所有 scenarios PASS，有截图证据
MARGINAL: 部分 scenarios PASS，或缺少截图
INADEQUATE: 多个 scenarios FAIL 或未执行
```

### 4. 特殊情况处理

**情况 1**: playwright-mcp 未安装

```
如果 worker 返回 "playwright-mcp not available"：
- 不标记为失败
- 在报告中添加建议: "建议安装 playwright-mcp 以启用 UI 自动化测试"
- test_adequacy 标记为 MANUAL_REQUIRED
```

**情况 2**: 本地服务器未启动

```
如果 browser_navigate 失败，错误信息包含 "connection refused":
- 不标记为任务失败
- 在报告中说明: "需要启动本地服务器后手工运行 UI 测试"
- 提供手工测试清单
```

### 5. 验证报告输出

```json
{
  "task_id": "impl-login-ui",
  "status": "pass",
  "test_adequacy": "ADEQUATE",
  "ui_test_results": {
    "total_scenarios": 5,
    "passed": 5,
    "failed": 0,
    "screenshots": ["test-results/login-success.png"],
    "console_errors": 0
  },
  "recommendations": []
}
```
```

---

##### 5.2.5 可选：启用高级功能

**录制用户操作生成代码**（用于创建测试）:

```
用户: 我要手动演示登录流程，帮我录制成 Playwright 代码

Claude Code:
1. browser_start_recording()
2. 提示用户在浏览器中操作
3. 用户操作完成后，browser_stop_recording()
4. 获得生成的 Playwright 测试代码
5. 保存到 test/e2e/login.spec.ts
```

**Mock 网络请求**（用于测试错误场景）:

```json
{
  "scenarios": [
    "test login with server error",
    "mock API to return 500",
    "verify error message appears"
  ],
  "setup_commands": [
    "browser_route('**/api/login', status=500, body='{\"error\":\"Server error\"}')"
  ]
}
```

---

##### 5.2.6 更新测试覆盖率报告

**修改**: `scripts/test-coverage-report.js`

**添加 UI 测试统计**:

```javascript
// 收集 UI 测试覆盖
const uiCoverage = {};
tasks.tasks.forEach(task => {
  if (task.tests?.ui_interactive) {
    task.tests.ui_interactive.forEach(test => {
      test.covers.forEach(reqId => {
        if (!uiCoverage[reqId]) {
          uiCoverage[reqId] = [];
        }
        uiCoverage[reqId].push(task.id);
      });
    });
  }
});

// 在报告中添加 UI 列
console.log('| Requirement | Unit | Integration | E2E | UI | Confidence |');
console.log('|-------------|------|-------------|-----|-------|------------|');

uniqueReqs.forEach(req => {
  const cov = coverage[req];
  const ui = uiCoverage[req] ? '✅' : '❌';
  const layers = [cov.unit, cov.integration, cov.e2e, uiCoverage[req]].filter(Boolean).length;
  const confidence = layers >= 3 ? 'HIGH' : layers === 2 ? 'MEDIUM' : 'LOW';
  
  console.log(`| ${req} | ${cov.unit ? '✅' : '❌'} | ${cov.integration ? '✅' : '❌'} | ${cov.e2e ? '✅' : '❌'} | ${ui} | ${confidence} |`);
});
```

---

##### 5.2.7 文档更新

**在 ENHANCEMENT_PLAN.md 中添加测试金字塔说明**:

```markdown
## UI 测试层级（使用 playwright-mcp）

### 1. 传统 E2E 测试（Headless Playwright）
- **工具**: Playwright test runner
- **模式**: Headless
- **适用**: CI/CD 自动化
- **由谁写**: `hf-test-worker` 生成测试文件

### 2. 交互式 UI 测试（playwright-mcp）
- **工具**: playwright-mcp MCP 服务器
- **模式**: Headed（可见浏览器）或 Headless
- **适用**: 开发阶段的快速验证、调试
- **由谁执行**: `hf-task-worker` 实时调用工具

### 3. 手工测试（清单）
- **工具**: 无（人工）
- **适用**: 复杂交互、可访问性、跨浏览器
- **由谁生成**: `hf-verifier` 生成测试清单

### 测试策略选择

| 场景 | 推荐方式 | 理由 |
|-----|---------|------|
| 关键用户流程（登录、支付） | E2E + UI | 双重保障 |
| 复杂表单验证 | UI interactive | 便于调试 |
| 视觉回归 | Playwright + Percy | 需要截图对比 |
| 性能测试 | Lighthouse + 自定义 | 专用工具 |
| 可访问性 | axe-core + 手工 | 需要人工判断 |
```

---

##### 5.2.8 完整示例

**场景**: 实现并测试用户登录功能

**1. 任务定义**（在 `03_TASKS.json` 中）:

```json
{
  "id": "impl-login",
  "title": "实现用户登录功能",
  "agent_type": "coding",
  "allowed_paths": ["src/auth/*", "test/e2e/*", "test-results/*"],
  "tests": {
    "unit": [
      {
        "file": "test/unit/auth.test.ts",
        "covers": ["REQ-001"],
        "scenarios": ["validates email format", "hashes password"]
      }
    ],
    "e2e": [
      {
        "file": "test/e2e/login.spec.ts",
        "covers": ["REQ-001"],
        "tool": "playwright",
        "scenarios": ["successful login flow"]
      }
    ],
    "ui_interactive": [
      {
        "description": "Interactive login test",
        "covers": ["REQ-001", "REQ-002"],
        "tool": "playwright-mcp",
        "scenarios": [
          "navigate to /login",
          "verify form fields exist",
          "fill valid credentials",
          "click submit",
          "verify redirect to dashboard",
          "verify user name displayed"
        ]
      }
    ]
  },
  "coverage_matrix": {
    "REQ-001": {
      "unit": true,
      "integration": false,
      "e2e": true,
      "ui": true,
      "confidence": "high"
    }
  }
}
```

**2. hf-task-worker 执行**:

```
1. 实现 src/auth/login.ts
2. 写单元测试 test/unit/auth.test.ts
3. 写 E2E 测试 test/e2e/login.spec.ts
4. 执行 UI 交互测试:
   - browser_navigate("http://localhost:3000/login")
   - browser_snapshot() → 确认表单存在
   - browser_type("#email", "test@example.com")
   - browser_type("#password", "Test1234!")
   - browser_click("button:has-text('Login')")
   - browser_wait_for("text=Dashboard")
   - browser_verify_text_visible("Welcome, Test User")
   - browser_take_screenshot("test-results/login-pass.png")
5. 返回结果
```

**3. hf-verifier 验证**:

```
✅ 单元测试通过
✅ E2E 测试通过
✅ UI 交互测试通过（6/6 scenarios）
✅ 截图存在: test-results/login-pass.png
✅ 无 console 错误

test_adequacy: ADEQUATE
```

---

#### 任务 5.3: 端到端测试流程
**负责人**: 手工完成  
**验证步骤**:

1. **创建测试项目**:
   ```bash
   mkdir test-harness-enhancement
   cd test-harness-enhancement
   npm init -y
   ```

2. **运行完整流程**:
   ```bash
   # 1. 设计阶段
   /hf-design "构建一个用户登录功能"
   
   # 检查: 00_REQUIREMENTS.md 是否有 EARS 格式
   scripts/validate-ears.sh
   
   # 2. 规划阶段
   /hf-plan
   
   # 检查: 是否生成了 coverage_matrix
   scripts/test-coverage-report.js
   
   # 3. 实施阶段
   /hf-run
   
   # 检查: 是否有 sensor 报告
   ls docs/harnessflow/sensor-report-*.json
   
   # 检查: 是否有 Lessons Learned
   ls docs/harnessflow/LESSONS-*.md
   ```

3. **验证质量提升**:
   - 对比改造前后的测试覆盖率
   - 统计 sensor 发现的问题数量
   - 检查 Lessons 是否包含可行动的建议

---

## 四、验收标准

### 4.1 功能完整性

| 功能 | 验收标准 | 测试方法 |
|-----|---------|---------|
| EARS 模板 | `/hf-design` 生成的需求书符合 EARS 格式 | 手工检查 + `validate-ears.sh` |
| Test Coverage Matrix | `/hf-plan` 生成的任务图包含完整的 `coverage_matrix` | 检查 JSON 结构 + `test-coverage-report.js` |
| Adequacy Review | `hf-verifier` 能判断测试充分性 | 创建测试任务，故意漏掉部分测试，看是否检测到 |
| Sensor 扫描 | `hf-verifier` 能运行 7 类传感器 | 运行完整流程，检查 sensor-report-*.json |
| Lessons Learned | 每阶段结束生成 LESSONS-Phase-X.md | 运行到阶段结束，检查文件存在且内容完整 |

### 4.2 性能要求

- EARS 校验脚本运行时间 < 5 秒
- Test Coverage Matrix 生成时间 < 10 秒
- Sensor 扫描时间 < 30 秒（取决于测试套件大小）

### 4.3 向后兼容性

- **已有项目不受影响**: 如果 `00_REQUIREMENTS.md` 不符合 EARS 格式，显示警告但不阻塞
- **可选启用**: 在 `harnessflow.md` 中添加配置项，允许禁用 Adequacy Review 和 Sensor

---

## 五、风险与缓解

### 5.1 主要风险

| 风险 | 可能性 | 影响 | 缓解措施 |
|-----|-------|------|---------|
| Sensor 检查太慢 | 中 | 中 | 支持并行运行、可配置跳过某些 sensor |
| EARS 格式学习成本高 | 中 | 低 | 提供详细示例、允许渐进式采用 |
| 测试矩阵生成不准确 | 高 | 中 | 在 `/hf-plan` 中加强提示词、允许手工修正 |
| Lessons 质量参差不齐 | 中 | 低 | 提供模板和评分标准、定期回顾 |

### 5.2 回退计划

如果某个功能导致问题，可以**独立禁用**：

```json
// docs/harnessflow/config.json (新增)
{
  "enable_ears_validation": true,
  "enable_adequacy_review": true,
  "enable_sensors": ["correctness", "consistency"],  // 可只启用部分
  "enable_lessons": true
}
```

---

## 六、后续优化方向

### 6.1 短期 (1-2 个月)

1. **智能 Sensor 选择**: 根据任务类型自动选择相关的 sensor
   - 前端任务: 跳过 SQL 注入检查
   - 后端任务: 加强安全和性能检查

2. **Lessons 聚合**: 跨项目聚合 Lessons，形成最佳实践库

3. **测试生成辅助**: 根据 coverage_matrix 自动生成测试骨架

### 6.2 长期 (3-6 个月)

1. **AI Reviewer**: 训练模型识别常见测试问题

2. **指标仪表盘**: 可视化测试覆盖率、sensor 趋势、Lessons 价值

3. **与 CI/CD 集成**: 在 PR 中自动运行 sensor 检查，生成报告

---

## 七、时间表与里程碑

```
Week 1:
  Day 1-2: 阶段 1 (需求与设计增强)
  Day 3-4: 阶段 2 (实施书与测试矩阵)

Week 2:
  Day 1-2: 阶段 3 (验证器增强)
  Day 3: 阶段 4 (经验教训机制)
  Day 4-5: 阶段 5 (集成与测试)

Week 3:
  Day 1-2: 文档完善与培训
  Day 3: 正式发布
```

---

## 八、总结

### 8.1 为什么这个方案更合适

✅ **成本低**: 5-8 人日 vs 15-20 人日  
✅ **风险小**: 增量改进，不破坏现有架构  
✅ **价值高**: 移植 tlc 最核心的质量机制  
✅ **可扩展**: 保留了 HarnessFlow 的并行优势，未来可以继续优化  

### 8.2 关键成功因素

1. **严格执行 EARS 格式**: 这是所有质量检查的基础
2. **测试矩阵要精准**: 不能流于形式，要真正覆盖需求
3. **Sensor 要实用**: 不能报太多 false positive，否则会被忽略
4. **Lessons 要可行动**: 不是写流水账，而是提炼可复用的模式

### 8.3 预期效果

- **测试覆盖率**: 从 ~60% 提升到 > 80%
- **首次验证通过率**: 从 ~70% 提升到 > 85%
- **返工次数**: 从平均 2 次降低到 < 1.5 次
- **质量问题发现**: 通过 Sensor 提前发现 ~30% 的潜在问题

---

## 九、外部文档导入支持 (新增)

### 9.1 场景说明

**问题**: 用户已有设计文档（手工编写、从 PRD 转换、或其他工具生成），想直接用它走 `/hf-plan`，但当前系统要求文档必须通过 `/hf-design` 生成。

**需求**:
- 能够导入外部的 `01_DESIGN.md`
- 验证文档是否符合 HarnessFlow 的格式要求
- 自动修复缺失的元数据字段
- 无缝衔接到 `/hf-plan` 流程

---

### 9.2 解决方案

#### 9.2.1 创建文档验证脚本

**文件**: `scripts/validate-hf-docs.js`

**功能**:
1. 检查文档是否包含必需的元数据字段（Status, Based on）
2. 检查文档是否包含必需的章节
3. 自动修复缺失字段（添加默认值）
4. 生成修复建议

**使用方式**:
```bash
# 检查文档
node scripts/validate-hf-docs.js check 01_DESIGN.md

# 自动修复
node scripts/validate-hf-docs.js fix 01_DESIGN.md
```

**实现**（代码见下方）:
```javascript
#!/usr/bin/env node
const fs = require('fs');
const path = require('path');

const DOCS_DIR = 'docs/harnessflow';

const REQUIRED_FIELDS = {
  '00_REQUIREMENTS.md': {
    metadata: ['Status'],
    sections: ['需求', '验收标准']
  },
  '01_DESIGN.md': {
    metadata: ['Status', 'Based on'],
    sections: ['设计', '架构']
  },
  '02_IMPLEMENTATION_PLAN.md': {
    metadata: ['Status', 'Based on'],
    sections: ['实施计划', 'Phase']
  }
};

function validateDocument(filename) {
  const filepath = path.join(DOCS_DIR, filename);
  
  if (!fs.existsSync(filepath)) {
    return { valid: false, error: '文件不存在' };
  }
  
  const content = fs.readFileSync(filepath, 'utf-8');
  const requirements = REQUIRED_FIELDS[filename];
  
  if (!requirements) {
    return { valid: true };
  }
  
  const warnings = [];
  const fixes = [];
  
  // 检查 metadata
  requirements.metadata.forEach(field => {
    const regex = new RegExp(`^\\*\\*${field}\\*\\*:`, 'm');
    if (!regex.test(content)) {
      warnings.push(`缺少字段: ${field}`);
      fixes.push({
        field,
        default: field === 'Status' ? 'Draft' : 
                 field === 'Based on' ? 'External' : 'N/A'
      });
    }
  });
  
  // 检查章节
  requirements.sections.forEach(section => {
    if (!content.includes(section)) {
      warnings.push(`建议添加章节: ${section}`);
    }
  });
  
  return { valid: warnings.length === 0, warnings, fixes };
}

function applyFixes(filename, fixes) {
  const filepath = path.join(DOCS_DIR, filename);
  let content = fs.readFileSync(filepath, 'utf-8');
  
  const metadata = fixes.map(f => `**${f.field}**: ${f.default}`).join('\n');
  
  // 在第一个 # 标题前插入
  const match = content.match(/^#\s+/m);
  if (match) {
    const pos = content.indexOf(match[0]);
    content = content.slice(0, pos) + metadata + '\n\n' + content.slice(pos);
  } else {
    content = metadata + '\n\n' + content;
  }
  
  fs.writeFileSync(filepath, content);
}

// CLI
const [,, cmd, file] = process.argv;

if (cmd === 'check') {
  const files = file ? [file] : Object.keys(REQUIRED_FIELDS);
  let hasIssues = false;
  
  files.forEach(f => {
    const result = validateDocument(f);
    if (!result.valid) {
      console.log(`❌ ${f}`);
      result.warnings?.forEach(w => console.log(`   ${w}`));
      hasIssues = true;
    } else {
      console.log(`✅ ${f}`);
    }
  });
  
  if (hasIssues) {
    console.log('\n💡 运行 fix 命令自动修复');
    process.exit(1);
  }
  
} else if (cmd === 'fix') {
  const result = validateDocument(file);
  if (result.fixes?.length > 0) {
    applyFixes(file, result.fixes);
    console.log(`✅ 已修复 ${file}`);
    console.log('请检查并更新这些字段:');
    result.fixes.forEach(f => console.log(`   ${f.field}: ${f.default}`));
  } else {
    console.log('✅ 无需修复');
  }
}
```

---

#### 9.2.2 修改 `/hf-plan` 支持外部文档

在 `/hf-plan` 技能的开头添加文档检测逻辑：

**伪代码**:
```markdown
## 前置检查

### 1. 检查设计文档

if 存在 01_DESIGN.md:
  # 验证格式
  运行 scripts/validate-hf-docs.js check 01_DESIGN.md
  
  if 验证失败:
    提示用户:
      "检测到外部设计文档，但格式不规范"
      "运行以下命令修复: node scripts/validate-hf-docs.js fix 01_DESIGN.md"
      "或手工添加以下字段到文档开头:"
      "  **Status**: Approved"
      "  **Based on**: 00_REQUIREMENTS.md"
    退出
  
  # 检查 Status
  提取 Status 字段
  
  if Status != "Approved":
    提示用户:
      "设计文档状态: {Status} (需要 Approved)"
      "如果设计已确认，请更新: **Status**: Approved"
    退出
  
  # 使用完整模式
  MODE = "full"
  BASE_DOC = "01_DESIGN.md"

else:
  # 无设计文档，使用快速模式
  提示: "未检测到设计文档，将使用快速模式"
  MODE = "fast"
  BASE_DOC = "00_REQUIREMENTS.md"

### 2. 生成实施书

根据 MODE 选择策略:
- full: 从 01_DESIGN.md 提取架构决策
- fast: 从 00_REQUIREMENTS.md 推断设计
```

---

#### 9.2.3 标准外部文档模板

**最小必需元数据**:

```markdown
# 设计文档

**Status**: Approved
**Based on**: 00_REQUIREMENTS.md
**Author**: 产品团队 / 手工编写
**Created**: 2026-09-17

## 架构设计

[你的设计内容...]

## 技术选型

[...]
```

如果用户的文档缺少这些字段，`validate-hf-docs.js fix` 会自动添加。

---

### 9.3 使用场景

#### 场景 1: 导入外部设计文档

```bash
# 1. 复制外部文档
cp my-design.md docs/harnessflow/01_DESIGN.md

# 2. 验证格式
node scripts/validate-hf-docs.js check 01_DESIGN.md

# 3. 如果有警告，自动修复
node scripts/validate-hf-docs.js fix 01_DESIGN.md

# 4. 手工确认 Status（编辑文件，改为 Approved）
# 编辑 docs/harnessflow/01_DESIGN.md

# 5. 正常运行 plan
/hf-plan
```

---

#### 场景 2: 用户在聊天中提供设计

```
用户: 我的设计是：用 Redis 做缓存，REST API 用 Express，前端用 React。
     直接帮我生成实施书。

助手:
1. 我会先将你的设计保存到 01_DESIGN.md
2. 自动添加必需的元数据字段
3. 运行 /hf-plan

[调用 Write 工具创建 01_DESIGN.md，包含必需字段]
[调用 /hf-plan]
```

---

#### 场景 3: 只有需求，跳过设计

```
用户: 我有 00_REQUIREMENTS.md，直接生成实施书

助手:
[检测到无 01_DESIGN.md]
💡 将使用快速模式（直接从需求生成实施书）

[生成 02_IMPLEMENTATION_PLAN.md]
[在开头标注: **Based on**: 00_REQUIREMENTS.md (no design doc)]
```

---

### 9.4 实施计划

**工作量**: 0.5 人日

**任务**:
1. 创建 `scripts/validate-hf-docs.js` (2 小时)
2. 修改 `/hf-plan` 技能添加文档检测逻辑 (1 小时)
3. 创建外部文档导入指南 (1 小时)
4. 测试各种场景 (1 小时)

**集成点**:
- 在阶段 1 之后、阶段 2 之前执行
- 与快速模式（3.2.2）配合使用

---

### 9.5 验收标准

| 场景 | 验收条件 | 测试方法 |
|-----|---------|---------|
| 导入完整外部文档 | 能够验证并修复格式，正常进入 /hf-plan | 复制外部文档，运行 fix，运行 /hf-plan |
| 导入不规范文档 | 给出清晰的错误提示和修复建议 | 故意创建缺少字段的文档 |
| 缺少设计文档 | 自动切换到快速模式 | 只提供需求书，运行 /hf-plan |
| Status 未 Approved | 提示用户更新 Status | 设计文档 Status 设为 Draft |

---

**准备好开始实施了吗？建议从阶段 1 的 EARS 模板开始！** 🚀
