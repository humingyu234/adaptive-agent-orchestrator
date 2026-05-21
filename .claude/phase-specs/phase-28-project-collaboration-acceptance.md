# Phase 28 - Project Collaboration Acceptance

## Goal

最终验收 AAO 是否达到"项目协作者"蓝图。
用一个完整的、真实的、多阶段协作任务证明 Phase 22-27 的能力。

这不是单元测试的替代品。这是最终产品验收测试。

## The Target Scenario

```
"研究并重构 AAO memory 系统"

必须端到端证明以下 13 个步骤全部走通:
```

```
1.  AAO 创建 ProjectSession
    python -m orchestrator project start "研究并重构 AAO memory 系统"

2.  调研外部成熟方案
    Planning Council (LLM) 规划调研步骤
    → worker 调研 GitHub / 大厂 memory 方案
    → 产出对比报告

3.  对比当前 memory 设计
    worker 分析当前 src/orchestrator/memory.py 或相关代码
    → 产出现状分析

4.  给出补强方案
    Planning Council 综合调研 + 现状 → 产出改进计划
    → 包含多个 milestone

5.  暂停等用户确认
    milestone gate → paused_for_approval
    → 用户可以 project ask 追问设计原因

6.  用户可以追问设计原因
    "为什么选方案A而不是方案B？" → 基于 DecisionLog 回答
    "调研了哪些大厂方案？" → 基于 worker output 回答

7.  approve 后拆 worker tasks
    用户 approve → 计划拆成多个 WorkerTaskPacket

8.  多 worker 执行
    独立步骤并行，依赖步骤串行
    → real Claude Code workers

9.  Isolated Reviewer 审查
    每个 worker 产出 → Reviewer (只读) 审查
    → 产出 ReviewFinding

10. 自动返工至少一次
    故意引入一个 fixable 问题（如缺失 import 或 test 失败）
    → Phase 22 检测 → FixTask → 修复 → 重测通过
    → audit 记录 repair round

11. 每个 milestone 生成验收包
    milestone 完成 → evidence summary + reviewer findings + repair history
    → paused_for_approval

12. 项目可 resume
    关闭 Claude Code → 重新打开
    → project continue
    → 正确恢复到当前 milestone
    → project ask 能回答之前的决策原因

13. 最终输出 proof pack / audit report
    完整 audit trail:
    - 计划
    - 审批记录
    - worker 执行记录
    - reviewer 发现
    - 修复历史
    - milestone 验收记录
    - 最终结论
```

## Evidence Required

```
每个步骤必须产出:
- 可定位的 artifact 路径
- observed evidence（不是 worker 口述）
- 如果某步用 mock，必须在 handoff 中明确标注
```

## Acceptance Criteria

这个 phase 通过，必须满足：

```
[ ] 13 个步骤全部走通（mock 可以，但必须标注）
[ ] 至少 1 个步骤使用 real Claude Code worker
[ ] 至少 1 个步骤使用 real LLM planning
[ ] 至少 1 轮 Phase 22 auto-repair 成功
[ ] 至少 1 个 milestone gate 正常暂停并等待审批
[ ] project ask 至少回答 2 个不同类型的问题
[ ] project resume 正确恢复状态
[ ] audit report 完整可读，包含所有环节
[ ] SystemIssue detection 在 self-check 中运行且不误报
[ ] 最终 handoff 清楚标注真实 vs mock 的边界
```

## Manual Smoke Test

如果完整 13 步太耗时或 API key 限制：
- 运行最长的可行子集
- 明确标注哪些步是真实执行、哪些步是 mock
- 被 mock 跳过的步在 known_limitations.md 中记录

最小可接受范围：
```
必须真实:
- project start + session 创建
- 至少一个 real Claude Code worker 执行
- 至少一轮 auto-repair
- project ask 回答
- project resume
- audit report

可以 mock:
- 多个 worker 并行（如果环境不支持）
- LLM planning（如果 API key 不可用，用 deterministic planner）
- Reviewer（至少用 RuleBasedReviewer）
```

## Quality Bar

```
一个认真的人能从 audit report 回答:

- 这个项目做了什么？
- 计划是怎么出来的？
- 每个 milestone 改了哪些文件、测试结果如何？
- 哪个环节出过问题、怎么修的？
- 每个 milestone 是谁批准的？
- 为什么选了这个方案而不是别的？
- 现在项目处于什么状态、下一步该做什么？

如果答案需要读源代码才能知道，则验收不通过。
```

## Definition Of Done

```
- 13 步验收场景全部走通或明确标注 mock
- 真实执行部分覆盖: real worker, real repair, real resume, real ask
- phase 22-27 的能力在完整链路中协同工作
- audit report 完整可读
- known_limitations.md 更新，记录 v2 验收状态
- handoff 明确说明: 什么是真的、什么是 mock 的、还剩什么
```

## Required Final Explanation To User

```
Phase 28 不是做新功能。是把 Phase 22-27 的所有能力串在一起跑一遍。

这个 phase 通过的时候，AAO 就不再是一个"控制框架"了。
它是一个能接项目、做调研、出方案、等你确认、派工人干活、
独立审查、自动修 bug、按模块验收、能续跑、能回答追问的——
项目协作者。

这是 AAO v2 的最终验收。
```

## Claude Code Instruction

Read `CLAUDE.md` 和这个 spec。Phase 28 是验收阶段，不是功能阶段。
不做新功能。串链路。发现问题修集成缺口。真实汇报什么通了、什么没通。
