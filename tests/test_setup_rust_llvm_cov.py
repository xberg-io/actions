from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_cargo_llvm_cov_installs_through_mise_with_the_latest_release_as_fallback() -> None:
    steps = yaml.safe_load((ROOT / "setup-rust/action.yml").read_text())["runs"]["steps"]
    assert not [step for step in steps if str(step.get("uses", "")).startswith("taiki-e/install-action@")]
    llvm_cov_steps = [step for step in steps if "install-tools.sh" in str(step.get("run", ""))]
    assert len(llvm_cov_steps) == 1
    install = llvm_cov_steps[0]
    assert install["if"] == "inputs.install-llvm-cov == 'true'"
    assert install["run"].endswith('install-tools.sh" . github:taiki-e/cargo-llvm-cov')
    assert install["env"]["INSTALL_TOOLS_UNDECLARED_VERSION"] == "latest"
    setup = next(step for step in steps if step.get("uses") == "xberg-io/actions/setup-mise@v1")
    assert setup["if"] == "inputs.install-llvm-cov == 'true' && steps.mise.outputs.present != 'true'"
    assert steps.index(setup) < steps.index(install)
