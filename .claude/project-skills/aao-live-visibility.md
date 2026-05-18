# AAO Live Visibility

Use whenever implementing runtime status, progress, evidence, or reporting.

The user must be able to answer:

- What task is running?
- Which step is current?
- How many steps are done?
- What did the last step decide?
- What evidence exists?
- What failed and why?
- Does the system need human review?
- Where is the final report?

Do not build a web dashboard first. Start with structured data and CLI-rendered
status. A web UI or Langfuse exporter can come later.
