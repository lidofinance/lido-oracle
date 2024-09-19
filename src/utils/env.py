import os


def from_file_or_env(env_name: str):
    """Return value read from `${env_name}_FILE` or `${env_name}` value directly"""

    filepath_env = f"{env_name}_FILE"
    if filepath := os.getenv(filepath_env):
        if not os.path.exists(filepath):
            raise ValueError(f'File {filepath} does not exist. Fix {filepath_env} variable or remove it.')

        with open(filepath) as f:
            return f.read().rstrip()

    return os.getenv(env_name)
