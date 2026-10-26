---
type: Concept
title: Area Map
x-ai-rulez:
  kind: context
  id: area-map
  metadata:
    priority: high
---

# Area Map

This repo holds shared GitHub Actions composite actions and reusable workflows; each top-level `<name>/` with an `action.yml` is one action.

- `setup-*/`, `install-*/` — toolchain and runtime setup
- `build-*/`, `stage-*/`, `package-*/` — binding, native-library and CLI builds
- `publish-*/` — registry publishing per ecosystem
- `verify-*/`, `validate-*/`, `check-*/` — package, release and config checks
- `*-release*/`, `retag-for-republish/` — release lifecycle
- `homebrew-*/` — Homebrew bottles
- `cache-*/`, `*-cache/` — build caches
- `run-*/` — test-suite runners
- `.github/workflows/reusable-*.yml` — reusable workflows
- `.github/workflows/test-*.yml`, `tests/`, `bats-lib/` — tests for the actions (`testing-conventions` skill)

Releasing a new version and moving the major tag: `release-workflow` skill.
