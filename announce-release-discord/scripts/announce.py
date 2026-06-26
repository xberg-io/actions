#!/usr/bin/env python3
"""Post a release announcement to Discord, idempotently.

Behavior:
  - Skip prerelease tags (any tag containing a '-' suffix per semver).
  - Dedup via a marker asset (discord-announced.marker) on the GitHub Release —
    surviving tag delete/recreate republish cycles, since the prepare job
    only creates the release if missing.
  - Fetch release notes from the GitHub Release body when not provided, stripping
    language install snippets and regenerating GitHub release notes when the body
    has been replaced by package-specific instructions.
  - POST a Discord embed via the webhook.
  - Upload the marker asset on success.

All inputs are passed via INPUT_* environment variables to match the
existing publish-github-release/scripts/ensure_release.py convention.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, cast

# Asset names starting with a dot get renamed by GitHub's release-asset API
# (e.g. `.discord-announced` becomes `default.discord-announced`), which breaks
# dedup — so we use a plain name. The legacy dot-prefixed form is also
# accepted by `already_announced` for backward compat with releases that were
# marked before this fix.
MARKER_ASSET_NAME = "discord-announced.marker"
LEGACY_MARKER_ASSET_NAMES = frozenset({".discord-announced", "default.discord-announced"})
DISCORD_DESCRIPTION_LIMIT = 4000
DEFAULT_EMBED_COLOR = 0x5865F2  # Discord Blurple
STABLE_TAG_PATTERN = re.compile(r"^v\d+\.\d+\.\d+$")
ALLOWED_WEBHOOK_SCHEMES = frozenset({"https"})
RELEASE_FIELDS = "body,name,publishedAt,targetCommitish,url"
PACKAGE_INSTALL_SECTION_PATTERNS = (
    re.compile(r"(?im)^\s*<!--\s*zig-fetch\s*-->\s*$"),
    re.compile(r"(?im)^\s*#{0,6}\s*Swift Package Manager\s*$"),
    re.compile(r"(?im)^\s*#{1,6}\s*Zig\s*$"),
)


def env_str(key: str, default: str = "") -> str:
    value = os.environ.get(key, default) or default
    return value.strip()


def env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw in {"true", "1", "yes", "y", "on"}


def parse_color(raw: str) -> int:
    raw = raw.strip()
    if not raw:
        return DEFAULT_EMBED_COLOR
    base = 16 if raw.lower().startswith("0x") or raw.startswith("#") else 10
    cleaned = raw.removeprefix("#").removeprefix("0x").removeprefix("0X")
    try:
        return int(cleaned, base)
    except ValueError:
        return DEFAULT_EMBED_COLOR


def gh_release_view(tag: str, fields: str, repo: str) -> dict[str, Any] | None:
    cmd = ["gh", "release", "view", tag, "--json", fields]
    if repo:
        cmd.extend(["--repo", repo])
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        if result.stderr:
            print(f"Warning: gh release view failed: {result.stderr.strip()}", file=sys.stderr)
        return None
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return cast("dict[str, Any]", parsed) if isinstance(parsed, dict) else None


def already_announced(tag: str, repo: str) -> bool:
    payload = gh_release_view(tag, "assets", repo)
    if not payload:
        return False
    accepted = LEGACY_MARKER_ASSET_NAMES | {MARKER_ASSET_NAME}
    return any(asset.get("name") in accepted for asset in payload.get("assets") or [])


def fetch_release(tag: str, repo: str) -> dict[str, Any]:
    payload = gh_release_view(tag, RELEASE_FIELDS, repo)
    return payload or {}


def generate_release_notes(tag: str, repo: str, target_commitish: str = "") -> dict[str, Any]:
    cmd = [
        "gh",
        "api",
        f"repos/{repo}/releases/generate-notes",
        "-X",
        "POST",
        "-f",
        f"tag_name={tag}",
    ]
    if target_commitish:
        cmd.extend(["-f", f"target_commitish={target_commitish}"])

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        if result.stderr:
            print(f"Warning: gh release generate-notes failed: {result.stderr.strip()}", file=sys.stderr)
        return {}
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    return cast("dict[str, Any]", parsed) if isinstance(parsed, dict) else {}


def is_placeholder_release_note(body: str, tag: str) -> bool:
    return body.strip() == f"Release {tag}"


def release_log_from_body(raw: str, tag: str) -> str:
    body = (raw or "").strip()
    if not body:
        return ""

    section_starts = [
        match.start() for pattern in PACKAGE_INSTALL_SECTION_PATTERNS if (match := pattern.search(body)) is not None
    ]
    if section_starts:
        body = body[: min(section_starts)].strip()

    if is_placeholder_release_note(body, tag):
        return ""
    return body


def release_log_for_announcement(release: dict[str, Any], tag: str, repo: str) -> str:
    body_log = release_log_from_body(str(release.get("body") or ""), tag)
    if body_log:
        return body_log

    generated = generate_release_notes(tag, repo, str(release.get("targetCommitish") or ""))
    return str(generated.get("body") or "").strip()


def normalize_notes(raw: str, tag: str) -> str:
    body = (raw or "").strip()
    if not body or is_placeholder_release_note(body, tag):
        return "_No release notes provided._"
    if len(body) > DISCORD_DESCRIPTION_LIMIT:
        body = body[: DISCORD_DESCRIPTION_LIMIT - 1].rstrip() + "…"
    return body


def project_name_from_repo(repo: str) -> str:
    if "/" in repo:
        return repo.split("/", 1)[1]
    return repo


def build_payload(
    *,
    tag: str,
    repo: str,
    project_name: str,
    description: str,
    color: int,
    timestamp: str,
) -> dict[str, Any]:
    return {
        "username": "xberg releases",
        "embeds": [
            {
                "title": f"{project_name} {tag}",
                "url": f"https://github.com/{repo}/releases/tag/{tag}",
                "description": description,
                "color": color,
                "timestamp": timestamp,
                "footer": {"text": repo},
            }
        ],
    }


def validate_webhook_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ALLOWED_WEBHOOK_SCHEMES:
        print(
            f"Error: webhook URL scheme '{parsed.scheme}' not allowed (must be https)",
            file=sys.stderr,
        )
        sys.exit(1)
    if not parsed.netloc:
        print("Error: webhook URL is missing a host", file=sys.stderr)
        sys.exit(1)


def post_to_discord(webhook_url: str, payload: dict[str, Any]) -> None:
    validate_webhook_url(webhook_url)
    request = urllib.request.Request(  # noqa: S310 — scheme validated above
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "xberg-release-announcer"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 — scheme validated above
            status = response.status
            if status >= 300:
                body = response.read().decode("utf-8", errors="replace")
                print(f"Error: Discord webhook returned HTTP {status}: {body}", file=sys.stderr)
                sys.exit(1)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"Error: Discord webhook returned HTTP {exc.code}: {body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"Error: failed to reach Discord webhook: {exc.reason}", file=sys.stderr)
        sys.exit(1)


def upload_marker(tag: str, repo: str) -> bool:
    """Upload the dedup marker asset best-effort.

    The marker contains the tag string (rather than being empty) because
    GitHub's asset-upload API rejects zero-byte bodies with HTTP 400. Dedup
    only checks the asset *name* (see already_announced), so any non-empty
    content works.

    Failures here do not propagate: by the time we reach this function the
    Discord post has already happened, so failing the step would create
    noisy CI for no useful reason. We log a warning and move on; the worst
    case is a duplicate announcement on the next workflow rerun.
    """
    marker = Path(MARKER_ASSET_NAME)
    marker.write_text(f"{tag}\n")
    try:
        cmd = ["gh", "release", "upload", tag, str(marker), "--clobber"]
        if repo:
            cmd.extend(["--repo", repo])
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as exc:
            print(
                f"Warning: failed to upload {MARKER_ASSET_NAME} marker (exit {exc.returncode}); "
                "Discord post already succeeded, continuing.",
                file=sys.stderr,
            )
            return False
        return True
    finally:
        marker.unlink(missing_ok=True)


def write_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT", "")
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as fh:
        fh.write(f"{name}={value}\n")


def main() -> None:
    tag = env_str("INPUT_TAG")
    webhook_url = env_str("INPUT_WEBHOOK_URL")
    repo = env_str("INPUT_REPO") or env_str("GITHUB_REPOSITORY")
    project_name = env_str("INPUT_PROJECT_NAME") or project_name_from_repo(repo)
    notes_override = env_str("INPUT_NOTES")
    color = parse_color(env_str("INPUT_COLOR", "0x5865F2"))
    dry_run = env_bool("INPUT_DRY_RUN", default=False)

    if not tag:
        print("Error: INPUT_TAG is required", file=sys.stderr)
        sys.exit(1)
    if not webhook_url:
        print("Error: INPUT_WEBHOOK_URL is required", file=sys.stderr)
        sys.exit(1)
    if not repo:
        print("Error: INPUT_REPO (or GITHUB_REPOSITORY) is required", file=sys.stderr)
        sys.exit(1)

    if not STABLE_TAG_PATTERN.match(tag):
        print(f"Skipping prerelease tag {tag} (only vMAJOR.MINOR.PATCH announced)")
        write_output("posted", "skipped-prerelease")
        return

    if not dry_run and already_announced(tag, repo):
        print(f"Already announced {tag} — skipping (marker asset present on release)")
        write_output("posted", "skipped-already-announced")
        return

    if notes_override:
        description = normalize_notes(notes_override, tag)
        timestamp = _dt.datetime.now(tz=_dt.timezone.utc).isoformat()
    else:
        release = fetch_release(tag, repo)
        description = normalize_notes(release_log_for_announcement(release, tag, repo), tag)
        timestamp = release.get("publishedAt") or _dt.datetime.now(tz=_dt.timezone.utc).isoformat()

    payload = build_payload(
        tag=tag,
        repo=repo,
        project_name=project_name,
        description=description,
        color=color,
        timestamp=timestamp,
    )

    if dry_run:
        print("[dry-run] Would POST to Discord:")
        print(json.dumps(payload, indent=2))
        write_output("posted", "false")
        return

    post_to_discord(webhook_url, payload)
    print(f"Posted {tag} announcement to Discord")

    if upload_marker(tag, repo):
        print(f"Uploaded {MARKER_ASSET_NAME} marker to release {tag}")
    write_output("posted", "true")


if __name__ == "__main__":
    main()
