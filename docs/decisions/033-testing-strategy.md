# 033 — 测试策略

## 背景

当前测试主要验证"产物存在"（assertIn、assertIsNotNone、assertTrue），不验证行为正确性。随着项目从骨架走向完整生态，需要更明确的测试分层和覆盖标准。

## 决策

### 三层测试

| 层 | 名称 | 覆盖范围 | 工具 | 目标数量 | 运行频率 |
|---|------|---------|------|---------|---------|
| 1 | 单元测试 | 单个模块：Evaluator、FailureTaxonomy、Guardrails、MemoryManager、StateCenter、Registry | unittest | 每个模块 3~10 个 | 每次改动 |
| 2 | 集成测试 | 端到端 workflow：各类型 workflow 完整跑通，验证产物正确性 | unittest + mock LLM | 每个 workflow 至少 1 个 | 每次改动 |
| 3 | 回归测试 | 真实 LLM 跑 workflow，比较前后运行质量 | real provider | 关键 workflow 3~5 个 | 改关键模块时 |

### Smoke test 断言标准

当前 smoke test 只验证"字段存在"，应升级为验证"字段内容正确"：

- **不只要** `self.assertIn("plan", output)` → **还要** `self.assertGreater(len(plan["sub_questions"]), 0)`
- **不只要** `self.assertIsNotNone(report)` → **还要** 验证 supervisor 在 planner 失败时给出正确的 suggested_target
- **不只要** 验证 report 生成 → **还要** 验证 failure_summary 的 category 和 severity 正确

### Mock 策略

- **单元测试**：所有外部依赖 mock（LLM、工具、文件 I/O）
- **集成测试**：LLM 用 MockProvider，文件 I/O 用 tempfile，其余真实
- **回归测试**：全真实（真实 LLM provider、真实工具），但不在 CI 里跑，手动触发

### 测试文件组织

```
tests/
├── unit/
│   ├── test_evaluator.py
│   ├── test_evaluator_l2.py
│   ├── test_failure_taxonomy.py
│   ├── test_guardrails.py
│   ├── test_memory_manager.py
│   ├── test_state_center.py
│   └── test_tool_registry.py
├── integration/
│   ├── test_research_workflow.py
│   ├── test_supervised_workflow.py
│   ├── test_human_review_workflow.py
│   └── test_support_workflow.py
└── regression/
    └── test_real_llm_quality.py
```

当前 `tests/test_runtime_smoke.py`（64KB）作为过渡保留，逐步拆分到上述目录。

## 理由

- 当前 2 个测试文件已经很难定位失败原因
- 只验证"产物存在"无法发现行为退化
- 分层后可以更快判断问题在哪一层
- mock 策略明确后不会出现"测不过是因为 LLM 返回不合法 JSON"的噪音
