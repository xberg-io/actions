# setup-textlint

Install Node.js and pnpm through mise, then textlint and the xberg-io standard rule set in one batched `pnpm install`.
Used for prose linting in docs CI. The caller's `mise.toml` must declare `node` and `pnpm`.

The packages go into `$RUNNER_TEMP/textlint`: its `node_modules/.bin` is added to `PATH` and `NODE_PATH` points at its
`node_modules`, so later steps can run `textlint` and `require` a rule.

## Inputs

| Name             | Required | Default | Description                                                                         |
| ---------------- | -------- | ------- | ----------------------------------------------------------------------------------- |
| `node-version`   | no       | ``      | Node.js version, matched against the caller's mise locks. Empty uses `mise.toml`'s. |
| `extra-packages` | no       | ``      | Whitespace-separated list of additional npm package specs.                          |

## Standard rule set

`textlint`, `textlint-rule-no-todo`, `textlint-rule-no-start-duplicated-conjunction`, `textlint-rule-no-empty-section`, `textlint-rule-terminology`, `textlint-rule-no-zero-width-spaces`, `@textlint-rule/textlint-rule-no-invalid-control-character`, `textlint-rule-no-surrogate-pair`, `@textlint-rule/textlint-rule-no-unmatched-pair`, `textlint-rule-alex`, `textlint-rule-write-good`, `textlint-rule-common-misspellings`, `textlint-rule-stop-words`, `textlint-rule-en-capitalization`, `textlint-filter-rule-comments`, `textlint-filter-rule-node-types`.

## Example

```yaml
- uses: xberg-io/actions/setup-textlint@v1
- run: scripts/ci/docs/textlint.sh
```
