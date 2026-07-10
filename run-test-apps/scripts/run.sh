#!/bin/bash
set -euo pipefail

LANGUAGE="${INPUT_LANGUAGE}"
WORKING_DIRECTORY="${INPUT_WORKING_DIRECTORY:-.}"
LOG_PATH="/tmp/test-apps-${LANGUAGE}.log"

cd "${WORKING_DIRECTORY}"

echo "Generating test-apps for ${LANGUAGE}..."
alef test-apps generate --lang "${LANGUAGE}" --clean

echo "Running test-apps for ${LANGUAGE}..."
set +e
alef test-apps run --lang "${LANGUAGE}" 2>&1 | tee "${LOG_PATH}"
exit_code=${PIPESTATUS[0]}
set -e

if [ "$exit_code" -eq 0 ]; then
	passed="true"
else
	passed="false"
fi

{
	echo "passed=${passed}"
	echo "exit-code=${exit_code}"
	echo "log-path=${LOG_PATH}"
} >>"$GITHUB_OUTPUT"

echo "Test-apps for ${LANGUAGE}: exit_code=${exit_code}, log=${LOG_PATH}"
exit "$exit_code"
