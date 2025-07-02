from pathlib import Path

import pytest

from src.utils.env import from_file_or_env


@pytest.mark.unit
class TestFromFileOrEnv:
    @pytest.fixture()
    def file_path(self, tmp_path: Path) -> Path:
        return tmp_path / "file"

    def test_from_env(self, monkeypatch: pytest.MonkeyPatch):
        with monkeypatch.context() as mp:
            env_name = "ENV_NAME"
            expected = "WHATEVER"

            mp.setenv(env_name, expected)
            actual = from_file_or_env(env_name)
            assert actual == expected

    def test_from_file(self, monkeypatch: pytest.MonkeyPatch, file_path: Path):
        with monkeypatch.context() as mp:
            env_name = "ENV_NAME"
            expected = "WHATEVER"

            mp.setenv(f"{env_name}_FILE", str(file_path))
            with file_path.open("w") as f:
                f.write(expected)

            actual = from_file_or_env(env_name)
            assert actual == expected

    def test_file_overrides_env(self, monkeypatch: pytest.MonkeyPatch, file_path: Path):
        with monkeypatch.context() as mp:
            env_name = "ENV_NAME"
            expected = "WHATEVER"

            mp.setenv(f"{env_name}_FILE", str(file_path))
            mp.setenv(env_name, "OVERRIDDEN")
            with file_path.open("w") as f:
                f.write(expected)

            actual = from_file_or_env(env_name)
            assert actual == expected

    def test_file_does_not_exist(self, monkeypatch: pytest.MonkeyPatch):
        with monkeypatch.context() as mp:
            env_name = "ENV_NAME"
            mp.setenv(f"{env_name}_FILE", "NONEXISTENT")
            with pytest.raises(ValueError, match="does not exist"):
                from_file_or_env(env_name)
