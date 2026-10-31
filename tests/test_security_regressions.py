"""Adversarial regression tests for the composite-action / workflow shell-injection fixes.

Each test extracts the *actual* `run:` script for a named step straight out of the real
action.yml / workflow.yml file (never a copy pasted into this file), executes it with a real
bash, and asserts on argv arrays or marker-file side effects — never on a rejoined string, which
is precisely the kind of assertion that hid the word-splitting defect this file's build-rust-cli
tests were added to catch. A rejected/legitimate distinction always checks *both* directions:
that a hostile value is inert and that a real value still works.
"""

import os
import stat
import subprocess
import textwrap
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _composite_step(action_path: str, step_name: str) -> dict:
    """Return the raw step mapping for `step_name` in a composite action.yml's runs.steps."""
    doc = yaml.safe_load((_REPO_ROOT / action_path).read_text())
    for step in doc["runs"]["steps"]:
        if step.get("name") == step_name:
            return step
    raise AssertionError(f"step {step_name!r} not found in {action_path}")


def _workflow_step(workflow_path: str, job_name: str, step_name: str) -> dict:
    """Return the raw step mapping for `step_name` in a workflow.yml job's steps."""
    doc = yaml.safe_load((_REPO_ROOT / workflow_path).read_text())
    for step in doc["jobs"][job_name].get("steps", []):
        if step.get("name") == step_name:
            return step
    raise AssertionError(f"step {step_name!r} not found in {workflow_path}::{job_name}")


