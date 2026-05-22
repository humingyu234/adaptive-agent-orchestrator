# AAO Known Limitations

This document exists to be honest about what AAO does and does not do.
Transparent limitations build more trust than hidden gaps.

## Scope

**AAO is a personal open-source engineering system and proof-of-work
project.**  It is not a claimed production SaaS deployment, not a
commercial product, and not a service with uptime guarantees.

## Architecture Limitations

### Worker dependency
AAO is a control layer, not a worker.  It requires a separately
configured worker (Claude Code, LLM provider, or test worker) to actually
execute tasks.  The control layer can verify, block, and recover — but it
cannot do the work itself.

### LLM/Claude Code dependency
Real task execution through Claude Code workers depends on:
- Claude Code being installed and logged in
- Local tooling and filesystem permissions
- Network access for LLM API calls

The golden scenario suite and demo scripts run without these dependencies
by using deterministic fake workers.  But real-world usage requires real
workers.

### Optional integrations
Some integrations are optional adapters and may not be installed by
default:
- LangGraph (orchestrated mode runner)
- Tavily/Serper/DuckDuckGo (real search tools)
- External LLM providers (OpenAI, Anthropic, DeepSeek, GLM, Kimi, Ollama)

These adapters work when installed, but AAO core is designed to be
functional without them.

## Control Limitations

### Human review needs a human
AAO can detect when human review is needed and pause execution.  It
cannot make the judgment itself.  The human must read the question,
evaluate the context, and decide.

### Golden scenarios prove contracts, not completeness
The 22 golden scenarios prove that the control layer correctly handles
the staged failure modes.  They do not prove that AAO catches every
possible real-world failure.  The space of agent failures is unbounded;
the scenarios cover the high-signal, high-frequency categories.

### Evidence requires runtime capture
AAO can verify whether evidence exists, but it can only verify evidence
that the runtime actually captures.  If a worker or runner does not
record test output, file diffs, or command logs, AAO will correctly
report them as missing — which is honest but means the system depends on
worker discipline.

### Policy enforcement is as strong as the policy file
Declarative policy (YAML) controls what AAO checks.  If the policy file
is incomplete or misconfigured, AAO will not catch what it wasn't asked
to catch.  Default policies are safe but may need tuning for specific
workflows.

## Performance Limitations

### Control overhead
AAO adds evaluation, guardrail, policy, evidence, and recovery checks to
every step.  For small tasks, this overhead may not be justified.  The
task router (Phase 9) can route small tasks to `off` or `log` mode to
avoid unnecessary control overhead.

### Not optimized for production throughput
AAO is designed for correctness and auditability, not for high-throughput
production workloads.  It has not been benchmarked under concurrent load
or large-scale deployment.

## Testing Limitations

### Test coverage is focused on control contracts
Tests focus on the control layer's decisions, evidence handling, failure
classification, and recovery behavior.  Some utility code, CLI output
formatting, and optional integration adapters have lighter coverage.

### Integration tests with live Claude Code are manual
The Claude Code worker bridge (Phase 18) has unit tests and a documented
acceptance path (docs/acceptance.md). Integration tests with live Claude
Code still require a real Claude Code session, which is inherently
non-deterministic and requires user interaction.  The acceptance test
layer exercises the full control path with deterministic fake workers.

## v2 Collaboration Acceptance (Phase 22-28)

Phase 28 completes the v2 project collaboration feature set (Phases 22-27).
The acceptance tests exercise a 13-step end-to-end scenario:

1. project start → 2-4. execute milestone + pause → 5. gate paused →
6. ask questions → 7. approve milestone → 8-11. continue + approvals →
12. resume (process restart) → 13. complete audit trail

**What's real:**

- Control path: project session, milestone lifecycle, approval gates,
  decision logging, audit trail — all exercised through actual CLI handlers
- Persistence: sessions, milestones, decisions, approvals, run links all
  survive store recreation (simulates process restart)
- Gates: approved milestones activate the next pending milestone;
  unapproved milestones block progress
- Self-check: 6 categories of system issue detection run against live
  session state; protected-path proposals are blocked

**What's mock:**

- Workers: deterministic fake workers (no real Claude Code subprocess)
- Planning: deterministic planner (no real LLM planning council)
- Evidence: fake evidence artifacts produced by fake workers

**What remains (not in scope for v2):**

- Real multi-worker parallel execution (multi_worker.py exists but not
  wired into the mainline project flow)
- Real Claude Code worker bridge in the project flow
- Real LLM planning council in the project flow
- LangGraph runner integration for orchestrated mode

## What AAO Is Not

- **Not a Claude Code replacement** — AAO controls and audits; Claude Code
  (or another worker) executes
- **Not a LangGraph replacement** — LangGraph is an optional runner, not
  the control brain
- **Not a generic all-in-one agent framework** — AAO focuses on control,
  not on being every AI tool
- **Not a tracing/monitoring platform** — Live Watch is for runtime
  visibility, not for production observability at scale
- **Not an eval SaaS** — RegressionCompare and golden scenarios are for
  development-time proof, not for continuous production evaluation
- **Not a production SaaS** — No uptime guarantees, no SLA, no paid
  support

## Honest Assessment

AAO demonstrates that an AI-assisted engineering system can have:
- Evidence-backed completion verification
- Policy-enforced safety gates
- Bounded recovery from failures
- Structured planning with risk review
- Honest audit reporting

It does **not** demonstrate production readiness, enterprise scale, or
commercial viability.  Those are different problems that require
different engineering investment.

**If you're evaluating AAO for hiring or collaboration:** judge it on
the quality of the control architecture, the honesty of the tests, and
the clarity of the demo — not on production metrics that don't exist yet.
