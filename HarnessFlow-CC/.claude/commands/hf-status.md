---
description: 只读进度报告 — 阶段/任务状态、下一批可并行任务、文档一致性检查，不执行任何开发
allowed-tools: Read, Glob, Grep, Bash(git status:*), Bash(git log:*), Bash(git diff:*), Skill
---

先调用 `Skill(harnessflow)` 载入共享契约。本命令只读，不写文件、不派子代理、不提交。

读 `docs/harnessflow/03_TASKS.json`、`04_STATE.md`、`02_IMPLEMENTATION_PLAN.md`，
以及 `git status` / `git log --oneline -10`。

输出这些，简洁为主：

```
文档状态：需求=<Status> 设计=<Status> 实施书=<Status>

阶段进度：
  P01 <title>  done
  P02 <title>  in_progress  — 3/5 任务完成
  P03 <title>  todo         — 依赖 P02

当前阶段下一批：P02-B2 (parallel)
  P02-T04  coding/sonnet   src/api/**
  P02-T05  testing/haiku   tests/api/**

阻塞项：<任务 ID — 原因 — 恢复条件，或 无>
待人工：<任务 ID — 交接文件路径，或 无>

一致性检查：
  任务图与实施书 ID 对应   PASS/FAIL
  依赖图无环、引用完整     PASS/FAIL
  状态账本与任务图一致     PASS/FAIL（不一致时列出差异）
  并行批次路径不相交       PASS/FAIL（FAIL 时列出相交任务对）

工作区：干净 / 有未提交改动（列出文件，并判断是否属于记录中的进行中任务）
```

发现不一致时只报告差异和建议动作，不要自己修。修状态是 `/hf-run` 的职责。
