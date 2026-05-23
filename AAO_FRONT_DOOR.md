# AAO Front Door

AAO Front Door 是新会话和新任务的轻量入口。它不是完整执行流程，
只回答一个问题：这次任务应该直接做，还是交给 AAO 控制层？

## 新会话启动

每次新开 Claude Code / Codex 会话，先做这四步：

1. 读 `CLAUDE.md` 和本文件。
2. 跑 `git status --short`，确认当前工作区状态。
3. 对当前任务跑：

   ```bash
   python -m orchestrator front-door "<task>"
   ```

4. 没有读过相关源码、测试或 artifact 前，不要说“没有这个功能”、
   “已经接通”、或“测试通过”。

## 分流规则

| 任务 | 入口 | 行为 |
| --- | --- | --- |
| small | direct | 简单问答、解释、低风险小改动。Claude Code / Codex 直接做，但要读相关源码后再下结论。 |
| medium | controlled | 多文件、小特性、bugfix、需要测试或 evidence。走 AAO controlled。 |
| large | project_session | 多阶段、可恢复、多 worker、架构改造、长期任务。走 project session。 |

## small

例子：

- 解释一个函数。
- 看一个小测试失败原因。
- 修改一两行低风险文案。

推荐行为：

```text
读相关源码 -> 直接回答或小改 -> 跑必要的小范围检查
```

## medium

例子：

- 修 worker timeout，并补测试。
- 改 evidence 校验。
- 修改几个文件并要求测试证明。

推荐命令：

```bash
python -m orchestrator ask "<task>" --worker-mode claude-code --approve
```

当前语义：

- medium 默认是 controlled 单任务执行。
- 默认不需要多模型 Planning Council 讨论。
- 需要 worker packet、observed evidence、control decisions、audit report。
- 如果涉及 ControlPlane、worker bridge、evidence integrity、policy 等高风险核心链路，可以升级到 large/project_session。

## large

例子：

- 继续把 AAO 做成完整项目协作控制层。
- 跨模块 runner / project session / repair / resume 改造。
- 多阶段、多 worker、需要人工 gate 的任务。

推荐命令：

```bash
python -m orchestrator project status
python -m orchestrator project start "<task>" --planning-mode llm
python -m orchestrator project continue --worker-mode claude-code
```

如果已有 active project，优先 `project status`，再 `project continue`。

## 禁止假结论

这些话只有在有源码、测试或 artifact 证据时才能说：

- “没有这个链路。”
- “已经端到端接通。”
- “worker 真的执行了。”
- “AAO 独立收集了 evidence。”
- “测试已经通过。”

没有证据时，只能说：

```text
我还没确认。下一步要读 <file> / 跑 <command> / 看 <artifact>。
```

