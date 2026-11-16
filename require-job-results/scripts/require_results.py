#!/usr/bin/env python3
"""Fail when a needed job did not finish with a result the publishing channel accepts.

Inputs (env):
  INPUT_CHANNEL               Channel name for messages.
  INPUT_NEEDS                 JSON of the caller's `needs` context.
  INPUT_SUCCEEDED             Jobs that must be `success` (newline or comma separated).
  INPUT_SUCCEEDED_OR_SKIPPED  Jobs that must be `success` or `skipped`.
"""

from __future__ import annotations

import json
import os
import re
import sys


def parse_jobs(raw: str) -> list[str]:
    return [job for job in (part.strip() for part in re.split(r"[\n,]", raw)) if job]


def blocking_jobs(needs: dict[str, dict], succeeded: list[str], succeeded_or_skipped: list[str]) -> list[str]:
    """Return one message per job whose result blocks the channel."""
    problems: list[str] = []
    for jobs, accepted in ((succeeded, {"success"}), (succeeded_or_skipped, {"success", "skipped"})):
        for job in jobs:
            if job not in needs:
                problems.append(f"{job} is not in this job's needs, so its result cannot be checked")
                continue
            result = needs[job].get("result", "")
            if result not in accepted:
                problems.append(f"{job} finished '{result}' (needs {' or '.join(sorted(accepted))})")
    return problems


def main() -> int:
    channel = os.environ.get("INPUT_CHANNEL", "").strip() or "this channel"
    try:
        needs = json.loads(os.environ.get("INPUT_NEEDS", "") or "null")
    except json.JSONDecodeError as exc:
        print(f"::error::require-job-results: `needs` is not JSON ({exc}); pass ${{{{ toJSON(needs) }}}}")
        return 1
    if not isinstance(needs, dict):
        print("::error::require-job-results: `needs` must be the JSON object from ${{ toJSON(needs) }}")
        return 1

    succeeded = parse_jobs(os.environ.get("INPUT_SUCCEEDED", ""))
    succeeded_or_skipped = parse_jobs(os.environ.get("INPUT_SUCCEEDED_OR_SKIPPED", ""))
    if not succeeded and not succeeded_or_skipped:
        print("::error::require-job-results: name at least one job in `succeeded` or `succeeded-or-skipped`")
        return 1

    problems = blocking_jobs(needs, succeeded, succeeded_or_skipped)
    if problems:
        for problem in problems:
            print(f"::error title={channel} not published::{problem}")
        print(f"{channel} is blocked: {len(problems)} required job(s) did not finish as needed.")
        return 1

    checked = len(succeeded) + len(succeeded_or_skipped)
    print(f"{channel}: all {checked} required job result(s) accepted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
