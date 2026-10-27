---
type: Decision
title: Workflow Deltas
paths:
  - ".github/workflows/**"
x-ai-rulez:
  kind: rule
  id: workflow-deltas
  metadata:
    priority: high
---

Actions-specific exceptions to the shared `github-workflow-conventions` skill:

- Keep the `.yml` extension and the existing filenames here; do not apply the skill's `.yaml` and `ci-`/`release-` naming.
- `reusable-*.yml` paths are a public interface: every other repository calls them as `xberg-io/actions/.github/workflows/reusable-<name>.yml@v1`. Never rename or remove one.
