import os
from typing import overload


@overload
def from_file_or_env(env_name: str, default: str) -> str: ...


@overload
def from_file_or_env(env_name: str, default: None = None) -> str | None: ...


def from_file_or_env(env_name: str, default: str | None = None) -> str | None:
    """Return value read from `${env_name}_FILE` or `${env_name}` value directly.

    An empty file means that the value is not set, so the default is returned.
    """

    filepath_env = f"{env_name}_FILE"
    if filepath := os.getenv(filepath_env):
        if not os.path.exists(filepath):
            raise ValueError(f'File {filepath} does not exist. Fix {filepath_env} variable or remove it.')

        with open(filepath) as f:
            return f.read().rstrip() or default

    return os.getenv(env_name, default)
