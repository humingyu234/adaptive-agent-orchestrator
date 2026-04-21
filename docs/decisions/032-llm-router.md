# LLM Router - 自动分流入口

## 1. 问题

`ask` 命令如何根据用户自然语言自动选择合适的 workflow？

痛点：
- 用户需要手动指定 workflow 路径
- 关键词规则匹配不够智能
- 无法理解复杂意图

它在整个系统里的位置：
- 属于 `ask` CLI 命令入口
- 在 Scheduler 执行前进行路由决策
- 与 LLMClient 配合实现智能路由

---

## 2. 决策

实现 LLM Router，通过 LLM 分类用户意图并自动选择 workflow。

核心函数：
- `_route_workflow_with_llm()` - LLM 路由函数
- `_resolve_workflow_for_ask()` - 主路由入口（LLM + fallback）
- `_infer_workflow_path()` - 规则路由 fallback

支持的 workflow：
- `deep_research` - 研究/分析任务
- `deep_research_supervised` - 需要主管审核
- `deep_research_human_review` - 需要人工确认
- `customer_support_brief` - 客服/工单

路由优先级：
1. LLM router（非 mock provider 时）
2. 规则路由 fallback

---

## 3. 取舍

### 备选方案

1. **纯关键词规则匹配**
   - 优点：简单、无外部依赖
   - 缺点：无法理解复杂意图
   - 作为 fallback 保留

2. **LLM 分类器（采用）**
   - 优点：理解自然语言意图
   - 缺点：依赖 LLM 可用性
   - 采用原因：更智能的用户体验

### 牺牲

- LLM 调用增加延迟
- 依赖 LLM 可用性

### 换来

- 更智能的意图理解
- 更好的用户体验
- 可扩展的分类能力

---

## 4. 当前边界

**未覆盖：**
- 更多 workflow 类型
- 多轮对话澄清意图
- 用户偏好学习

**保持简单：**
- 只支持 4 种 workflow
- 单次分类，无对话
- 严格匹配，拒绝模糊输出

---

## 5. 后续演化

- 支持更多 workflow 类型
- 增加置信度阈值
- 支持用户反馈修正

---

## 6. 面试 / 博客表达

### 一句话版本

LLM Router 通过 LLM 分类用户意图，自动选择合适的 workflow。

### 稍展开版本

LLM Router 是一个智能路由模块，通过 LLM 理解用户自然语言意图，自动选择 deep_research、customer_support_brief 等合适的 workflow。它支持严格匹配、引号归一化，并在 LLM 不可用时自动 fallback 到规则路由。
