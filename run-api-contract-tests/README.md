# run-api-contract-tests

Run [schemathesis](https://schemathesis.readthedocs.io/) property-based contract tests against a running API. The action starts the supplied Docker image as the system under test, waits for it to come up, then runs `schemathesis run` with the kreuzberg-dev standard check set. The container is always stopped on exit.

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `image` | yes |  | Docker image to run as the SUT. Must be loaded locally. |
| `port` | no | `8000` | Port bound on host and container. |
| `spec-path` | no | `/openapi.json` | Path of the OpenAPI document. |
| `startup-wait-seconds` | no | `5` | Sleep after `docker run -d` before testing. |
| `max-examples` | no | `10` | schemathesis `--max-examples`. |
| `request-timeout-ms` | no | `30000` | schemathesis `--request-timeout`. |
| `checks` | no | (kreuzberg standard set) | Comma-separated schemathesis checks. |
| `schemathesis-version` | no | `schemathesis` | pip spec for schemathesis. |
| `extra-args` | no | `` | Extra args appended to `schemathesis run`. |

## Example

```yaml
- uses: kreuzberg-dev/actions/run-api-contract-tests@v1
  with:
    image: kreuzberg:full
    port: "8000"
```
