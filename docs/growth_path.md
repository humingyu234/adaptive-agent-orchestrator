# 1 到 2 年成长路径

## 这份文档记录什么
这份文档记录的是：基于当前两条主线项目，未来 1 到 2 年应该怎样成长、阶段目标是什么、每个阶段最重要的任务是什么。

这不是空泛的职业规划，而是围绕当前实际在做的三条线展开：

- `deep_research_agent`
- `adaptive-agent-orchestrator`
- future evaluate system

---

## 当前主线定位

先把一句话定住：

**未来最值得持续积累的方向，是 workflow-native agent infrastructure。**

也就是把这些能力一起长起来：

- agent workflow
- multi-agent orchestration
- evaluate / regression
- reliability / degradation
- files-as-context / agent-native working style

这条路线的意义在于：

- 不是只会调 prompt
- 不是只会拼 demo
- 也不是单纯走传统后端路线
- 而是在做真正会被很多 agent 系统反复需要的底层能力

---

## 阶段 1：现在到未来 3 个月

## 目标

**把当前项目线拉直，不要散。**

### 最重要的任务

#### 1. 稳住 `deep_research_agent`
这个项目仍然是当前最强、最像成品的项目。

这一阶段它的目标不是无限加功能，而是：

- 更稳
- 更能展示
- 更能解释
- eval 更像系统

#### 2. 让 `adaptive-agent-orchestrator` 跑出最小闭环
不要求很大，但一定要真的能跑。

至少要做到：

- `Scheduler`
- `StateCenter`
- `Evaluator(L1)`
- 一个最小 workflow

#### 3. 把 evaluate 路线显式化
也就是：

- judge / taxonomy / compare 的边界清楚
- 评估抽离路线不再只存在聊天记录里
- evaluation layer 方向开始被项目文档固定下来

### 这一阶段在长什么

- 项目收敛能力
- 系统化表达能力
- 从应用里抽 infra 的能力

---

## 阶段 2：未来 3 到 6 个月

## 目标

**让作品集从“一个项目很强”变成“有一条完整技术路线”。**

### 最重要的任务

#### 1. 让 `adaptive-agent-orchestrator` 接第二个 workflow
例如：

- coding workflow
- support workflow

这样才能证明：

- 这个引擎不是只为 `deep_research` 写死的小框架

#### 2. evaluate system 进入 Phase 0 / Phase 1
也就是：

- `detect_failure_tags()` 抽成 judge
- `cases / runners / judges / taxonomy` 边界更清楚
- 至少形成项目内 evaluation layer 草稿

#### 3. 开始练更成熟的工作方式
不再只靠单对话框推进，而开始稳定使用：

- 文件化上下文
- 1 主 1 辅
- role-based task split

### 这一阶段在长什么

- multi-project coherence
- orchestrator mindset
- agent team workflow mindset

---

## 阶段 3：未来 6 到 12 个月

## 目标

**让自己从“做过 agent 项目的人”变成“有清晰 agent infra 叙事的人”。**

### 最重要的任务

#### 1. 形成 2 到 3 个互相关联的代表作
理想结构：

- `deep_research_agent`
  - workflow + eval + reliability
- `adaptive-agent-orchestrator`
  - orchestration runtime
- future evaluate layer / `agent-eval`
  - judge / taxonomy / regression

#### 2. 每个项目都能一句话讲清
例如：

- `deep_research_agent`：一个 research workflow 系统，重点在 eval 和 reliability
- `adaptive-agent-orchestrator`：一个轻量多 Agent 运行时，重点在 runtime evaluation 和 adaptive control
- `agent-eval`：一个 workflow-native 评估层，重点在 failure taxonomy 和 regression compare

#### 3. 开始能讲“系统之间的关系”
也就是不把 3 个项目讲成孤立作品，而是：

- 应用层
- 引擎层
- 评估层

相互支撑、相互验证。

### 这一阶段在长什么

- 技术叙事能力
- 系统分层能力
- 求职时最稀缺的“我到底擅长什么”的表达能力

---

## 阶段 4：未来 1 到 2 年

## 目标

**把自己从“有潜力”推进到“有明显方向感和作品密度”的状态。**

### 可能形成的个人形象

不是：

- 只会调 API 的 AI 应用开发者

也不是：

- 纯八股型后端工程师

而是：

**懂 agent workflow、orchestration、evaluation、reliability 的 agent systems builder。**

---

## 未来 1 到 2 年最值得积累的 5 个能力

### 1. Workflow Design（工作流设计）
会设计：

- agent 步骤
- 状态流
- fail path
- degrade path

### 2. Evaluation（评估）
会做：

- quick checks
- variant eval
- taxonomy
- compare / regression

### 3. Orchestration（编排）
会做：

- shared state
- scheduler
- retry / re-plan
- runtime control

### 4. Working Style（工作方式）
会做：

- 文件化上下文
- role-based agent collaboration
- 从 1 主 1 辅过渡到多 Agent 团队模式

### 5. Technical Narrative（技术叙事）
会讲清：

- 每个项目在整体系统里的位置
- 为什么做这个
- 解决了什么真实问题

---

## 最不该做的事

### 1. 不要同时追太多方向
当前主线已经很清楚，不要再开很多无关项目把注意力打散。

### 2. 不要被“手写代码没那么强”吓住
当前真正的竞争力不是卷低级手写，而是：

- 系统理解
- workflow
- eval
- orchestration

### 3. 不要把自己逼成万能平台作者
正确路线是：

- 真实问题驱动
- 小步收敛
- 逐步抽象

而不是一开始就造宇宙级框架。

---

## 当前正式结论

当前未来 1 到 2 年最应该坚持的路线是：

- 用 `deep_research_agent` 稳住应用和 eval
- 用 `adaptive-agent-orchestrator` 长出编排内核
- 逐步把 evaluate system 抽出来
- 最终形成“应用层 + 引擎层 + 评估层”这条清晰的 agent infra 路线

---

## 一句话总结

未来 1 到 2 年最重要的，不是证明自己年纪轻也能做大项目，而是把自己稳定地长成一个懂 agent systems 的 builder。
