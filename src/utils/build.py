import json

UNKNOWN_BUILD_INFO = {"version": "unknown", "branch": "unknown", "commit": "unknown"}


def get_build_info() -> dict:
    path = "./build-info.json"
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return UNKNOWN_BUILD_INFO
