# AAO Scope Guard

Use whenever the task starts expanding.

Ask:

- Is this required for the current phase?
- Does this prove ControlPlane works?
- Is this moving files instead of adding behavior?
- Does this add a heavy dependency?
- Does this make simple tasks slower?
- Can this be an optional adapter later?

Default rule:

```text
If it is not necessary for AAO Core or the current product-release phase, defer
it.
```
