# 025 LLM Provider Abstraction

## Background

The project needs to support multiple LLM backends, for example:

- GLM
- OpenAI-compatible providers
- Codex CLI
- Ollama
- DeepSeek

The old `LLMClient` only covered mock mode. That was fine for local testing, but not enough for real provider integration.

## Decision

We introduce a provider abstraction layer and keep `agent` and `llm` separated.

- `agent` describes the role and responsibility
- `llm` describes which model capability that role uses at runtime

This allows:

- global provider/model overrides
- per-agent provider/model overrides
- future policy-based automatic model routing

## CLI shape

Global override:

```bash
py -m orchestrator run --workflow workflows/deep_research.yaml --query "xxx" --llm glm --model GLM-5.1
```

Single-agent override:

```bash
py -m orchestrator agent --name planner --query "xxx" --llm codex --model o3
```

Per-agent override:

```bash
py -m orchestrator run --workflow workflows/deep_research.yaml --query "xxx" --agent-llm planner=glm:GLM-5.1,supervisor=codex:gpt-5.4,search=deepseek:deepseek-chat
```

`--agent-llm` format:

```text
agent_name=provider:model
```

If `:model` is omitted, only the provider is overridden.

## Why

This keeps the architecture layered:

```text
CLI / Workflow / Scheduler
        -> Agent
        -> LLMClient
        -> Provider
        -> Real model service
```

Benefits:

- workflows do not bind directly to one provider
- agents do not hardcode one backend
- later we can add cost/quality based routing

## Current status

Done:

- provider abstraction layer
- CLI global override support
- per-agent override plumbing

Still pending:

- production-ready provider setup docs
- automatic model assignment by role / cost / quality
- stronger provider health checks
