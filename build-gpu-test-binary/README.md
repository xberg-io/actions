# build-gpu-test-binary

Build a single `cargo test --no-run` binary with JSON message output, then extract its executable path and copy it to a stable filename. Designed for split CI flows where the test binary is built on a cheap runner and executed on a GPU-enabled runner via `actions/upload-artifact` / `actions/download-artifact`.

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `package` | yes |  | Cargo package (`-p <package>`). |
| `test-name` | yes |  | Test target name (`--test <name>`). |
| `features` | no | `` | Comma-separated cargo features to enable. |
| `output-name` | no | `gpu-test-binary` | Filename for the staged binary. |

## Outputs

| Name | Description |
|---|---|
| `binary-path` | Absolute path to the staged binary. |

## Example

```yaml
- uses: kreuzberg-dev/actions/build-gpu-test-binary@v1
  with:
    package: kreuzberg
    test-name: gpu_acceleration
    features: paddle-ocr,layout-detection,embeddings,pdf,ocr,ort-dynamic
    output-name: gpu-acceleration-test
- uses: actions/upload-artifact@v4
  with:
    name: gpu-test-binary
    path: gpu-acceleration-test
```
