# 018 Tool Permission And Trust Hierarchy

## 背景

当前项目已经有：

- `ToolRegistry`
- `Guardrails v1`
- 可插拔 agent

但之前 tool 的控制还停留在：

- agent 只要声明了某个 tool 名字，就能调用

这意味着“允许使用某工具”和“是否有足够权限使用该工具”还没有分开。

## 问题

如果没有最小信任层级，后面一旦接入更强工具，例如：

- 文件写入
- 浏览器控制
- 代码执行

那工具调用边界会不够清楚。

## 决策

新增两层最小权限语义：

### Agent 侧

- `trust_level`

当前支持：

- `low`
- `medium`
- `high`

### Tool 侧

- `risk_level`

当前支持：

- `low`
- `medium`
- `high`

`BaseAgent.run_tool()` 在调用前会比较二者等级。

如果：

- `agent trust_level < tool risk_level`

就直接拒绝执行。

## 为什么这样做

### 1. 把“会不会用”和“能不能用”分开

之前：

- 只要 agent 声明过工具，就默认能用

现在：

- agent 声明过工具，且信任级别够，才能真正执行

### 2. 为后续更强工具做铺路

这一步虽然现在只作用在 mock tool 上，但后面接：

- file io
- browser
- python exec

时就不会从零开始补安全边界。

### 3. 让 trust hierarchy 进入 runtime

这次不是只在文档里说“human > supervisor > worker”，而是先把最小工具权限边界变成真正工作的 runtime 规则。

## 当前边界

当前仍是最小版本：

- 只限制 tool call
- 还没有完整 role-based policy
- 还没有 human approval upgrade path

但这已经足够让系统具备最小的“信任级别 <-> 工具风险级别”控制能力。

## 影响

- ToolRegistry 更接近完整生态平台层
- worker 层调用高风险能力时有了明确边界
- 后续继续做：
  - safety review
  - trust hierarchy
  - tool permission policy

会更顺
