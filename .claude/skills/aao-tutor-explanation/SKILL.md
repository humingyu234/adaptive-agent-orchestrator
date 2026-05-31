---
name: aao-tutor-explanation
description: Use after completing an AAO change or when explaining AAO design, runtime paths, bugs, evidence, guardrails, recovery, or project workflow to the user.
---

# AAO Tutor Explanation

Explain directly and concretely. Do not over-structure small answers.

Preferred shape:

```text
what it is
why it mattered
what changed
how the runtime path works now
how it was verified
what remains risky
```

Style:

- Use simple words first, technical terms second.
- Use small before/after flows when helpful.
- Tie explanations to actual files, commands, or artifacts.
- Keep it concise unless the user asks for depth.

Mental model for AAO:

```text
worker = does the work
AAO = observes and verifies
ControlPlane = decides
reviewer = read-only second look
audit = memory of what happened and why
```
