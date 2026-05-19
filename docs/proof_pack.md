# AAO Proof Pack

## 1. Problem

AI-assisted engineering workflows have systemic failure modes that raw
LLM capability does not solve:

| Failure mode | What happens | Why it matters |
|---|---|---|
| False completion | Worker says "done" but no evidence exists | Tasks marked complete with no verification |
| Risky automation | Worker changes secrets, configs, credentials | Dangerous changes pass silently |
| Infinite retry | Worker retries the same failure forever | Wastes tokens, time, and trust |
| Plan-execution gap | Complex tasks executed without a reviewed plan | Drift, missed requirements, wrong scope |
| Dishonest reporting | System claims success without backing evidence | Audit trail is fiction |

These failures are not about model quality.  They are about **control** —
and better models alone do not fix them.

## 2. AAO Answer

AAO is a **runtime control layer** that sits between the orchestrator and
the worker:

```
Task → Planning → Policy → Execution → Evidence → Guardrails
     → Failure Classification → Recovery → Human Review → Audit Report
```

AAO controls **six dimensions** of agent execution:

1. **Evidence** — observed files/output beat worker claims
2. **Policy** — protected files, high-risk tools, required checks
3. **Recovery** — bounded retry, explicit escalation, no infinite loops
4. **Planning** — structured plans with risk review before execution
5. **Human Review** — gates before risky actions, not after
6. **Audit** — honest reports with evidence, failure, and recovery sections

## 3. Proof Table

| Claim | Proof |
|---|---|
| Missing evidence blocks false completion | Golden scenario #2 + Demo A |
| Worker claims don't count as observed evidence | Golden scenario #3 |
| Memory hints are advisory, not evidence | Golden scenario #4 |
| Protected file requires human review | Golden scenario #5 + Demo B |
| Reviewer cannot write files | Golden scenario #6 |
| Guardrail blocks secret leak | Golden scenario #7 |
| Test failure → bounded retry → replan | Golden scenario #8 |
| Failure category is explicit, not inferred | Golden scenario #9 |
| Repeated tool calls detected and blocked | Golden scenario #10 |
| Planning catches missing evidence | Golden scenario #11 |
| User rejected plan stops execution | Golden scenario #12 |
| High-risk task requires human review | Golden scenario #13 |
| Complex task produces full PlanContract | Golden scenario #14 + Demo C |
| Audit report has evidence + failure + recovery | Golden scenario #15 |
| Report never claims success without evidence | Golden scenario #16 |
| Small task bypasses heavy orchestration | Golden scenario #17 |
| Medium task uses controlled mode | Golden scenario #18 |
| Human review approve → continue | Golden scenario #19 |
| Human review reject → stop | Golden scenario #20 |
| Runner interrupt → pause → resume | Golden scenario #21 |
| Regression detected → needs_human_review | Golden scenario #22 |

**All 22 scenarios pass deterministically — 0 LLM calls, 0 network, 0 filesystem.**

## 4. Key Engineering Decisions

### ControlPlane separation
ControlPlane is runner-independent.  The same evaluator, guardrail,
policy, and recovery logic works whether the runner is the native
scheduler, LangGraph, or a future backend.

### Evidence hierarchy
```
Observed (files on disk, test output captured)
  > Reported (worker says "tests passed")
  > Memory (previous run passed)
  > Nothing (no evidence at all)
```
Only observed evidence counts for success verification.

### Bounded recovery
Every recovery path has a maximum attempt count.  After exhaustion, the
action escalates: retry → replan → human_review → fail.  No infinite
loops.

### Human review is a gate, not a fallback
Human review triggers BEFORE risky execution, not after failure.  Policy
rules (protected files, high-risk tools, failed tests) map to human
review gates.

### Memory is not evidence
Memory hints from previous runs are advisory only.  They inform planning
but never substitute for fresh observed evidence from the current run.

### Optional runner adapters
LangGraph, external LLM providers, and real search tools are optional
adapters.  AAO's core control loop works without them.

## 5. How to Run Proof Locally

```bash
# Clone and install
git clone <repo>
cd adaptive-agent-orchestrator
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Golden scenario suite (0 LLM, 0 network)
python -m pytest -q tests/golden tests/test_golden_scenarios.py

# Demo A — Missing evidence blocked
python scripts/demo/missing_evidence.py

# Demo B — Protected file human review
python scripts/demo/protected_file.py

# Demo C — Full control loop
python scripts/demo/full_control_loop.py

# Full test suite
python -m pytest -q
```

All commands above work without API keys, network access, or Claude Code
login.

## 6. Known Limitations

See `docs/known_limitations.md` for the full honest assessment.

Key points:
- This is a personal open-source engineering system, not production SaaS
- LLM/Claude Code worker execution requires separately configured tooling
- Some integrations are optional adapters
- Golden scenarios prove control contracts, not all real-world failures
- The project is a proof-of-work portfolio artifact
