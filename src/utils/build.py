import json
import os

UNKNOWN_BUILD_INFO = {"version": "unknown", "branch": "unknown", "commit": "unknown"}


def get_build_info() -> dict:
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "./build-info.json")
        with open(path, "r") as f:
            build_info = json.load(f)
        return build_info
    except FileNotFoundError:
        return UNKNOWN_BUILD_INFO
