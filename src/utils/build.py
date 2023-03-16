import json

UNKNOWN_BUILD_INFO = {"version": "unknown", "branch": "unknown", "commit": "unknown"}


def get_build_info() -> dict:
    try:
        with open("../../build-info.json", "r") as f:
            build_info = json.load(f)
        return build_info
    except FileNotFoundError:
        return UNKNOWN_BUILD_INFO
