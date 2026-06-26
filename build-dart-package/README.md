# build-dart-package

Build a Dart package that wraps a Rust binding crate via
[flutter_rust_bridge](https://github.com/fzyzcjy/flutter_rust_bridge). The
action installs Flutter (optional) and `flutter_rust_bridge_codegen`, runs
the FRB code generator inside the package directory, then builds the named
cargo crate and emits the path of the resulting library. Publishing
(`dart pub publish`) is left to a separate action — pair this with
`xberg-io/actions/publish-pub@v1`.

## Usage

```yaml
- uses: actions/checkout@v4
- uses: xberg-io/actions/setup-rust@v1
- uses: xberg-io/actions/build-dart-package@v1
  id: dart_build
  with:
    package-dir: packages/dart
    crate-name: xberg-dart
- name: Show artifact
  run: ls -l "${{ steps.dart_build.outputs.library-path }}"
```

Skip the Flutter setup if the workflow already installed it:

```yaml
- uses: subosito/flutter-action@v2
  with:
    flutter-version: '3.27.0'
- uses: xberg-io/actions/build-dart-package@v1
  with:
    setup-flutter: 'false'
```

## Inputs

| Name | Required | Default | Description |
|---|---|---|---|
| `package-dir` | no | `packages/dart` | Directory containing `pubspec.yaml` and the FRB config. |
| `crate-name` | no | `xberg-dart` | Cargo crate name of the Rust binding crate. |
| `build-profile` | no | `release` | Cargo profile (`release`, `dev`, or a custom named profile). |
| `setup-flutter` | no | `true` | Install Flutter via `subosito/flutter-action`. |
| `flutter-version` | no | `3.27.0` | Flutter version, passed to `subosito/flutter-action`. |
| `frb-codegen-version` | no | `2.12.0` | `flutter_rust_bridge_codegen` version installed via cargo. |
| `dry-run` | no | `false` | Print the planned commands and exit without building. |

## Outputs

| Name | Description |
|---|---|
| `library-path` | Absolute path to the built dynamic/static library (`.so` / `.dylib` / `.dll`). |

## Notes

- The action assumes the caller already ran `actions/checkout` and a Rust
  toolchain action (e.g. `xberg-io/actions/setup-rust@v1`).
- The platform-specific library suffix is selected from `RUNNER_OS`.
- The library name matches Cargo's convention: dashes in the crate name
  become underscores (`xberg-dart` -> `libxberg_dart.{so,dylib}`,
  `xberg_dart.dll`).
- `dev`/`debug` profiles map to `target/debug/`; everything else maps to
  `target/<profile>/`.
- `flutter_rust_bridge_codegen` is installed with `--locked` and skipped if
  the requested version is already on `PATH`.
