import json
import os

UNKNOWN_BUILD_INFO = {"version": "unknown", "branch": "unknown", "commit": "unknown"}


def get_build_info() -> dict:
    path = "./build-info.json"
    if os.path.exists(path):
        with open(path, "r") as f:
            try:
                build_info = json.load(f)
            except json.JSONDecodeError:
                return UNKNOWN_BUILD_INFO
        return build_info
    return UNKNOWN_BUILD_INFO
