# AAO Boundary Test Designer

Use before adding or changing runtime behavior.

Use the matrix as an internal checklist. For high-risk changes, write it out.

```text
Contract:
Bad case:
Normal case:
Boundary case:
False-positive case:
Regression path:
Contract/path case:
```

Test names must describe behavior:

```text
test_control_plane_returns_continue_for_valid_output
test_control_plane_blocks_output_guardrail_violation
test_scheduler_preserves_human_review_pause_with_control_plane
test_live_view_reports_needs_human_review_state
test_policy_blocks_protected_file_change
test_known_failure_category_uses_explicit_path_not_infer_fallback
```

For control-layer changes, do not only test final output values. Add at least
one test that proves the intended runtime path.

Ask:

```text
Would this test still pass if the implementation guessed the right final value
at the end?
```

If yes, strengthen the test. Use monkeypatch/spies when useful.

Examples:

```text
Final-value-only test:
  failure_record.category == GUARDRAIL_BLOCKED

Path test:
  known guardrail failures propagate exc.failure_category and never call
  infer_failure_category.

Final-value-only test:
  report contains evidence

Path test:
  observed evidence comes from captured command output, not from a worker claim.
```

Do not proceed to the next phase until relevant targeted tests pass.
