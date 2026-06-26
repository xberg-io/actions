# check-docker-image-size

Inspect a locally-built Docker image and warn or fail when it exceeds a size threshold. Writes the size to a step output and to the job step summary.

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `image` | yes |  | Image reference to inspect, e.g. `xberg:cli`. Must already be loaded into the local docker daemon. |
| `warn-mb` | no | `` | Emit `::warning::` when size exceeds this many MB. Empty disables. |
| `fail-mb` | no | `` | Fail the step when size exceeds this many MB. Empty disables. |
| `label` | no | `<image>` | Label used in the step summary line. |

## Outputs

| Name | Description |
|---|---|
| `size-mb` | Image size in megabytes (integer). |

## Example

```yaml
- uses: xberg-io/actions/check-docker-image-size@v1
  with:
    image: xberg:cli
    warn-mb: "200"
    fail-mb: "400"
    label: "CLI image"
```
