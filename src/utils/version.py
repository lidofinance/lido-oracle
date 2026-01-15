import os
import tomllib
from functools import lru_cache


@lru_cache(maxsize=1)
def get_oracle_version() -> str:
    try:
        pyproject_path = os.path.join(os.path.dirname(__file__), "..", "..", "pyproject.toml")
        with open(pyproject_path, "rb") as f:
            pyproject_data = tomllib.load(f)
            version = pyproject_data.get("tool", {}).get("poetry", {}).get("version", "unknown")
            return version
    except (FileNotFoundError, tomllib.TOMLDecodeError, KeyError):
        return "unknown"
