#!/usr/bin/env bash
# Consumer-side install + smoke against a published binding.
# Inputs come via INPUT_* env vars (see action.yml).
set -euo pipefail

: "${INPUT_LANGUAGE:?language is required}"
: "${INPUT_VERSION:?version is required}"
: "${INPUT_PACKAGE_NAME:?package-name is required}"
INPUT_ARTIFACT_SOURCE="${INPUT_ARTIFACT_SOURCE:-registry}"
INPUT_LOCAL_PATH="${INPUT_LOCAL_PATH:-}"
INPUT_TEST_APPS_DIR="${INPUT_TEST_APPS_DIR:-test_apps}"
INPUT_SMOKE_ONLY="${INPUT_SMOKE_ONLY:-true}"

lang="$INPUT_LANGUAGE"
app_dir="$INPUT_TEST_APPS_DIR/$lang"

if [[ ! -d "$app_dir" ]]; then
  echo "::error::test_app directory not found: $app_dir"
  echo "Did you commit test_apps/, or set regenerate=true?"
  exit 1
fi

echo "::group::Environment"
echo "language:        $lang"
echo "version:         $INPUT_VERSION"
echo "package:         $INPUT_PACKAGE_NAME"
echo "artifact-source: $INPUT_ARTIFACT_SOURCE"
echo "local-path:      $INPUT_LOCAL_PATH"
echo "test-app:        $app_dir"
echo "smoke-only:      $INPUT_SMOKE_ONLY"
echo "::endgroup::"

cd "$app_dir"

# Per-language install + smoke. The smoke target name is by convention:
# the smoke test file/class/spec is always named *smoke*. For each language,
# `*` matches: tests/test_smoke.py, tests/smoke.test.ts, spec/smoke_spec.rb,
# SmokeTest.java, SmokeTests.cs, tests/SmokeTest.php, test/smoke_test.exs,
# Test_Smoke* (go), src/main.rs runs full mock-server harness (rust), or
# test_smoke.c (c).
case "$lang" in
python)
  if [[ "$INPUT_ARTIFACT_SOURCE" != "registry" && -n "$INPUT_LOCAL_PATH" ]]; then
    # Install from local wheelhouse via uv pip
    echo "::group::Install from local wheelhouse"
    uv venv
    uv pip install --find-links "$INPUT_LOCAL_PATH" "${INPUT_PACKAGE_NAME}==${INPUT_VERSION}"
    uv pip install pytest pytest-asyncio pytest-timeout
    echo "::endgroup::"
  else
    uv sync
  fi
  if [[ "$INPUT_SMOKE_ONLY" == "true" ]]; then
    uv run pytest tests/test_smoke.py -v
  else
    uv run pytest tests/ -v
  fi
  ;;

node | wasm)
  if [[ "$INPUT_ARTIFACT_SOURCE" != "registry" && -n "$INPUT_LOCAL_PATH" ]]; then
    echo "::group::Install local tarball"
    tarball=$(find "$INPUT_LOCAL_PATH" -maxdepth 1 -name '*.tgz' -print -quit)
    [[ -n "$tarball" ]] || {
      echo "::error::no .tgz found in $INPUT_LOCAL_PATH"
      exit 1
    }
    pnpm add "$tarball"
    pnpm install
    echo "::endgroup::"
  else
    pnpm install
  fi
  if [[ "$INPUT_SMOKE_ONLY" == "true" ]]; then
    pnpm exec vitest run tests/smoke.test.ts
  else
    pnpm exec vitest run
  fi
  ;;

ruby)
  if [[ "$INPUT_ARTIFACT_SOURCE" != "registry" && -n "$INPUT_LOCAL_PATH" ]]; then
    echo "::group::Install local gem"
    gem_file=$(find "$INPUT_LOCAL_PATH" -maxdepth 1 -name '*.gem' -print -quit)
    [[ -n "$gem_file" ]] || {
      echo "::error::no .gem found in $INPUT_LOCAL_PATH"
      exit 1
    }
    gem install --local "$gem_file"
    bundle config --local local."$INPUT_PACKAGE_NAME" "$INPUT_LOCAL_PATH"
    bundle install --local
    echo "::endgroup::"
  else
    bundle install
  fi
  if [[ "$INPUT_SMOKE_ONLY" == "true" ]]; then
    bundle exec rspec spec/smoke_spec.rb
  else
    bundle exec rspec spec/
  fi
  ;;

java)
  if [[ "$INPUT_ARTIFACT_SOURCE" != "registry" && -n "$INPUT_LOCAL_PATH" ]]; then
    echo "::group::Install local jar(s) into maven repository"
    for jar in "$INPUT_LOCAL_PATH"/*.jar; do
      [[ -f "$jar" ]] || continue
      mvn install:install-file -Dfile="$jar" -DgeneratePom=true || true
    done
    echo "::endgroup::"
  fi
  if [[ "$INPUT_SMOKE_ONLY" == "true" ]]; then
    mvn test -Dtest=SmokeTest -B
  else
    mvn test -B
  fi
  ;;

csharp)
  if [[ "$INPUT_ARTIFACT_SOURCE" != "registry" && -n "$INPUT_LOCAL_PATH" ]]; then
    echo "::group::Add local nuget source"
    dotnet nuget add source "$(readlink -f "$INPUT_LOCAL_PATH")" --name local || true
    echo "::endgroup::"
  fi
  dotnet restore
  if [[ "$INPUT_SMOKE_ONLY" == "true" ]]; then
    dotnet test --filter "FullyQualifiedName~SmokeTests" --logger "console;verbosity=normal"
  else
    dotnet test --logger "console;verbosity=normal"
  fi
  ;;

php)
  # Step 1: install the extension via PIE. alef-generated test_apps emit an
  # install.sh next to composer.json that calls `pie install` for the
  # current platform; we just run it. PIE >= 1.3.7 (preferably 1.4.x)
  # is required for array-form `php-ext.download-url-method` parsing.
  if [[ -x "install.sh" || -f "install.sh" ]]; then
    bash install.sh "$INPUT_VERSION"
  else
    echo "::warning::install.sh not found in $app_dir; assuming the extension is preinstalled"
  fi

  # Step 2: composer install for the dev deps (phpunit, guzzle). Local
  # composer.json should require `ext-liter_llm: "*"` (platform req) — not
  # the actual package. Composer's platform resolver satisfies it from
  # `php -m` once PIE has installed the .so.
  composer install --no-interaction --prefer-dist

  # Step 3: smoke or full suite.
  if [[ "$INPUT_SMOKE_ONLY" == "true" ]]; then
    vendor/bin/phpunit tests/SmokeTest.php
  else
    vendor/bin/phpunit
  fi
  ;;

elixir)
  mix deps.get
  if [[ "$INPUT_SMOKE_ONLY" == "true" ]]; then
    mix test test/smoke_test.exs
  else
    mix test
  fi
  ;;

go)
  go mod download
  if [[ "$INPUT_SMOKE_ONLY" == "true" ]]; then
    go test -v -run "Test_Smoke"
  else
    go test -v ./...
  fi
  ;;

rust)
  if [[ "$INPUT_SMOKE_ONLY" == "true" ]]; then
    cargo run --quiet
  else
    cargo run
  fi
  ;;

c)
  bash download_ffi.sh
  make
  if [[ "$INPUT_SMOKE_ONLY" == "true" ]]; then
    ./run_tests --smoke
  else
    ./run_tests
  fi
  ;;

*)
  echo "::error::Unknown language: $lang"
  exit 1
  ;;
esac

echo "verify-install: $lang OK ($INPUT_PACKAGE_NAME @ $INPUT_VERSION)"
