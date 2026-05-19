# Phase 17 - Demo, README, and Release Proof Pack

## Goal

Turn AAO from an internally working control system into something a stranger can
understand, run, inspect, and evaluate.

This phase is not about adding more core runtime features. It is about proving
the value of the features already built:

```text
task -> planning / worker -> live control decisions -> evidence -> recovery
     -> human review when needed -> audit report -> repeatable proof
```

After this phase, the user should be able to:

```text
1. clone the repo
2. run one quickstart command
3. run 2-3 deterministic demos
4. open sample reports/evidence
5. record a 3-5 minute demo video
6. explain AAO clearly in an interview or outreach message
```

## Why This Phase Exists

AAO's portfolio value is not only "the architecture exists." The value is:

```text
Claude Code / worker does the task.
AAO makes the task controlled, visible, interruptible, evidence-backed,
recoverable, and auditable.
```

Without Phase 17, AAO may look like a large personal codebase.

With Phase 17, AAO should look like a serious engineering artifact:

```text
- clear problem
- easy quickstart
- concrete failure scenarios
- visible runtime behavior
- honest audit output
- tests that prove the claims
- limitations that do not pretend to be production adoption
```

The demo must show behavior, not slogans.

## Start Conditions

Do not start Phase 17 until Phase 16 is actually done.

Required before Phase 17:

```text
- Golden Scenario Suite exists as real tests, not only fake worker helpers.
- tests/test_golden_scenarios.py or equivalent scenario tests exist.
- Golden scenarios cover missing evidence, protected file, human review,
  recovery, repeated tool/no-progress, planning revision, memory/evidence
  separation, and audit report.
- Full test suite passes, or skipped tests are intentional and documented.
```

If these are not true, stop and finish Phase 16 first.

## Non-Goals

Do not use this phase to expand the product.

Non-goals:

```text
- no new ControlPlane feature
- no new planning algorithm
- no new memory architecture
- no new LangGraph capability
- no production/SaaS claim
- no fake users, fake stars, or fake adoption
- no marketing landing page instead of a runnable quickstart
- no decorative dashboard rewrite
- no broad refactor unless a demo-blocking bug requires it
- no hiding limitations
```

Allowed core-code fixes:

```text
Only fix real demo-blocking bugs found while running the quickstart or demos.
Each fix must be small, tested, and named in the handoff.
```

## Allowed Files

Prefer this write set:

```text
README.md
docs/demo.md
docs/proof_pack.md
docs/known_limitations.md
docs/golden_scenarios.md
examples/
examples/demo/
scripts/
scripts/demo/
tests/test_readme_examples.py
tests/test_demo_scripts.py
PROJECT_STATE.md
PROJECT_LOG.md
```

Allowed only if needed by a real demo-blocking bug:

```text
src/orchestrator/__main__.py
src/orchestrator/report_writer.py
src/orchestrator/live_view.py
src/orchestrator/scheduler.py
```

Do not use `git add .`. Keep commits reviewable.

## Required Artifacts

### 1. README First Screen

The first screen of `README.md` must answer these questions in under 30 seconds:

```text
What is AAO?
Who is it for?
What problem does it solve?
What can I run quickly?
What proof exists?
What is intentionally not claimed?
```

Recommended first-screen shape:

```text
# Adaptive Agent Orchestrator

AAO is a runtime control layer for AI-assisted engineering workflows.
It lets workers such as Claude Code execute tasks while AAO handles planning,
evidence checks, guardrails, recovery, human review, live visibility, memory,
and audit reports.

Quick demo:
  <one command>

Proof:
  - Golden scenarios
  - Live Watch sample
  - Audit Report sample
  - Evidence Pack sample

Honest scope:
  This is a personal open-source engineering system and proof-of-work project,
  not a claimed production SaaS deployment.
```

Avoid:

```text
- long philosophy before the user knows what it does
- claiming production-grade unless production usage exists
- architecture diagram before quickstart
- too many badges
- hiding that some integrations are optional
```

### 2. Clean Quickstart

Provide one clean path for a stranger:

```text
git clone <repo>
cd adaptive-agent-orchestrator
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q tests/golden tests/test_golden_scenarios.py
python -m orchestrator demo <scenario-name>
```

If the exact CLI differs, document the real command. Do not invent commands that
do not run.

The quickstart should not require:

```text
- real LLM API key
- network access
- Claude Code login
- LangGraph installed unless clearly marked optional
```

### 3. Demo Scripts

Add deterministic demo scripts or CLI commands for at least these three demos.

#### Demo A - Missing Evidence Block

Story:

```text
Worker says the task is complete, but there is no observed test output.
AAO refuses to mark the run as successful.
```

Must show:

```text
- fake worker output
- evidence status
- ControlPlane decision
- failure category
- recovery/action
- report or summary
```

Value:

```text
Prevents "AI says done" from becoming false completion.
```

#### Demo B - Protected File Human Review

Story:

```text
Worker attempts a risky/protected file change.
AAO pauses and asks for human review before continuing.
```

Must show:

```text
- policy rule
- attempted file change
- human review state
- approve path
- reject path if cheap to demonstrate
```

Value:

```text
Keeps dangerous work from silently passing through automation.
```

#### Demo C - Complex Task Control Loop

Story:

```text
Complex task enters planning, gets reviewed, executes through a worker,
hits at least one control decision, and ends with an audit report.
```

Must show:

```text
- Planning Council output
- risk reviewer concern
- approved plan
- Live Watch progress
- evidence pack
- recovery or guardrail decision
- final audit report
```

Value:

```text
Shows the full AAO workflow, not a single isolated checker.
```

### 4. Sample Outputs

Create sample outputs generated from real commands, or clearly mark them as
static examples.

Required samples:

