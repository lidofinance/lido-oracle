import pytest
import os
import tomllib

from src.utils.version import get_oracle_version


@pytest.mark.unit
class TestVersion:

    def test_get_oracle_version__returns_valid_version(self):
        version = get_oracle_version()

        assert version != "unknown"
        assert len(version) > 0
        assert version[0].isdigit()
        # Should contain dots (semantic versioning)
        assert "." in version
        # Should have at least major.minor format
        version_parts = version.split(".")
        assert len(version_parts) >= 2
        # Major and minor should be numeric
        assert version_parts[0].isdigit()
        assert version_parts[1].isdigit()

    def test_get_oracle_version__matches_pyproject_toml(self):
        pyproject_path = os.path.join(os.path.dirname(__file__), "..", "..", "pyproject.toml")
        with open(pyproject_path, "rb") as f:
            pyproject_data = tomllib.load(f)
            expected_version = pyproject_data.get("tool", {}).get("poetry", {}).get("version")

        actual_version = get_oracle_version()

        assert actual_version == expected_version
