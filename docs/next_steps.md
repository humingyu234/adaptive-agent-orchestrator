# AAO Next Steps

Updated: 2026-06-01

## P0

Completed on the real single-worker `claude-code` mainline path:

- AAO-owned evidence capture.
- Pre-worker git baseline and baseline-relative worker attribution.
- Git `HEAD` / index mutation detection during real worker execution.
- Shared AAO-owned evidence bundle for RuleBasedReviewer and CodexReviewer.
- Safe required-check command families and a total execution budget.
- Fail-fast git-worktree requirement for real controlled `claude-code` execution.
- Lean `CLAUDE.md` plus official `.claude/skills/<skill>/SKILL.md` entrypoints.
- Claude Code Worker Doctor preflight with AAO-owned observed evidence.
- Medium real task acceptance completed after policy check normalization.

Next:

1. Remove or archive temporary helper/probe scripts.
   - `tmp_write_evidence.py` is untracked and should be deleted or archived after confirmation.
   - Tracked `tmp/test_*.py` probe scripts should be removed from the repo or moved under non-test fixtures.
   - Rotate any API keys that were ever written into temporary probe scripts.

2. Add lightweight Control Trace output for demos and PR review.
   - Task / plan / worker / observed evidence / decision / failure / recovery / audit.
   - Keep it CLI/artifact-first; do not build a large dashboard yet.

## P1

- Run one large project session acceptance:
  Planning Council -> milestones -> real worker -> AAO evidence -> ControlPlane -> reviewer -> repair if needed -> audit -> resume.
- Decide and implement independent-evidence semantics for packet/multi-worker/langgraph paths.
- Validate the audit representation of real multi-round auto-repair.
- Fix CLI/docs mismatches found by the Opus review, especially flags that look supported but are no-ops on a path.
- Keep fake, packet, dry-run, and real worker evidence visibly separated in reports.
- Add a small real-run proof pack under `examples/real_run/`.
- Add a PR Proof Pack format for future open-source PRs:
  problem, change, verification, risk, AAO-observed evidence, reviewer findings.

## P2 / Parking Lot

- AAO memory system:
  define records for current state, decisions, incidents, evidence, user preferences, and resume briefs.
- Evaluate OpenViking only after the memory schema is clear and the real worker/evidence path is stable.
- LangGraph runner persistence hardening.
- Multi-worker real-world reliability and conflict handling.
- Archive legacy `.claude/project-skills/*.md` after old phase-spec references are migrated.

## Non-Goals Right Now

- Do not build a large memory system before worker/evidence stabilization.
- Do not rewrite Planning Council prompts as a substitute for evidence integrity.
- Do not merge unrelated refactors into the evidence/worker reliability fixes.