```text
examples/demo/sample_live_watch.txt
examples/demo/sample_audit_report.md
examples/demo/sample_evidence_pack.json
examples/demo/sample_failure_record.json
examples/demo/sample_recovery_decision.json
```

Rules:

```text
- Prefer generated artifacts over hand-written ones.
- If hand-written, label them "sample only".
- Do not include secrets, API keys, local absolute paths, or private messages.
- Keep output short enough to read in a demo.
```

### 5. Proof Pack

Add `docs/proof_pack.md`.

It should contain:

```text
1. Problem
   What goes wrong in AI-assisted engineering workflows?

2. AAO answer
   What does AAO control?

3. Proof table
   Claim -> demo/test/report that proves it

4. Key engineering decisions
   ControlPlane separation, evidence hierarchy, bounded recovery,
   human review, memory is not evidence, optional runner adapters.

5. How to run proof locally
   Exact commands.

6. Known limitations
   Honest current boundaries.
```

Example proof table:

```text
Claim                                      Proof
-----------------------------------------  -------------------------------
Missing evidence blocks false completion   Golden scenario + demo A
Protected file requires human review        Golden scenario + demo B
Recovery cannot retry forever               Recovery tests + golden scenario
Memory is not accepted as current evidence  Golden scenario
Audit report includes evidence and failure  Sample audit report
```

### 6. Demo Video Script

Add `docs/demo.md` with a 3-5 minute recording script.

The script should be natural, not over-marketed.

Recommended structure:

```text
0:00 - 0:30  Problem
0:30 - 1:00  What AAO is
1:00 - 2:00  Demo A: missing evidence blocked
2:00 - 3:00  Demo B: protected file human review
3:00 - 4:00  Demo C: complex task control loop
4:00 - 4:30  Tests and proof pack
4:30 - 5:00  Honest limitations and next step
```

The script should include exactly what to click/run/show.

### 7. Known Limitations

Add or update `docs/known_limitations.md`.

Do not hide weaknesses. Good limitations increase trust.

Include:

```text
- This is not a claimed production SaaS.
- LLM/Claude Code worker execution depends on local tooling and permissions.
- Some integrations are optional adapters.
- LangGraph integration may be optional if dependency is not installed.
- Human review still requires the user to make judgment.
- Golden scenarios prove control contracts, not all real-world failures.
```

If some phase is only partially supported, say so clearly.

## Demo Command Contract

If adding demo commands, prefer a shape like:

```bash
python -m orchestrator demo missing-evidence
python -m orchestrator demo protected-file
python -m orchestrator demo full-control-loop
python -m orchestrator demo all
```

Each command should print:

```text
- scenario name
- worker behavior
- control decision
- evidence status
- failure/recovery if any
- path to generated report/sample output
```

If the current CLI structure makes `demo` subcommands too invasive, use scripts:

```bash
python scripts/demo/missing_evidence.py
python scripts/demo/protected_file.py
python scripts/demo/full_control_loop.py
```

Do not add a heavy demo framework.

## Tests

Required tests:

```text
tests/test_demo_scripts.py
tests/test_readme_examples.py
```

Minimum contracts:

```text
- demo scripts run without API keys
- demo scripts exit 0
- demo scripts produce expected key phrases / output files
- README quickstart commands are real or explicitly marked optional
- sample output generation does not include secrets
- golden scenario suite still passes
```

If testing README commands is too brittle, test the commands through a small
helper list in code or docs and mention the limitation.

## Validation Commands

Run:

```bash
python3 -m pytest -q tests/golden tests/test_golden_scenarios.py
python3 -m pytest -q tests/test_demo_scripts.py tests/test_readme_examples.py
python3 -m pytest -q
python3 -m compileall src/orchestrator
git diff --check
```

Also manually run the documented quickstart and the three demo commands from a
fresh shell.

Record exact commands and outputs in the handoff.

## Definition Of Done

Phase 17 is done only when:

```text
- README first screen is clear to a stranger.
- Quickstart commands are real and tested.
- At least three demo scripts/commands work offline.
- Demo A proves missing evidence is blocked.
- Demo B proves protected-file human review.
- Demo C proves planning -> worker -> live/control -> audit path.
- Sample Live Watch, Audit Report, Evidence Pack, failure/recovery outputs exist.
- Golden Scenario Suite passes.
- Demo video script is ready for the user to record.
- Known limitations are honest.
- Full test suite passes or skips are documented.
- No fake production/user/adoption claims are present.
```

## Reviewer Checklist

Reviewer must check:

```text
Can a stranger understand AAO in 30 seconds?
Can a stranger run the quickstart without guessing?
Do demos show real control behavior, not just happy-path text?
Are sample outputs generated or honestly labeled?
Do tests prove demo commands work?
Are limitations honest?
Is the project easier to evaluate for hiring/collaboration after this phase?
Did the phase avoid adding unrelated core runtime features?
```

Reviewer should explain findings plainly:

```text
This demo is weak because it only shows success text.
It does not show the control decision or evidence path.
The fix is to print the ControlDecision and generated EvidencePack path.
```

## Handoff Requirements

Final handoff must include:

```text
1. Files changed
2. Demo commands added
3. README quickstart command
4. Sample output paths
5. Tests run and result
6. What the user can now record
7. Known limitations that remain
8. Any core-code bug fixed during the phase
```

## Claude Code Instruction

Read `CLAUDE.md` and this file. Implement only Phase 17.

This is a proof and presentation phase. Do not continue expanding AAO's core
runtime. Make the existing system legible, runnable, and trustworthy.

After implementation, explain naturally:

```text
- what a stranger can now run
- what each demo proves
- why this makes AAO less like a toy project
- what the user still needs to personally record or say in the video
```

Keep the explanation concrete and easy for the user to repeat in their own
words.
