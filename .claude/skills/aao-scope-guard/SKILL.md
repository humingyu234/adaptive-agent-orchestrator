---
name: aao-scope-guard
description: Use when an AAO task starts expanding into memory systems, dashboards, new runners, broad refactors, multi-worker work, or unrelated product ideas.
---

# AAO Scope Guard

Before expanding scope, ask:

- Does this unblock real single-worker medium acceptance?
- Does this make evidence more trustworthy?
- Does this reduce worker runtime failure?
- Does this improve demo/proof clarity?
- Can it be postponed without breaking the current path?

Default:

```text
If it does not help the current Worker Doctor -> medium acceptance -> Control Trace path, park it.
```

Prefer:

- small vertical slices
- explicit non-goals
- one commit per concern
- docs parking lot for useful later ideas
