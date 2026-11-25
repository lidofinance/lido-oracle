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

    def test_from_file_or_env__trailing_newline_in_file__returns_stripped_value(
        self, monkeypatch: pytest.MonkeyPatch, file_path: Path
    ):
        monkeypatch.setenv("ENV_NAME_FILE", str(file_path))
        file_path.write_text("WHATEVER\r\n")

        actual = from_file_or_env("ENV_NAME")

        assert actual == "WHATEVER"

    def test_from_file_or_env__empty_file__returns_none(self, monkeypatch: pytest.MonkeyPatch, file_path: Path):
        monkeypatch.setenv("ENV_NAME_FILE", str(file_path))
        monkeypatch.setenv("ENV_NAME", "FROM_ENV")
        file_path.write_text("\n")

        actual = from_file_or_env("ENV_NAME")

        assert actual is None

    def test_from_file_or_env__empty_file_with_default__returns_default(
        self, monkeypatch: pytest.MonkeyPatch, file_path: Path
    ):
        monkeypatch.setenv("ENV_NAME_FILE", str(file_path))
        file_path.write_text("")

        actual = from_file_or_env("ENV_NAME", "DEFAULT")

        assert actual == "DEFAULT"

    def test_from_file_or_env__nothing_set_with_default__returns_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("ENV_NAME", raising=False)
        monkeypatch.delenv("ENV_NAME_FILE", raising=False)

        actual = from_file_or_env("ENV_NAME", "DEFAULT")

        assert actual == "DEFAULT"

    def test_from_file_or_env__empty_file_variable__reads_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ENV_NAME_FILE", "")
        monkeypatch.setenv("ENV_NAME", "FROM_ENV")

        actual = from_file_or_env("ENV_NAME", "DEFAULT")

        assert actual == "FROM_ENV"
