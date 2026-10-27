---
type: Concept
title: Area Map
x-ai-rulez:
  kind: context
  id: area-map
  metadata:
    priority: high
---

## Area Map

Each top-level `<name>/action.yml` defines one action. Workflows live in `.github/workflows/`; test suites in `tests/`, `bats-lib/` and each action's `tests/`. An action's inputs and outputs are a public interface consumed at `@v1`: add, never rename or remove, and record changes under `## [Unreleased]` in CHANGELOG.md. Use `testing-conventions` for tests and `release-workflow` for versioning and the floating major tag.
