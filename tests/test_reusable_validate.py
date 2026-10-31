from pathlib import Path

import yaml

_WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "reusable-validate.yml"


def _workflow_content() -> str:
    return _WORKFLOW.read_text()


def test_fixture_snippet_gate_is_backward_compatible():
    content = _workflow_content()

    assert "check-fixture-snippets:" in content
    assert "alef-version:" in content
    assert "default: false" in content
    assert 'default: "latest"' in content


def test_go_toolchain_default_matches_consumer_workspaces():
    content = _workflow_content()
    go_input = content.split("go-version:", 1)[1].split("golangci-lint-version:", 1)[0]

    assert 'default: "1.26"' in go_input


def test_fixture_snippet_gate_installs_generates_checks_drift_and_validates():
    content = _workflow_content()
    expected_in_order = [
        "uses: xberg-io/actions/install-alef@v1",
        "run: alef e2e generate",
        "run: git diff --exit-code",
        "run: alef snippets check --strict --cache off",
    ]

    positions = [content.index(fragment) for fragment in expected_in_order]
    assert positions == sorted(positions)
    assert "version: ${{ inputs.alef-version }}" in content


def test_every_snippet_gated_step_is_accounted_for():
    """Pin the exact set of steps gated on `check-fixture-snippets`, by name.

    A bare count broke the moment the pnpm/wasm-pack setup steps were added, and a count
    cannot tell "someone added a gated step" from "someone dropped a gate". Naming them
    fails loudly in both directions: an ungated addition never appears here, and a step
    that silently loses its gate disappears from this set. ~keep
    """
    gated = []
    current_name = None
    for line in _workflow_content().splitlines():
        stripped = line.strip()
        if stripped.startswith("- name:"):
            current_name = stripped.removeprefix("- name:").strip()
        elif "inputs.check-fixture-snippets" in stripped and stripped.startswith("if:"):
            gated.append(current_name)

    assert gated == [
        "Install alef CLI",
        "Generate fixture snippets",
        "Check fixture snippet drift",
        "Set up Node.js and pnpm",
        "Set up wasm-pack",
        "Validate fixture snippets",
    ]


def _workflow() -> dict:
    return yaml.safe_load(_workflow_content())


def test_toolchain_gate_is_opt_in():
    inputs = _workflow()[True]["workflow_call"]["inputs"]

    assert inputs["check-toolchain"]["type"] == "boolean"
    assert inputs["check-toolchain"]["default"] is False


def test_toolchain_gate_runs_check_toolchain_right_after_checkout():
    steps = _workflow()["jobs"]["validate"]["steps"]

    assert steps[0]["uses"] == "actions/checkout@v7"
    assert steps[1]["uses"] == "xberg-io/actions/check-toolchain@v1"
    assert steps[1]["if"] == "${{ inputs.check-toolchain }}"
    assert [step for step in steps if "check-toolchain" in str(step.get("if", ""))] == [steps[1]]


def test_adr_gate_is_opt_in():
    inputs = _workflow()[True]["workflow_call"]["inputs"]

    assert inputs["check-adrs"]["type"] == "boolean"
    assert inputs["check-adrs"]["default"] is False


def test_adr_gate_installs_adrlint_from_mise_then_lints_formats_and_checks_the_lock():
    steps = _workflow()["jobs"]["validate"]["steps"]
    gated = [step for step in steps if "inputs.check-adrs" in str(step.get("if", ""))]

    assert [step.get("uses") for step in gated] == ["xberg-io/actions/setup-mise@v1", None]
    assert gated[0]["with"]["install-args"] == "github:Goldziher/adrlint"
    script = gated[1]["run"]
    commands = ["adrlint lint --format github", "adrlint format --check", "adrlint lock --check"]
    positions = [script.index(command) for command in commands]
    assert positions == sorted(positions)


def test_adr_gate_fails_when_no_adr_was_checked():
    steps = _workflow()["jobs"]["validate"]["steps"]
    script = next(step["run"] for step in steps if step.get("name") == "Check the ADR log")

    assert "summary=$(adrlint lint 2>&1)" in script, "adrlint prints its summary on stderr"
    assert "files? checked" in script
    assert "-gt 0" in script


def test_toolchains_install_through_mise_instead_of_setup_actions():
    steps = _workflow()["jobs"]["validate"]["steps"]
    uses = [str(step.get("uses", "")) for step in steps]
    for action in ("actions/setup-python@", "astral-sh/setup-uv@", "actions/setup-java@", "actions/setup-go@"):
        assert not [ref for ref in uses if ref.startswith(action)], action
    toolchains = next(step for step in steps if step.get("name") == "Set up the toolchains through mise")
    assert toolchains["uses"] == "xberg-io/actions/setup-mise@v1"
    tools = toolchains["with"]["tools"]
    for fragment in (
        "format('python={0} uv', inputs.python-version)",
        "format('{0}-{1}', inputs.java-distribution, inputs.java-version)",
        "format('go={0}', inputs.go-version)",
        "runner.os != 'Windows' && format('ruby={0}', inputs.ruby-version)",
    ):
        assert fragment in tools, fragment


def test_ruby_stays_on_setup_ruby_only_where_mise_has_a_lock_gap():
    steps = _workflow()["jobs"]["validate"]["steps"]
    setup_ruby = [step for step in steps if str(step.get("uses", "")).startswith("ruby/setup-ruby@")]
    assert len(setup_ruby) == 1
    assert setup_ruby[0]["if"] == "${{ inputs.setup-ruby && runner.os == 'Windows' }}"
    bundle = next(step for step in steps if step.get("name") == "Install the Ruby bundle")
    assert "runner.os != 'Windows'" in bundle["if"]
    assert "bundle install" in bundle["run"]


def test_toolchain_versions_default_to_the_callers_mise_config():
    inputs = _workflow()[True]["workflow_call"]["inputs"]

    for name in ("python-version", "java-version", "ruby-version", "zig-version"):
        assert inputs[name]["default"] == "", name


def test_action_pin_lint_is_opt_in():
    inputs = _workflow()[True]["workflow_call"]["inputs"]

    assert inputs["lint-action-pins"]["type"] == "boolean"
    assert inputs["lint-action-pins"]["default"] is False


def test_action_pin_lint_installs_gau_then_lints_github_and_every_action_file():
    steps = _workflow()["jobs"]["validate"]["steps"]
    gated = [step for step in steps if "inputs.lint-action-pins" in str(step.get("if", ""))]

    assert [step.get("uses") for step in gated] == ["xberg-io/actions/setup-mise@v1", None]
    assert gated[0]["with"]["tools"] == "github:Goldziher/gh-actions-updater"
    script = gated[1]["run"]
    assert gated[1]["shell"] == "bash"
    assert 'gau --lint-pins "${paths[@]}"' in script
    assert "paths+=(.github)" in script
    assert "':(glob)**/action.yml' ':(glob)**/action.yaml'" in script
    assert "--config" not in script, "an explicit --config would skip the caller's .gh-actions-updater.toml"


def test_action_pin_lint_fails_when_no_file_was_scanned():
    steps = _workflow()["jobs"]["validate"]["steps"]
    script = next(step["run"] for step in steps if step.get("name") == "Lint the action pins")

    assert "across ([0-9]+) file" in script
    assert '[ "${scanned:-0}" -gt 0 ]' in script
    assert 'exit "$status"' in script
