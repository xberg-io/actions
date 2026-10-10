# Concepts

* [Release Workflow](SKILL.md) - How to cut a release of the xberg-io/actions repo — clean-tree + poly/tests preconditions, CHANGELOG rollover, commit and push to main, then the two-tag scheme this repo uses (create a NEW immutable `vX.Y.Z` annotated tag AND force-move the floating major `v1` tag to the same commit so every consumer pinning `@v1` picks up the release). Load when cutting/releasing a new version of the actions repo, or when the floating `v1` tag needs to be advanced.
