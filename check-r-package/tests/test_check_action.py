"""Unit tests for check-r-package action contract."""

from pathlib import Path

import pytest
import yaml


class TestCheckRPackageAction:
    """Test check-r-package action.yml structure and contract."""

    @pytest.fixture
    def action_yml(self) -> dict:
        """Load the action.yml file."""
        action_path = Path(__file__).parent.parent / "action.yml"
        with action_path.open() as f:
            return yaml.safe_load(f)

    def test_action_has_required_metadata(self, action_yml: dict) -> None:
        """Verify action has name and description."""
        assert "name" in action_yml
        assert action_yml["name"] == "Check R Package"
        assert "description" in action_yml

    def test_action_has_inputs(self, action_yml: dict) -> None:
        """Verify action has inputs."""
        inputs = action_yml.get("inputs", {})
        assert "package-dir" in inputs
        assert "r-version" in inputs

    def test_package_dir_has_default(self, action_yml: dict) -> None:
        """Verify package-dir input has sensible default."""
        assert "default" in action_yml["inputs"]["package-dir"]
        assert action_yml["inputs"]["package-dir"]["default"] == "packages/r"

    def test_r_version_has_default(self, action_yml: dict) -> None:
        """Verify r-version input has default."""
        assert "default" in action_yml["inputs"]["r-version"]
        assert action_yml["inputs"]["r-version"]["default"] == "4.4"

    def test_action_uses_composite_runner(self, action_yml: dict) -> None:
        """Verify action uses composite runner with steps."""
        runs = action_yml.get("runs", {})
        assert runs.get("using") == "composite"
        assert "steps" in runs
        assert len(runs["steps"]) > 0

    def test_has_r_cmd_check_step(self, action_yml: dict) -> None:
        """Verify action includes R CMD check step."""
        runs = action_yml.get("runs", {})
        step_names = [step.get("name", "").lower() for step in runs.get("steps", [])]
        assert any("check" in name for name in step_names), "No R CMD check step found"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
