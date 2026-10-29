#!/usr/bin/env bash
#MISE description="Run a specific test workflow locally (usage: mise run test:act test-setup-rust.yml)"
#USAGE arg "<workflow>" help="Workflow file name under .github/workflows"
set -euo pipefail

act -W ".github/workflows/${usage_workflow:?}"
