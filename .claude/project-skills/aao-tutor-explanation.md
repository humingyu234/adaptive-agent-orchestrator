# AAO Tutor Explanation

Use after every completed phase, feature slice, bug fix, or important design
decision.

The user must understand and own the project. Explain naturally, like a senior
engineer walking through the change. Do not sound like a rigid checklist.

Style requirement:

- Explain like teaching a bright 12-year-old who is serious and curious.
- Be intuitive, specific, and easy to restate.
- Use concrete examples before abstract terms.
- Use small text diagrams, arrows, before/after comparisons, or everyday
  analogies when they make the runtime path easier to see.
- When a technical term matters, include it in parentheses after the plain
  explanation.
- Avoid redundant explanation. If the user already understands a layer, move on.
- Do not use an analogy unless it maps back to the actual code path.

Cover these points in prose:

- what changed, in one plain sentence
- what problem it solves
- where it sits in AAO
- how the runtime path worked before
- how the runtime path works now
- which files changed and what role each file plays
- why this design was chosen
- what alternative was not chosen and why
- what tests were run
- what those tests prove
- what remains unproven or intentionally out of scope
- what this enables next

Use concrete paths and flows. Avoid empty abstractions.

Preferred explanation shape:

```text
concrete example -> intuitive picture -> actual code path -> engineering term
-> why it matters -> one boundary case
```

Example style:

```text
Before this change, Scheduler was like a person checking tickets by hand at
every door. After this change, Scheduler sends each ticket to ControlPlane.
ControlPlane gives back a decision: continue, retry, needs_human_review, or
fail. In code, the path is:

agent output -> Scheduler -> ControlPlane -> ControlDecision -> Scheduler

The engineering term is a control gate: one place that decides whether the run
can move forward.
```

For important concepts, end with:

```text
You can think of it this way: <plain mental model>.
```

Then invite the user to restate it in their own words when useful. Correct the
restatement directly and calmly if needed.
