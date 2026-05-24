# AAO Next Steps

Updated: 2026-05-25

## P0

Completed on the real single-worker `claude-code` mainline path:

- AAO-owned evidence capture.
- Pre-worker git baseline and baseline-relative worker attribution.
- Git `HEAD` / index mutation detection during real worker execution.
- Shared AAO-owned evidence bundle for RuleBasedReviewer and CodexReviewer.
- Safe required-check command families and a total execution budget.
- Fail-fast git-worktree requirement for real controlled `claude-code` execution.

Next:

1. Remove or archive temporary helper script `tmp_write_evidence.py`.

2. Add Worker Doctor / Claude worker preflight.
   - Check configured `claude` path.
   - Check relevant env/API/proxy presence.
   - Run a short `claude -p` smoke test before long worker tasks.
   - Fail fast with observed evidence instead of waiting 600 seconds.

3. Run medium real task acceptance.
   - Real Claude Code worker.
   - 1-3 files changed.
   - AAO-owned checks and diff.
   - Audit report generated.
   - Repeat until the failure mode is explainable.

## P1

- Run one large project session acceptance:
  Planning Council -> milestones -> real worker -> AAO evidence -> ControlPlane -> reviewer -> repair if needed -> audit -> resume.
- Decide and implement independent-evidence semantics for packet/multi-worker/langgraph paths.
- Validate the audit representation of real multi-round auto-repair.
- Fix CLI/docs mismatches found by the Opus review, especially flags that look supported but are no-ops on a path.
- Keep fake, packet, dry-run, and real worker evidence visibly separated in reports.
- Add a small real-run proof pack under `examples/real_run/`.

## P2 / Parking Lot

- AAO memory system:
  define records for current state, decisions, incidents, evidence, user preferences, and resume briefs.
- Evaluate OpenViking only after the memory schema is clear and the real worker/evidence path is stable.
- LangGraph runner persistence hardening.
- Multi-worker real-world reliability and conflict handling.

## Non-Goals Right Now

- Do not build a large memory system before worker/evidence stabilization.
- Do not rewrite Planning Council prompts as a substitute for evidence integrity.
- Do not merge unrelated refactors into the evidence/worker reliability fixes.
