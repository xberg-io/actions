# setup-android-emulator

Composite GitHub Action that provisions an Android emulator on the runner so
downstream `task <lang>:test:e2e` invocations can drive instrumented tests
(`./gradlew connectedDebugAndroidTest`).

Wraps `reactivecircus/android-emulator-runner@v2` (de facto standard runner;
manages AVD snapshots and KVM acceleration) and exports `ANDROID_HOME` /
`ANDROID_SDK_ROOT` for the rest of the job.

## Inputs

| Name        | Default        | Description                                                |
|-------------|----------------|------------------------------------------------------------|
| `api-level` | `34`           | Android API level                                          |
| `target`    | `google_apis`  | System image: `google_apis` \| `default` \| `google_apis_playstore` |
| `arch`      | `x86_64`       | ABI: `x86_64` (KVM, GHA Linux) \| `arm64-v8a` (slower)     |
| `profile`   | `pixel_6`      | AVD hardware profile                                        |
| `avd-name`  | `kreuzberg-test` | AVD identifier                                            |

## Outputs

- `android-home` — absolute path to the SDK root
- `avd-name` — provisioned AVD identifier

## Usage

```yaml
- uses: kreuzberg-dev/actions/setup-android-emulator@v1
  with:
    api-level: "34"

- uses: kreuzberg-dev/actions/build-android-natives@v1
  # builds the JNI .so per ABI

- name: Run kotlin-android emulator e2e
  uses: reactivecircus/android-emulator-runner@v2
  with:
    api-level: 34
    target: google_apis
    arch: x86_64
    profile: pixel_6
    script: task kotlin-android:test:e2e
```

The action only **provisions** the SDK and warms the AVD cache. The emulator
process itself is started by the consumer's `reactivecircus/android-emulator-runner@v2`
step (it boots the emulator, runs `script:`, then tears it down).

## Requirements

- Linux runner with KVM available (default for `ubuntu-latest`). macOS / Windows
  runners can use this action but boot times are significantly slower without
  KVM.
- A Java toolchain (the action installs Temurin 21).
