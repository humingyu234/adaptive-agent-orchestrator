# Human Review Gate

## 这份记录是做什么的

这份记录沉淀的是 `adaptive-agent-orchestrator` 在 Phase 2A 之后补上的下一层控制能力：

- 为什么系统不能在 `supervisor` 之后默认直接结束
- 为什么要把 `Human review gate` 作为 runtime 内的正式节点
- 为什么当前先做“等待人工确认”的最小闭环，而不是一口气做完整交互式审批系统

---

## 1. 问题

在补完 checkpoint-backed replan 之后，系统已经具备：

- Worker 执行
- Evaluator(L1)
- Supervisor 结构化修正建议
- checkpoint-backed replan

但这时还有一个明显缺口：

**系统还没有一个正式的人工拍板门。**

如果 `supervisor` 给出“当前结果可接受”，runtime 就会直接结束为 `completed`。

这对于最小 demo 是够的，但对完整生态方向来说还不够，因为：

- 人类应该保留最高权限
- 某些最终输出不应该默认自动放行
- 后续 approval gate / live interrupt / trust hierarchy 都需要有一个明确的人工接管点

---

## 2. 决策

当前先补一个最小版本的 `Human review gate`：

- 新增 `HumanReviewAgent`
- 在 workflow 中允许 `supervisor -> human_review`
- `human_review` 输出结构化审查包 `human_review_gate`
- 当其输出 `decision=await_human` 时，runtime 进入：
  - `needs_human_review`

也就是说：

- 系统会走到人工门口
- 会把当前结果、建议和上下文打包好
- 但不会擅自继续

---

## 3. 为什么这样取舍

### 为什么要把它做成正式节点

因为如果人工审核只写在文档里，而不进入 runtime，后续就会出现：

- 状态里没有正式记录
- 执行轨迹里没有人工门
- workflow 看起来支持人工介入，实际上运行时没有落点

做成正式节点以后，人工接管就从“概念层”变成“流程层”。

### 为什么当前先停在 `await_human`

因为这阶段最重要的不是把交互 UI 做满，而是先把 runtime 语义做对：

- 知道什么时候需要人工拍板
- 知道此时不能默认继续
- 知道要留下结构化审查包

也就是说，当前优先做的是：

**runtime 先会停。**

而不是：

**runtime 先把所有审批界面和双向交互做满。**

### 为什么不直接把人工决策写死成 approve

因为那样等于没有 gate。

人工门的核心价值恰恰在于：

- 系统必须承认“这里需要人”
- 系统必须允许自己暂停

---

## 4. 当前实现边界

已经做到：

- workflow 可以显式插入 `human_review`
- `human_review` 会输出结构化审查包
- runtime 会停在 `needs_human_review`

还没做到：

- 真正交互式 approve / reject 输入
- human reject 后的回流路由
- approval UI / CLI resume
- trust hierarchy 与权限体系完整联动

所以当前更准确的定位是：

**最小 Human review gate 已经成立，但完整审批系统还没做满。**

---

## 5. 后续演化

最自然的后续步骤是：

1. 增加 resume / approve / reject 的 CLI 或 API 入口
2. 让 human decision 能回流到 scheduler 路由
3. 和 checkpoint / state save-load 结合，支持人工批准后继续执行
4. 再和 `TrustHierarchy`、`SafetyGuard` 接起来

---

## 6. 面试 / 博客表达

### 一句话版本

我们没有把 Human review 只停留在设计图里，而是先把它做成了 runtime 里的正式 gate：系统会在 supervisor 之后生成结构化人工审查包，并停在 `needs_human_review`，承认这里必须由人拍板。

### 稍展开版本

很多系统会说“人类保留最高权限”，但运行时里并没有真正的停靠点。我们这一步的重点，就是先把人工介入点做成正式流程节点，让系统能够明确地说：到这里我先停，不擅自越过人类审批。这为后续 approval gate、resume、trust hierarchy 和安全边界打了基础。
