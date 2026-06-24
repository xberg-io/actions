# setup-onnx-runtime-gpu

Download the GPU/CUDA build of ONNX Runtime, extract it under `$RUNNER_TEMP`, and export `ORT_DYLIB_PATH` + `LD_LIBRARY_PATH` for downstream steps. Companion to the CPU-only `setup-onnx-runtime` action — kept separate so callers explicitly opt into CUDA payloads.

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `version` | yes |  | ORT release version, e.g. `1.24.2`. |
| `platform` | no | `linux-x64-gpu` | Tarball platform suffix matching upstream naming (e.g. `linux-aarch64-gpu`). |

## Outputs

| Name | Description |
|---|---|
| `lib-dir` | Absolute path to the staged ORT `lib/` directory. |

## Example

```yaml
- uses: xberg-io/actions/setup-onnx-runtime-gpu@v1
  with:
    version: "1.24.2"
```
