import subprocess
from pathlib import Path

import pytest
import yaml

_ACTION = Path(__file__).resolve().parents[1] / "prepare-release-metadata" / "action.yml"
_AVAILABLE = "crates,cli,homebrew,scoop"


def _resolve_targets(tmp_path: Path, event: str, requested: str, dispatch: str = "docker") -> str:
    action = yaml.safe_load(_ACTION.read_text())
    step = next(step for step in action["runs"]["steps"] if step.get("id") == "prepare")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stubs = {
        "alef": '#!/bin/bash\nprintf "%s\\n" "$@" >>"$ALEF_ARGS"\nprintf "{}\\n"\n',
        "jq": '#!/bin/bash\nwhile IFS= read -r line; do\n  if [[ "$1" == "." ]]; then printf "%s\\n" "$line"; fi\ndone\n',
    }
    for name, source in stubs.items():
        stub = bin_dir / name
        stub.write_text(source)
        stub.chmod(0o755)
    args_file = tmp_path / "alef_args"
    env = {
        "PATH": str(bin_dir),
        "ALEF_ARGS": str(args_file),
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "GITHUB_SHA": "a" * 40,
        "GITHUB_REF_NAME": "v1.2.3",
        "EVENT_NAME": event,
        "INPUT_TAG": "v1.2.3" if event == "workflow_dispatch" else "",
        "INPUT_DRY_RUN": "false",
        "INPUT_FORCE_REPUBLISH": "false",
        "INPUT_REF": "",
        "INPUT_TARGETS": requested,
        "EVENT_RELEASE_TAG": "v1.2.3",
        "EVENT_DISPATCH_TAG": "v1.2.3",
        "EVENT_DISPATCH_DRY_RUN": "false",
        "EVENT_DISPATCH_FORCE_REPUBLISH": "false",
        "EVENT_DISPATCH_REF": "",
        "EVENT_DISPATCH_TARGETS": dispatch,
        "AVAILABLE_TARGETS": _AVAILABLE,
    }
    result = subprocess.run(
        ["/bin/bash", "-c", step["run"]],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert args_file.is_file(), "the actual action must invoke alef"
    args = args_file.read_text().splitlines()
    assert args.count("release-metadata") == args.count("--targets") == 1
    return args[args.index("--targets") + 1]


@pytest.mark.parametrize("event", ["release", "repository_dispatch", "workflow_dispatch", "push"])
@pytest.mark.parametrize("requested", ["crates,cli", "none"])
def test_explicit_targets_override_the_event_defaults(tmp_path, event, requested):
    assert _resolve_targets(tmp_path, event, requested) == requested


@pytest.mark.parametrize(
    ("event", "dispatch", "expected"),
    [
        ("release", "docker", _AVAILABLE),
        ("repository_dispatch", "docker", "docker"),
        ("repository_dispatch", "", _AVAILABLE),
        ("workflow_dispatch", "docker", _AVAILABLE),
        ("push", "docker", _AVAILABLE),
    ],
)
def test_empty_target_input_preserves_event_and_available_fallbacks(tmp_path, event, dispatch, expected):
    assert _resolve_targets(tmp_path, event, "", dispatch) == expected
