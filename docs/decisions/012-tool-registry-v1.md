# ToolRegistry v1

## 这份记录是做什么的

这份记录沉淀的是 `adaptive-agent-orchestrator` 在 runtime 主干基本成形之后，对工具层做出的第一版正式抽象：

- 为什么现在要引入 `ToolRegistry v1`
- 为什么当前先把 mock search context 能力从 agent 内部抽出来
- 为什么这一步要同时补 agent 的工具声明能力

---

## 1. 问题

在补完：

- checkpoint-backed replan
- human review gate
- MemoryManager v1
- 第二个 workflow
- execution audit

之后，系统已经越来越像真正的 runtime 内核。

但这时还有一个明显问题：

**工具能力还没有正式进入统一注册层。**

以当前实现为例，`SearchAgent` 里仍然直接内置了 mock context 生成逻辑。  
这对最小 demo 没问题，但对完整生态 v2 来说有几个风险：

- agent 和具体能力耦合太紧
- 后续想接真实搜索、浏览器、文件、代码执行时，没有统一入口
- 无法明确区分“agent 做决策”与“tool 提供能力”

---

## 2. 决策

当前先补一个最小但正式的 `ToolRegistry v1`：

- 新增 `ToolSpec`
- 新增 `ToolRegistry`
- 增加默认工具注册函数 `build_default_tool_registry()`
- 当前先注册一个工具：
  - `mock_search_context`

同时：

- `AgentConfig` 新增 `tools`
- `BaseAgent` 新增 `run_tool()`
- `SearchAgent` 通过 `ToolRegistry` 调用 `mock_search_context`

也就是说：

**agent 现在要显式声明自己能用什么工具，工具能力本身则从 agent 体内抽离出来。**

---

## 3. 为什么这样取舍

### 为什么现在就要做 ToolRegistry

因为完整生态 v2 里，Tool Registry 是正式一层，不是细节补丁。

而且当前阶段已经很适合接它：

- agent 契约已经存在
- 第二个 workflow 已经证明 runtime 不只跑一种任务
- report 和 audit 也已经开始成熟

这时补工具层，会让架构更完整，而不是更乱。

### 为什么先从 `mock_search_context` 开始

因为当前最明显的隐式工具行为就藏在 `SearchAgent` 里。

先把这一块抽出来，有几个好处：

- 改动范围小
- 最容易看出收益
- 能直接验证 agent/tool 解耦是否顺畅

这一步的目的不是“一次接完所有工具”，而是：

**先把工具层的接口立住。**

### 为什么要让 agent 显式声明 `tools`

因为如果没有工具声明，后面工具层很容易又退化成：

- agent 想调什么就直接调什么

而显式声明以后，系统开始具备：

- 权限边界雏形
- agent/tool 契约
- 更清晰的审计能力

---

## 4. 当前实现边界

已经做到：

- 工具注册表存在
- agent 可以声明工具
- `SearchAgent` 已改为通过注册表取上下文能力
- report 能看到当前 workflow 的 declared tools 和工具痕迹

还没做到：

- 多种真实工具接入
- tool-level guardrails
- tool permission hierarchy
- tool adapters / provider abstraction
- scheduler 级别的 tool routing

所以当前更准确的定位是：

**ToolRegistry v1 已经把工具层正式拉出来了，但还只是第一步。**

---

## 5. 后续演化

最自然的下一步是：

1. 增强 Memory，让 tool usage 也能进入更长期经验沉淀
2. 设计 `LLMClient v1`
3. 补 `Guardrails v1`
4. 后续再接真实 `web_search`、`file_io`、`python_exec` 等工具

---

## 6. 面试 / 博客表达

### 一句话版本

我们没有继续把能力硬塞在 agent 体内，而是开始把工具能力抽到统一注册表，让 agent 通过显式声明和统一入口使用工具，为后续的真实工具接入和 guardrail 打基础。

### 稍展开版本

一个运行时内核如果想支持越来越多的 agent，就不能让每个 agent 自己偷偷长工具逻辑。这一步的价值，就是把“能力”从 agent 里拆出来，建立独立的 Tool Registry，并让 agent 通过显式声明来使用工具。这样系统后面才更容易扩真实搜索、文件操作、代码执行和安全边界。
