# setup-textlint

Install Node.js, textlint, and the xberg-io standard rule set in one batched `npm install`. Used for prose linting in docs CI.

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `node-version` | no | `24` | Node.js version to install. |
| `extra-packages` | no | `` | Whitespace-separated list of additional npm package specs. |

## Standard rule set

`textlint`, `textlint-rule-no-todo`, `textlint-rule-no-start-duplicated-conjunction`, `textlint-rule-no-empty-section`, `textlint-rule-terminology`, `textlint-rule-no-zero-width-spaces`, `@textlint-rule/textlint-rule-no-invalid-control-character`, `textlint-rule-no-surrogate-pair`, `@textlint-rule/textlint-rule-no-unmatched-pair`, `textlint-rule-alex`, `textlint-rule-write-good`, `textlint-rule-common-misspellings`, `textlint-rule-stop-words`, `textlint-rule-en-capitalization`, `textlint-filter-rule-comments`, `textlint-filter-rule-node-types`.

## Example

```yaml
- uses: xberg-io/actions/setup-textlint@v1
- run: scripts/ci/docs/textlint.sh
```
