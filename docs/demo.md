# AAO Demo Video Script — 3-5 minutes

This script is designed to be recorded in one take with a terminal and a
browser window open.  No slides needed.  Show real control behavior, not
marketing.

## Preparation

- Terminal ready in the project directory
- Python virtual environment activated
- Text size large enough for screen recording (14pt+)
- Close unrelated windows, notifications off

## Script

### 0:00 — 0:30 Problem

**What you show:**
Terminal with an empty prompt.

**What you say:**

> AI coding agents are powerful, but they make mistakes.  They can claim a
> task is done when it isn't.  They can change files they shouldn't.  They
> can get stuck in retry loops.  And the orchestrator can't tell the
> difference between real evidence and what the agent just says.
>
> AAO — Adaptive Agent Orchestrator — is a control layer that sits between
> the orchestrator and the worker.  It checks evidence, enforces policy,
> bounds recovery, requires human review for risky changes, and produces
> honest audit reports.
>
> Let me show you three concrete examples.

### 0:30 — 1:30 Demo A: Missing Evidence Blocked

**What you show:**
Run `python scripts/demo/missing_evidence.py` and scroll through output.

**What you say:**

> First demo: the worker says "I fixed it" but provides no test output, no
> file changes, no commands run — nothing observable.
>
> *(scroll to Worker Output)*
> You see here: status is "completed", but test_output is empty,
> files_changed is empty.  Just a natural-language claim.
>
> *(scroll to Evidence Status)*
> AAO checks for observed evidence.  All three items — test output, file
> changes, commands run — are MISSING.
>
> *(scroll to ControlPlane Decision)*
> ControlPlane blocks success — action is "needs_human_review".  Failure
> category: task_quality_error.  Recovery: request_evidence.
>
> This is not a retry loop.  After one attempt, it escalates to replan.
>
> The key point: without evidence verification, "AI says done" becomes
> false completion.  AAO prevents that.

### 1:30 — 2:30 Demo B: Protected File Human Review

**What you show:**
Run `python scripts/demo/protected_file.py` and scroll through output.

**What you say:**

> Second demo: the worker modifies a protected file — config/secrets.yaml.
>
> *(scroll to Policy Configuration)*
> The policy says: these files are protected.  Protected file changes
> require human review.  No exceptions.
>
> *(scroll to Worker Output)*
> The worker changed src/main.py (fine) AND config/secrets.yaml (not fine).
>
> *(scroll to ControlPlane Decision)*
> AAO detects the protected file and blocks — needs_human_review.
> Failure category: policy_error.
>
> *(scroll to Human Review Gate)*
> The system now shows the human review question: "Worker modified
> config/secrets.yaml.  Approve or reject?"
>
> *(point to approve/reject paths)*
> If a human approves, execution continues.  If they reject, it stops.
> There's no automatic retry for policy violations.  The human decides.
>
> Without this, a worker can silently change secrets, credentials, or
> environment files.  AAO puts a human gate in front of risky changes.

### 2:30 — 3:30 Demo C: Full Control Loop

**What you show:**
Run `python scripts/demo/full_control_loop.py` and scroll through output.

**What you say:**

> Third demo: the full AAO workflow for a complex task.  This is where
> everything comes together.
>
> *(scroll through Planning Council output)*
> A complex refactoring task enters the Planning Council.  It produces a
> structured plan with 12 steps, success criteria, stop conditions,
> required evidence, and non-goals.
>
> *(scroll to Plan Approval)*
> The plan is reviewed and approved.
>
> *(scroll to Worker Execution)*
> The worker executes: 3 files changed, 14 tests pass.
>
> *(scroll to Evidence Verification)*
> AAO verifies all evidence: test output observed, diff observed, lint
> observed.  Decision: continue.
>
> *(scroll to Recovery)*
> I also simulate what happens if tests fail: retry once, then replan.
> Recovery is bounded — no infinite loops.
>
> *(scroll to Audit Report)*
> Finally, an audit report is generated with the full trace: plan,
> evidence, control decisions, recovery path, and status.
>
> This is the complete AAO control loop: Planning → Risk Review →
> Approval → Execution → Evidence → Guardrails → Recovery → Audit Report.

### 3:30 — 4:30 Tests and Proof

**What you show:**
Run `python -m pytest -q tests/golden tests/test_golden_scenarios.py`

**What you say:**

> Everything I've shown is backed by a deterministic test suite.  22
> golden scenarios, 49 tests, 0 LLM calls, 0 network.
>
> *(show the test output passing)*
>
> These tests prove all five control contracts:
> - Evidence beats claims
> - Policy controls risky actions
> - Recovery is bounded
> - Planning prevents bad execution
> - Reports are honest
>
> Every scenario exercises the real AAO control code against staged
> failures.  No mocking, no shortcuts.

### 4:30 — 5:00 Honest limitations

**What you say (no terminal needed, or show docs/known_limitations.md):**

> AAO is a proof-of-work engineering system, not a production SaaS.
>
> Honest limitations:
> - It requires LLM/Claude Code workers that are separately configured
> - Some integrations are optional adapters
> - Human review still needs a human to make the judgment
> - Golden scenarios prove control contracts, not every real-world failure
> - This is open-source personal work, not a deployed service
>
> Being honest about what it doesn't do builds more trust than claiming
> everything works.

## What the user needs to record personally

1. The spoken narration (use this script as a guide, not a teleprompter)
2. Any personal motivation or background they want to add
3. Close with their own contact info or call to action if desired

## After recording

The recording should be short enough to share in an interview or outreach
message. 3-5 minutes is the sweet spot — long enough to show real
behavior, short enough that someone watches the whole thing.
