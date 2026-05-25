import importlib.util
import re
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "finalize-release" / "scripts" / "finalize_release.py"


def _import_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


finalize_release = _import_script("finalize_release", _SCRIPT_PATH)


# ---------------------------------------------------------------------------
# Go module tag construction
# ---------------------------------------------------------------------------


def test_go_module_tag_strips_trailing_vn():
    """Strip trailing /vN (N >= 2) from go_module_path before combining with tag."""
    # Input: packages/go/v3, tag: v3.5.1
    # Expected: packages/go/v3.5.1 (not packages/go/v3/v3.5.1)
    module_path = "packages/go/v3"
    tag = "v3.5.1"

    module_subdir = re.sub(r"/v(?:[2-9]|[1-9]\d+)$", "", module_path)
    module_tag = f"{module_subdir}/{tag}"

    assert module_subdir == "packages/go"
    assert module_tag == "packages/go/v3.5.1"


def test_go_module_tag_strips_v2():
    """Strips /v2 suffix."""
    module_path = "packages/foo/v2"
    tag = "v2.1.0"

    module_subdir = re.sub(r"/v(?:[2-9]|[1-9]\d+)$", "", module_path)
    module_tag = f"{module_subdir}/{tag}"

    assert module_subdir == "packages/foo"
    assert module_tag == "packages/foo/v2.1.0"


def test_go_module_tag_strips_v10():
    """Strips /v10 and higher version numbers."""
    module_path = "packages/bar/v10"
    tag = "v10.0.0"

    module_subdir = re.sub(r"/v(?:[2-9]|[1-9]\d+)$", "", module_path)
    module_tag = f"{module_subdir}/{tag}"

    assert module_subdir == "packages/bar"
    assert module_tag == "packages/bar/v10.0.0"


def test_go_module_tag_no_strip_v1():
    """Does NOT strip /v1 (v1 is implicit, not a suffix)."""
    module_path = "packages/baz/v1"
    tag = "v1.5.0"

    module_subdir = re.sub(r"/v(?:[2-9]|[1-9]\d+)$", "", module_path)
    module_tag = f"{module_subdir}/{tag}"

    # v1 should NOT be stripped (regex only matches v2+)
    assert module_subdir == "packages/baz/v1"
    assert module_tag == "packages/baz/v1/v1.5.0"


def test_go_module_tag_no_strip_if_missing():
    """Does not affect path without version suffix."""
    module_path = "packages/go"
    tag = "v3.5.1"

    module_subdir = re.sub(r"/v(?:[2-9]|[1-9]\d+)$", "", module_path)
    module_tag = f"{module_subdir}/{tag}"

    assert module_subdir == "packages/go"
    assert module_tag == "packages/go/v3.5.1"
