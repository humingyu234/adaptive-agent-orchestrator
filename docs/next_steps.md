# AAO Next Steps

Updated: 2026-05-25

## P0

1. Record and commit the current stable worktree.
   - Confirm current diffs are intentional.
   - Remove or archive temporary helper scripts such as `tmp_write_evidence.py`.
   - Run targeted tests and full test suite where practical.

2. Absorb the Opus independent evidence review.
   - Add AAO-owned evidence capture.
   - Run `git status --porcelain` after real worker execution.
   - Run `git diff HEAD` after real worker execution.
   - Run each `required_checks` command from AAO, not from worker self-report.
   - Write `observed/aao_test_output.txt` and `observed/aao_diff.patch`.
   - Treat worker files as reported evidence unless AAO generated them.

3. Add Worker Doctor / Claude worker preflight.
   - Check configured `claude` path.
   - Check relevant env/API/proxy presence.
   - Run a short `claude -p` smoke test before long worker tasks.
   - Fail fast with observed evidence instead of waiting 600 seconds.

4. Run medium real task acceptance.
   - Real Claude Code worker.
   - 1-3 files changed.
   - AAO-owned checks and diff.
   - Audit report generated.
   - Repeat until the failure mode is explainable.

## P1

- Run one large project session acceptance:
  Planning Council -> milestones -> real worker -> AAO evidence -> ControlPlane -> reviewer -> repair if needed -> audit -> resume.
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

