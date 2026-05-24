# Incident: Claude Worker Timeout

Date: 2026-05-25

## Symptom

A real Claude Code worker milestone timed out after 600 seconds with no stdout/stderr.

Observed artifact from the failed run:

```json
{
  "exit_code": -1,
  "timed_out": true,
  "elapsed_seconds": 600.08,
  "command": "/home/administrator/.npm-global/bin/claude -p --verbose --permission-mode auto"
}
```

An older real worker run without `--permission-mode auto` completed successfully in about 202 seconds:

```json
{
  "exit_code": 0,
  "timed_out": false,
  "elapsed_seconds": 202.3,
  "command": "/home/administrator/.npm-global/bin/claude -p --verbose"
}
```

## Impact

Planning could produce milestones, but execution stalled at the worker subprocess layer. The user could not tell whether the root cause was prompt quality, CLI/env/API/proxy state, or worker bridge behavior.

## Current Local Mitigation

Default Claude worker args were reverted to:

```text
-p --verbose
```

instead of:

```text
-p --verbose --permission-mode auto
```

## Follow-Up

Add Worker Doctor before real worker execution:

- verify `claude` executable path;
- verify required env/API/proxy state;
- run a short smoke command;
- write preflight output as AAO-observed evidence;
- fail fast when the worker environment is not ready.

## Boundary

This incident does not prove AAO is architecturally broken. It shows that the real worker subprocess boundary needs explicit preflight and clearer evidence.

