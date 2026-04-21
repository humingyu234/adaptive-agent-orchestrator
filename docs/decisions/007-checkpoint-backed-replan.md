# Checkpoint-Backed Replan

## 这份记录是做什么的

这份记录沉淀的是 `adaptive-agent-orchestrator` 在 Phase 2A 的关键升级：

- 为什么最小 `re_plan` 不能长期停留在“清空状态然后重跑”
- 为什么要把 checkpoint 从内存概念升级成 runtime 一等产物
- 为什么这一阶段优先做 checkpoint-backed replan，而不是直接扩更复杂的 Supervisor / Memory / L2-L3

---

## 1. 问题

在 `006-minimal-replan-signal.md` 之后，系统已经能做到：

- `Supervisor` 判断规划不稳
- 发出 `suggested_target=planner`
- 发出 `suggested_action=re_plan`
- `Scheduler` 回到 `planner`

但当时的实现本质上还是：

- 清掉 `plan`
- 清掉 `raw_documents`
- 清掉 `summary`
- 重新开始

这能证明控制信号存在，但还不能证明 runtime 真正具备：

- 可恢复性
- 可审计性
- 回滚依据

如果继续停留在这种“裸重跑”状态，后续会出现几个问题：

- replan 没有可靠恢复点，状态回退全靠手动清字段
- 无法向上层说明“系统到底回到了哪里”
- 后续接 `Human review gate` / `Memory` / 更复杂审计时，会缺少 durable runtime 基础

---

## 2. 决策

Phase 2A 正式把最小 `re_plan` 升级成：

**checkpoint-backed replan**

本次实现包括：

- `StateCenter` 新增基础 `save/load`
- checkpoint 从内存列表升级为磁盘持久化产物
- `Scheduler` 每个成功步骤后自动创建 runtime checkpoint
- 当 `Supervisor` 对 `planner` 发出 `re_plan` 时：
  - 不再只清状态
  - 而是回滚到目标节点之前的最近可靠 checkpoint
- 运行结束后自动生成：
  - persisted state
  - `ConvergenceReport`

---

## 3. 为什么这样取舍

### 为什么先做 checkpoint-backed replan

因为它正好卡在：

- 当前最小控制闭环已经存在
- 下一步最自然的 runtime 强化点

它不是另起新层，而是把已有闭环从“概念成立”推进到“运行时基础设施成立”。

### 为什么不直接先做 `Human review gate`

因为 `Human review gate` 更像生态上层能力。

如果底层 runtime 还没有：

- 可保存状态
- 可回滚状态
- 可输出收敛报告

那人类介入之后能看到的仍然只是“当下状态”，而不是“过程与恢复点”。

### 为什么不直接先做 `MemoryManager`

因为 `Memory` 依赖的前提之一就是：

- 当前状态结构稳定
- checkpoint / state snapshot 边界清楚

如果 runtime 本身还没有 durable state 语义，Memory 设计会很容易漂。

---

## 4. 当前实现边界

本次升级仍然有明确边界。

已经做到：

- 基础 checkpoint 持久化
- 完整 state save/load
- planner `re_plan` 时按 checkpoint 回滚
- 最小 `ConvergenceReport`

还没有做到：

- 完整 checkpoint store 抽象层
- 多分支 checkpoint 策略
- checkpoint 选择策略的更复杂优化
- human-approved rollback
- checkpoint 与长期 Memory 的联动

也就是说，这次不是“完整 durable runtime”，而是：

**先把 checkpoint / save-load / replan 真正接成可运行闭环。**

---

## 5. 后续演化

最自然的下一步是：

1. 增强 `ConvergenceReport` 字段与执行审计
2. 引入 `Human review gate`
3. 设计 `MemoryManager v1`
4. 用第二个 workflow 验证 checkpoint 机制没有写死在当前 research 流程

---

## 6. 面试 / 博客表达

### 一句话版本

我们没有让 `re_plan` 停留在“清空状态然后重跑”的 demo 级实现，而是把它升级成了 checkpoint-backed replan，让 runtime 开始具备真正的恢复点、审计产物和收敛报告。

### 稍展开版本

在多智能体系统里，`re_plan` 不是一句“回到 planner 重新做”就够了。真正有价值的是，系统要知道自己回退到了哪个可靠点，回退后保留什么、丢弃什么、留下什么审计证据。Phase 2A 的核心价值，就是把最小控制信号进一步变成 durable runtime 能力，为后续的 Human review、Memory 和更强评估层打基础。
