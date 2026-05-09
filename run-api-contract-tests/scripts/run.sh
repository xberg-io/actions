#!/usr/bin/env bash
set -euo pipefail

image="${INPUT_IMAGE:?INPUT_IMAGE is required}"
port="${INPUT_PORT:-8000}"
spec_path="${INPUT_SPEC_PATH:-/openapi.json}"
wait_secs="${INPUT_STARTUP_WAIT_SECONDS:-5}"
max_examples="${INPUT_MAX_EXAMPLES:-10}"
request_timeout="${INPUT_REQUEST_TIMEOUT_MS:-30000}"
checks="${INPUT_CHECKS:-not_a_server_error,status_code_conformance,content_type_conformance,response_schema_conformance,negative_data_rejection}"
schemathesis_spec="${INPUT_SCHEMATHESIS_VERSION:-schemathesis}"
extra_args="${INPUT_EXTRA_ARGS:-}"

pip3 install --quiet "$schemathesis_spec"

container_id=$(docker run -d -p "${port}:${port}" "$image")
echo "Started container ${container_id:0:12} (image=$image, port=$port)"

trap 'docker stop "$container_id" >/dev/null 2>&1 || true' EXIT

sleep "$wait_secs"

run_args=(run "http://localhost:${port}${spec_path}"
  --max-examples="$max_examples"
  --request-timeout="$request_timeout"
  --checks "$checks")
if [[ -n "$extra_args" ]]; then
  # Intentional word splitting on extra-args.
  # shellcheck disable=SC2206
  extras=($extra_args)
  run_args+=("${extras[@]}")
fi

set +e
schemathesis "${run_args[@]}"
status=$?
set -e

exit "$status"