def _run_step_script(step: dict, env: dict[str, str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Execute a step's `run:` body with bash, given a fully-resolved env (as GHA would set it).

    `step["env"]` values are still literal `${{ ... }}` expression text (this repo does not run
    a GitHub Actions expression evaluator) — callers pass the *already-substituted* env dict they
    want the script to see, mirroring exactly what GHA hands the shell after evaluating those
    expressions.
    """
    script = step["run"]
    full_env = {**os.environ, **env}
    return subprocess.run(
        ["bash", "-c", script],
        env=full_env,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _make_stub_bin(tmp_path: Path, name: str, body: str) -> Path:
    """Write an executable stub script named `name` into a fresh bin dir, return the bin dir."""
    bin_dir = tmp_path / "stubbin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / name
    stub.write_text(f"#!/bin/bash\n{body}\n")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


# ---------------------------------------------------------------------------
# build-rust-cli: extra-cargo-args (blocker 1 — xargs -n1 word-splitting fix)
# ---------------------------------------------------------------------------


def _cargo_argv_test_env(tmp_path: Path, extra_cargo_args: str) -> tuple[dict, Path]:
    stub_bin = _make_stub_bin(
        tmp_path,
        "cargo",
        textwrap.dedent(
            """\
            for a in "$@"; do
              printf '%s\\0' "$a"
            done > "$CARGO_ARGV_FILE"
            """
        ),
    )
    argv_file = tmp_path / "cargo_argv.nul"
    env = {
        "PATH": f"{stub_bin}:{os.environ['PATH']}",
        "RUST_PACKAGE_NAME": "demo-pkg",
        "RUST_BINARY_NAME": "demo-bin",
        "RUST_TARGET": "",
        "RUST_GLIBC_VERSION": "",
        "RUST_EXTRA_CARGO_ARGS": extra_cargo_args,
        "RUNNER_OS": "Linux",
        "GITHUB_WORKSPACE": str(tmp_path),
        "GITHUB_OUTPUT": str(tmp_path / "github_output.txt"),
        "CARGO_ARGV_FILE": str(argv_file),
    }
    return env, argv_file


def _read_argv(argv_file: Path) -> list[str]:
    if not argv_file.exists():
        return []
    raw = argv_file.read_bytes()
    return raw.decode().split("\0")[:-1] if raw else []


def _build_step():
    return _composite_step("build-rust-cli/action.yml", "Build CLI binary")


def test_extra_cargo_args_quoted_multiword_preserves_one_token(tmp_path):
    """A quoted multi-word value stays ONE argv entry, not split apart by its inner space.

    This is exactly the case that read -ra silently broke: it does not honor quoting, so
    `--features "foo bar"` became the two literal tokens `"foo` and `bar"`.
    """
    env, argv_file = _cargo_argv_test_env(tmp_path, '--features "foo bar"')
    (tmp_path / "github_output.txt").touch()
    result = _run_step_script(_build_step(), env, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    argv = _read_argv(argv_file)
    extra = argv[argv.index("--locked") :]
    assert extra == ["--locked", "--release", "--package", "demo-pkg", "--features", "foo bar"]
    assert len(extra) == 6


def test_extra_cargo_args_multiline_preserves_every_line(tmp_path):
    """Every newline-separated line survives as its own argv entry; none is silently dropped.

    This is exactly the case that read -ra silently broke: it only reads the FIRST line of a
    here-string, discarding every subsequent line without any error.
    """
    env, argv_file = _cargo_argv_test_env(tmp_path, "--features foo\n--no-default-features")
    (tmp_path / "github_output.txt").touch()
    result = _run_step_script(_build_step(), env, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    argv = _read_argv(argv_file)
    extra = argv[argv.index("--locked") :]
    assert extra == ["--locked", "--release", "--package", "demo-pkg", "--features", "foo", "--no-default-features"]
    assert len(extra) == 7


def test_extra_cargo_args_plain_multiflag_unchanged(tmp_path):
    """The originally-tested shape (space-separated, no quotes) still works as before."""
    env, argv_file = _cargo_argv_test_env(tmp_path, "--features foo --no-default-features")
    (tmp_path / "github_output.txt").touch()
    result = _run_step_script(_build_step(), env, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    argv = _read_argv(argv_file)
    extra = argv[argv.index("--locked") :]
    assert extra == ["--locked", "--release", "--package", "demo-pkg", "--features", "foo", "--no-default-features"]


def test_extra_cargo_args_semicolon_injection_is_inert(tmp_path):
    """A `;`-separated second command never runs; it becomes literal argv tokens instead."""
    marker = tmp_path / "PWNED_semicolon"
    env, argv_file = _cargo_argv_test_env(tmp_path, f"--features foo; touch {marker} #")
    (tmp_path / "github_output.txt").touch()
    result = _run_step_script(_build_step(), env, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert not marker.exists(), "injected `touch` executed as a second command"
    argv = _read_argv(argv_file)
    extra = argv[argv.index("--locked") :]
    # xargs -n1 still splits on whitespace like the old behavior did — the point is that
    # the semicolon and its trailing text arrive as inert argv tokens, never as a second
    # shell command, which the marker-file assertion above already proved.
    assert extra == [
        "--locked",
        "--release",
        "--package",
        "demo-pkg",
        "--features",
        "foo;",
        "touch",
        str(marker),
        "#",
    ]
    assert len(extra) == 9


def test_extra_cargo_args_command_substitution_is_inert(tmp_path):
    """`$(...)` and backtick command substitution never execute; they stay literal text."""
    marker1 = tmp_path / "PWNED_dollar"
    marker2 = tmp_path / "PWNED_backtick"
    env, _argv_file = _cargo_argv_test_env(tmp_path, f"--features $(touch {marker1}) `touch {marker2}`")
    (tmp_path / "github_output.txt").touch()
    result = _run_step_script(_build_step(), env, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert not marker1.exists(), "$() command substitution executed"
    assert not marker2.exists(), "backtick command substitution executed"


def test_extra_cargo_args_unbalanced_quote_fails_loudly(tmp_path):
    """Malformed input (an unbalanced quote) fails the step instead of silently truncating it."""
    env, _argv_file = _cargo_argv_test_env(tmp_path, '--features "foo')
    (tmp_path / "github_output.txt").touch()
    result = _run_step_script(_build_step(), env, cwd=tmp_path)
    assert result.returncode != 0
    assert "extra-cargo-args could not be parsed" in result.stderr


def test_extra_cargo_args_literal_backslash_caveat_is_documented_behavior(tmp_path):
    """Known, accepted trade-off: xargs treats backslash as an escape, collapsing it.

    This asserts the *documented* behavior so a future change to the parsing approach is
    forced to update this test deliberately rather than silently changing the contract.
    """
    env, argv_file = _cargo_argv_test_env(tmp_path, r"--features foo\bar")
    (tmp_path / "github_output.txt").touch()
    result = _run_step_script(_build_step(), env, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    argv = _read_argv(argv_file)
    extra = argv[argv.index("--locked") :]
    assert extra == ["--locked", "--release", "--package", "demo-pkg", "--features", "foobar"]


def _extra_only_argv(argv: list[str]) -> list[str]:
    """The variable-length tail of argv contributed by extra-cargo-args alone.

    argv is always ["--locked", "--release", "--package", "demo-pkg", *extra]: TARGET_FLAG is
    empty for these tests (RUST_TARGET is unset), so this fixed 4-item prefix is exactly where
    the extra-cargo-args-derived entries begin.
    """
    fixed_prefix = ["--locked", "--release", "--package", "demo-pkg"]
    extra = argv[argv.index("--locked") :]
    assert extra[: len(fixed_prefix)] == fixed_prefix
    return extra[len(fixed_prefix) :]


def test_extra_cargo_args_empty_produces_zero_argv_entries(tmp_path):
    """Cardinality pin: an empty value must contribute exactly 0 argv entries."""
    env, argv_file = _cargo_argv_test_env(tmp_path, "")
    (tmp_path / "github_output.txt").touch()
    result = _run_step_script(_build_step(), env, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    extra_only = _extra_only_argv(_read_argv(argv_file))
    assert len(extra_only) == 0
    assert extra_only == []


def test_extra_cargo_args_whitespace_only_produces_zero_argv_entries(tmp_path):
    """Cardinality pin: a whitespace-only value must contribute exactly 0 argv entries.

    Regression for a residual defect found after the xargs fix landed: `[[ -n "$VAR" ]]`
    passes for "   " (non-empty), so the split-and-accumulate logic used to run; xargs -n1
    emits nothing for whitespace-only input, but `while read <<< ""` still yields one empty
    line, so exactly one stray empty-string argv entry reached cargo (n=1, argv[0] == "").
    The fix guards on the *split result* being non-empty, not the raw input.
    """
    env, argv_file = _cargo_argv_test_env(tmp_path, "   \t  \n  ")
    (tmp_path / "github_output.txt").touch()
    result = _run_step_script(_build_step(), env, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    extra_only = _extra_only_argv(_read_argv(argv_file))
    assert len(extra_only) == 0
    assert extra_only == []


def test_extra_cargo_args_single_flag_produces_expected_argv_count(tmp_path):
    """Boundary pin: a normal single-flag value still contributes its correct nonzero count.

    Guards against a fix for the whitespace-only case (e.g. an overzealous strip/skip) that
    would also — wrongly — swallow legitimate non-whitespace values.
    """
    env, argv_file = _cargo_argv_test_env(tmp_path, "--features foo")
    (tmp_path / "github_output.txt").touch()
    result = _run_step_script(_build_step(), env, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    extra_only = _extra_only_argv(_read_argv(argv_file))
    assert len(extra_only) == 2
    assert extra_only == ["--features", "foo"]


def test_extra_cargo_args_trailing_quoted_empty_is_preserved(tmp_path):
    """A single explicitly quoted empty argument must survive, in position, not be dropped.

    Regression for a second residual defect: the whitespace-only guard (which checks whether
    the *split result* is non-empty) also silently swallowed a real quoted empty argument,
    because plain `xargs -n1` drops a wholly-empty TRAILING token while preserving a leading or
    middle one — isolated with `printf '%s' '--config ""' | xargs -n1 printf '%s\n' | od -c`,
    which shows only `--config\n` ever leaves xargs; the empty line for `""` never appears.
    `--config ""` is exactly this shape: two tokens, `--config` and an empty string, with the
    empty one trailing.
    """
    env, argv_file = _cargo_argv_test_env(tmp_path, '--config ""')
    (tmp_path / "github_output.txt").touch()
    result = _run_step_script(_build_step(), env, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    extra_only = _extra_only_argv(_read_argv(argv_file))
    assert len(extra_only) == 2
    assert extra_only == ["--config", ""]


def test_extra_cargo_args_middle_versus_trailing_empty_both_preserved(tmp_path):
    """Two quoted empties — one middle, one trailing — must both survive, each in position.

    This is the case that most sharply distinguishes the defect from its fix: plain xargs -n1
    keeps a MIDDLE empty token (between --a and --b) but drops the TRAILING one (after --b), so
    a test using only a middle empty would have passed against the bug. Both must be present
    here, at the correct index, for the fix to be proven — never collapsed into a rejoined
    string, which would hide exactly this position-dependent behavior.
    """
    env, argv_file = _cargo_argv_test_env(tmp_path, '--a "" --b ""')
    (tmp_path / "github_output.txt").touch()
    result = _run_step_script(_build_step(), env, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    extra_only = _extra_only_argv(_read_argv(argv_file))
    assert len(extra_only) == 4
    assert extra_only == ["--a", "", "--b", ""]


# ---------------------------------------------------------------------------
# cleanup-rust-cache: large-artifact-patterns (blocker 2 — confine deletion to target/)
# ---------------------------------------------------------------------------


def _cleanup_step():
    return _composite_step("cleanup-rust-cache/action.yml", "Cleanup build artifacts")


def _cleanup_sandbox(tmp_path: Path) -> Path:
    sandbox = tmp_path / "sandbox"
    (sandbox / "target" / "sub").mkdir(parents=True)
    (sandbox / "canary.txt").write_text("root-level file that must never be touched")
    (sandbox / "target" / "keep.txt").write_text("keep")
    (sandbox / "target" / "big.rlib").write_text("big")
    (sandbox / "target" / "sub" / "file.o").write_text("obj")
    return sandbox


def test_cleanup_rejects_flag_injection_pattern(tmp_path):
    """`--no-preserve-root /`-shaped input is rejected before any rm ever runs."""
    sandbox = _cleanup_sandbox(tmp_path)
    env = {"LARGE_ARTIFACT_PATTERNS": "--no-preserve-root /", "MAX_LIB_SIZE": "+999G"}
    result = _run_step_script(_cleanup_step(), env, cwd=sandbox)
    assert result.returncode == 0
    assert "skipping unsafe large-artifact-patterns entry" in result.stderr
    assert (sandbox / "canary.txt").exists(), "root-level file was deleted"
    assert (sandbox / "target" / "keep.txt").exists()


def test_cleanup_rejects_absolute_path_pattern(tmp_path):
    sandbox = _cleanup_sandbox(tmp_path)
    env = {"LARGE_ARTIFACT_PATTERNS": "/etc/passwd", "MAX_LIB_SIZE": "+999G"}
    result = _run_step_script(_cleanup_step(), env, cwd=sandbox)
    assert result.returncode == 0
    assert "skipping unsafe large-artifact-patterns entry" in result.stderr
    assert Path("/etc/passwd").exists(), "absolute path outside the sandbox was reachable"


def test_cleanup_rejects_traversal_pattern(tmp_path):
    sandbox = _cleanup_sandbox(tmp_path)
    env = {"LARGE_ARTIFACT_PATTERNS": "../canary.txt", "MAX_LIB_SIZE": "+999G"}
    result = _run_step_script(_cleanup_step(), env, cwd=sandbox)
    assert result.returncode == 0
    assert "skipping unsafe large-artifact-patterns entry" in result.stderr
    assert (sandbox / "canary.txt").exists(), "traversal pattern reached outside target/"


def test_cleanup_legitimate_pattern_still_deletes_inside_target(tmp_path):
    """The intended feature — deleting matched files under target/ — still works."""
    sandbox = _cleanup_sandbox(tmp_path)
    env = {"LARGE_ARTIFACT_PATTERNS": "sub/*.o\n*.rlib", "MAX_LIB_SIZE": "+999G"}
    result = _run_step_script(_cleanup_step(), env, cwd=sandbox)
    assert result.returncode == 0, result.stderr
    assert not (sandbox / "target" / "sub" / "file.o").exists()
    assert not (sandbox / "target" / "big.rlib").exists()
    assert (sandbox / "target" / "keep.txt").exists()
    assert (sandbox / "canary.txt").exists()


def test_cleanup_rejects_pattern_that_escapes_via_symlinked_component(tmp_path):
    """A pattern that is ordinary relative text still must not delete through a symlink.

    Regression for a residual defect: text-level rejection (leading '-'/'/' , '..') and
    expanding the glob from inside target/ does not confine anything once a *child of
    target/* is itself a symlink to somewhere else. `target/escape -> outside/` makes
    `escape/*.o` perfectly ordinary relative text that matches straight through the symlink.
    Confinement must be checked on the RESOLVED path of each match, not the pattern text —
    this builds a real symlink and runs the real extracted run: block against it.
    """
    sandbox = _cleanup_sandbox(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "victim.o"
    victim.write_text("must survive")
    (sandbox / "target" / "escape").symlink_to(outside, target_is_directory=True)

    env = {"LARGE_ARTIFACT_PATTERNS": "escape/*.o", "MAX_LIB_SIZE": "+999G"}
    result = _run_step_script(_cleanup_step(), env, cwd=sandbox)

    assert result.returncode == 0, result.stderr
    assert victim.exists(), "deletion escaped target/ through a symlinked path component"
    assert victim.read_text() == "must survive"
    assert "skipping large-artifact-patterns match that resolves outside target/" in result.stderr


# ---------------------------------------------------------------------------
# build-docs: docs-group (blocker 3 — validated before it enters install-command)
# ---------------------------------------------------------------------------


def _validate_docs_group_step():
    return _composite_step("build-docs/action.yml", "Validate docs-group")


def test_docs_group_rejects_shell_metacharacters(tmp_path):
    output = tmp_path / "github_output.txt"
    output.touch()
    env = {"DOCS_GROUP": "doc; rm -rf / #", "GITHUB_OUTPUT": str(output)}
    result = _run_step_script(_validate_docs_group_step(), env)
    assert result.returncode != 0
    assert "docs-group must match" in result.stderr
    assert output.read_text() == ""


def test_docs_group_rejects_command_substitution(tmp_path):
    output = tmp_path / "github_output.txt"
    output.touch()
    env = {"DOCS_GROUP": "doc$(touch pwned)", "GITHUB_OUTPUT": str(output)}
    result = _run_step_script(_validate_docs_group_step(), env)
    assert result.returncode != 0
    assert not (tmp_path / "pwned").exists()


def test_docs_group_accepts_legitimate_names(tmp_path):
    output = tmp_path / "github_output.txt"
    output.touch()
    for value in ("doc", "docs", "my-group_2"):
        output.write_text("")
        env = {"DOCS_GROUP": value, "GITHUB_OUTPUT": str(output)}
        result = _run_step_script(_validate_docs_group_step(), env)
        assert result.returncode == 0, result.stderr
        assert output.read_text().strip() == f"docs-group={value}"


def test_build_docs_install_command_uses_validated_output_not_raw_input():
    """Structural guard: the with: field must reference the validated step output.

    If a future edit reverts to splicing ${{ inputs.docs-group }} straight back into the
    install-command string, this fails even though the validation step above still exists.
    """
    content = (_REPO_ROOT / "build-docs/action.yml").read_text()
    install_command_line = next(line for line in content.splitlines() if "install-command:" in line)
    assert "steps.validate-docs-group.outputs.docs-group" in install_command_line
    assert "inputs.docs-group" not in install_command_line


# ---------------------------------------------------------------------------
# build-python-wheels: build-libheif (blocker 4 — real env var, not a YAML-level splice)
# ---------------------------------------------------------------------------


def _validate_build_libheif_step():
    return _composite_step("build-python-wheels/action.yml", "Validate build-libheif")


def test_build_libheif_accepts_true_and_false(tmp_path):
    for value in ("true", "false"):
        result = _run_step_script(_validate_build_libheif_step(), {"BUILD_LIBHEIF": value})
        assert result.returncode == 0, result.stderr


def test_build_libheif_rejects_non_boolean_shapes(tmp_path):
    for value in ("true; touch pwned #", "$(touch pwned)", "yes", ""):
        result = _run_step_script(_validate_build_libheif_step(), {"BUILD_LIBHEIF": value}, cwd=tmp_path)
        assert result.returncode != 0, f"value {value!r} should have been rejected"
        assert "build-libheif must be" in result.stderr
    assert not (tmp_path / "pwned").exists()


def test_cibw_before_all_linux_never_splices_build_libheif_input():
    """Structural guard: CIBW_BEFORE_ALL_LINUX must read $BUILD_LIBHEIF, never splice the input.

    The env value is substituted by GitHub Actions before cibuildwheel or its container even
    exist, so `${{ inputs.build-libheif }}` inside this string is exploitable regardless of
    anything happening inside the manylinux container — the container boundary is irrelevant to
    this specific injection surface.
    """
    doc = yaml.safe_load((_REPO_ROOT / "build-python-wheels/action.yml").read_text())
    build_step = next(s for s in doc["runs"]["steps"] if s["name"] == "Build wheels")
    cibw_before_all_linux = build_step["env"]["CIBW_BEFORE_ALL_LINUX"]
    assert "inputs.build-libheif" not in cibw_before_all_linux
    assert '$BUILD_LIBHEIF" = "true"' in cibw_before_all_linux
    assert build_step["env"]["CIBW_ENVIRONMENT_PASS_LINUX"] == "BUILD_LIBHEIF"


# ---------------------------------------------------------------------------
# list-language-definitions: definitions-path (64dbf35 — double quote-breakout closed)
# ---------------------------------------------------------------------------


def _list_language_definitions_step():
    return _composite_step("list-language-definitions/action.yml", "Get all language names")


def test_definitions_path_double_breakout_payload_is_inert(tmp_path):
    """The exact payload that ran arbitrary code pre-fix must be inert post-fix.

    Caveat: this harness routes DEFINITIONS_PATH through env, matching the fixed step.
    The pre-fix step never used env: at all -- it spliced ${{ inputs.definitions-path }}
    directly into the script text -- so mutating this file back to that historical shape
    does not exercise this specific test (setting an env var the old script never read is
    a no-op, not a real check). That the payload actually achieves code execution against
    the historical raw-splice shape was confirmed separately: substituting it into the
    literal script text the way GitHub Actions does, then executing the result with real
    bash/python3.
    """
    payload = "' if __import__('os').system('touch pwned') else '"
    output = tmp_path / "github_output.txt"
    output.touch()
    env = {"DEFINITIONS_PATH": payload, "GITHUB_OUTPUT": str(output)}
    _run_step_script(_list_language_definitions_step(), env, cwd=tmp_path)
    assert not (tmp_path / "pwned").exists(), "double quote-breakout payload executed code"
    assert output.read_text().strip() == "names="


def test_definitions_path_resolves_a_real_file_correctly(tmp_path):
    defs = tmp_path / "language_definitions.json"
    defs.write_text('{"python": {}, "go": {}, "rust": {}}')
    output = tmp_path / "github_output.txt"
    output.touch()
    env = {"DEFINITIONS_PATH": str(defs), "GITHUB_OUTPUT": str(output)}
    result = _run_step_script(_list_language_definitions_step(), env, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert output.read_text().strip() == "names=go,python,rust"


# ---------------------------------------------------------------------------
# reusable-validate.yml: golangci-lint-version (2164d21 — env-routed + validated + SHA-pinned)
# ---------------------------------------------------------------------------


def _install_golangci_lint_step():
    return _workflow_step(".github/workflows/reusable-validate.yml", "validate", "Install golangci-lint")


def test_golangci_lint_version_rejects_non_semver_shapes(tmp_path):
    """A malformed version input is rejected before curl (and thus any download) ever runs.

    Caveat: like the list-language-definitions double-breakout test above, this harness sets
    GOLANGCI_LINT_VERSION via env, matching the fixed step. The pre-fix step spliced
    ${{ inputs.golangci-lint-version }} directly into run: with no env: at all, so mutating
    this file back to that historical shape makes the whole script a bash syntax error
    ("bad substitution") for every input, coincidentally also satisfying this test's
    non-zero-exit assertion for the wrong reason. See
    test_install_golangci_lint_routes_version_through_env_not_run_splice below for the
    structural check that does catch that historical shape.
    """
    stub_bin = _make_stub_bin(tmp_path, "curl", 'echo "curl invoked" > "$CURL_CALLED_FILE"; exit 0')
    called_file = tmp_path / "curl_called"
    for value in ("v2.12.2; touch pwned #", "$(touch pwned)", "not-a-version", ""):
        called_file.unlink(missing_ok=True)
        env = {
            "PATH": f"{stub_bin}:{os.environ['PATH']}",
            "GOLANGCI_LINT_VERSION": value,
            "CURL_CALLED_FILE": str(called_file),
        }
        result = _run_step_script(_install_golangci_lint_step(), env, cwd=tmp_path)
        assert result.returncode != 0, f"value {value!r} should have failed validation"
        assert not called_file.exists(), f"curl ran for rejected value {value!r}"
    assert not (tmp_path / "pwned").exists()


def test_golangci_lint_version_accepts_semver_and_reaches_curl(tmp_path):
    """A well-formed version passes validation and the (stubbed) installer actually runs."""
    # The real step does `curl -sSfL URL -o FILE` then `sh FILE ...`. The stub must honor
    # `-o` and actually create that file (with a trivial, well-behaved install script) so the
    # subsequent `sh` invocation has something real to run — a stub that only echoes its args
    # would make the step fail for an unrelated reason (missing file) and mask what this test
    # is actually checking: that curl runs at all for a valid version.
    stub_bin = _make_stub_bin(
        tmp_path,
        "curl",
        textwrap.dedent(
            """\
            echo "$*" > "$CURL_CALLED_FILE"
            out=""
            prev=""
            for a in "$@"; do
              if [ "$prev" = "-o" ]; then
                out="$a"
              fi
              prev="$a"
            done
            if [ -n "$out" ]; then
              printf '#!/bin/sh\nexit 0\n' > "$out"
            fi
            """
        ),
    )
    # A go stub keeps `go env GOPATH` independent of whichever Go the runner image ships. ~keep
    _make_stub_bin(tmp_path, "go", 'echo "$GOPATH"')
    called_file = tmp_path / "curl_called"
    github_path = tmp_path / "github_path"
    env = {
        "PATH": f"{stub_bin}:{os.environ['PATH']}",
        "GOLANGCI_LINT_VERSION": "v2.12.2",
        "CURL_CALLED_FILE": str(called_file),
        "HOME": str(tmp_path),
        "GITHUB_PATH": str(github_path),
        "GOPATH": str(tmp_path / "gopath"),
    }
    result = _run_step_script(_install_golangci_lint_step(), env, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert called_file.exists(), "curl never ran for a valid version"
    assert "c0d3ddc9cf3faa61a4e378e879ece580256d76e5" in called_file.read_text()
    assert github_path.read_text() == f"{tmp_path / 'gopath'}/bin\n", "golangci-lint's directory must reach PATH"


def test_install_golangci_lint_routes_version_through_env_not_run_splice():
    """Structural guard: the version input must not be spliced directly into run:."""
    step = _install_golangci_lint_step()
    assert "inputs.golangci-lint-version" not in step["run"]
    assert step["env"]["GOLANGCI_LINT_VERSION"] == "${{ inputs.golangci-lint-version }}"
