"""Unit tests for publish-r-package action contract."""

from pathlib import Path

import pytest
import yaml


class TestPublishRPackageAction:
    """Test publish-r-package action.yml structure and contract."""

    @pytest.fixture
    def action_yml(self) -> dict:
        """Load the action.yml file."""
        action_path = Path(__file__).parent.parent / "action.yml"
        with action_path.open() as f:
            return yaml.safe_load(f)

    def test_action_has_required_metadata(self, action_yml: dict) -> None:
        """Verify action has name and description."""
        assert "name" in action_yml
        assert action_yml["name"] == "Publish R Package"
        assert "description" in action_yml

    def test_action_has_all_required_inputs(self, action_yml: dict) -> None:
        """Verify action has required inputs."""
        inputs = action_yml.get("inputs", {})
        required_inputs = {"version", "tag", "package-dir"}
        assert required_inputs.issubset(inputs.keys())

    def test_version_input_is_required(self, action_yml: dict) -> None:
        """Verify version input is mandatory."""
        assert action_yml["inputs"]["version"]["required"] is True

    def test_tag_input_is_required(self, action_yml: dict) -> None:
        """Verify tag input is mandatory."""
        assert action_yml["inputs"]["tag"]["required"] is True

    def test_action_has_outputs(self, action_yml: dict) -> None:
        """Verify action defines expected outputs."""
        outputs = action_yml.get("outputs", {})
        assert "artifact-url" in outputs
        assert "archive-path" in outputs

    def test_outputs_have_descriptions(self, action_yml: dict) -> None:
        """Verify outputs have descriptions."""
        outputs = action_yml.get("outputs", {})
        for output_name, output_config in outputs.items():
            assert "description" in output_config, f"Output {output_name} missing description"


class TestCheckRPackageAction:
    """Test check-r-package action.yml structure and contract."""

    @pytest.fixture
    def action_yml(self) -> dict:
        """Load the action.yml file."""
        action_path = Path(__file__).parent.parent.parent / "check-r-package" / "action.yml"
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

    def test_action_uses_composite_runner(self, action_yml: dict) -> None:
        """Verify action uses composite runner with steps."""
        runs = action_yml.get("runs", {})
        assert runs.get("using") == "composite"
        assert "steps" in runs
        assert len(runs["steps"]) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
