#!/usr/bin/env bash
# Commit the manifests render.py wrote and push them to the bucket's remote.
#
# Inputs (env):
#   BUCKET_DIR         Checked-out bucket whose credentials allow pushing.
#   MANIFESTS_CHANGED  Newline-separated manifest paths render.py wrote.
#   COMMIT_MESSAGE     Commit subject.
#   GIT_USER_NAME      Committer name.
#   GIT_USER_EMAIL     Committer email.
#   PUSH_ATTEMPTS      Push attempts before giving up (default 5).
#   PUSH_BACKOFF       Seconds per attempt to wait before a retry (default 3).
#
# Outputs (GITHUB_OUTPUT):
#   committed          'true' when a commit was pushed, 'false' when nothing changed.
set -euo pipefail

: "${BUCKET_DIR:?BUCKET_DIR is required}"
: "${COMMIT_MESSAGE:?COMMIT_MESSAGE is required}"
: "${GIT_USER_NAME:?GIT_USER_NAME is required}"
: "${GIT_USER_EMAIL:?GIT_USER_EMAIL is required}"
attempts="${PUSH_ATTEMPTS:-5}"
backoff="${PUSH_BACKOFF:-3}"

cd "${BUCKET_DIR}"

manifests=()
while IFS= read -r manifest; do
  [[ -n "${manifest}" ]] && manifests+=("${manifest}")
done <<<"${MANIFESTS_CHANGED:-}"

if [[ ${#manifests[@]} -eq 0 ]]; then
  echo "No manifests rendered; nothing to commit."
  echo "committed=false" >>"${GITHUB_OUTPUT:-/dev/null}"
  exit 0
fi

git config user.name "${GIT_USER_NAME}"
git config user.email "${GIT_USER_EMAIL}"

# Stage before comparing: `git diff --quiet` ignores untracked files, so an app's first
# manifest never counted as a change and was never committed. ~keep
git add -- "${manifests[@]}"
if git diff --cached --quiet -- "${manifests[@]}"; then
  echo "Manifests already match the bucket; skipping commit."
  echo "committed=false" >>"${GITHUB_OUTPUT:-/dev/null}"
  exit 0
fi

git commit --quiet -m "${COMMIT_MESSAGE}" -- "${manifests[@]}"

# Several release pipelines push to one bucket, so a concurrent release can land between
# checkout and push. Each touches only its own manifests, so rebasing onto the new tip and
# retrying is safe; a real conflict aborts rather than forcing the push. ~keep
branch="$(git rev-parse --abbrev-ref HEAD)"
for ((attempt = 1; attempt <= attempts; attempt++)); do
  if git push origin "HEAD:${branch}"; then
    echo "committed=true" >>"${GITHUB_OUTPUT:-/dev/null}"
    exit 0
  fi
  if ((attempt == attempts)); then
    break
  fi
  echo "Push rejected (attempt ${attempt}/${attempts}); rebasing onto the current bucket tip"
  git fetch origin "${branch}"
  if ! git rebase "origin/${branch}"; then
    git rebase --abort || true
    echo "::error::Rebasing the bucket commit hit a conflict; refusing to force the push"
    exit 1
  fi
  sleep $((attempt * backoff))
done

echo "::error::Could not push to the bucket after ${attempts} attempts"
exit 1
