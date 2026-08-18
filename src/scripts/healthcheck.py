import sys

import requests


# Above any container-level healthcheck timeout (Dockerfile: 3s, compose: 10s),
# so the Docker/compose `timeout` setting decides when the probe fails.
DEFAULT_TIMEOUT = 30.0


def probe(url: str, timeout: float = DEFAULT_TIMEOUT) -> int:
    try:
        response = requests.get(url, timeout=timeout, allow_redirects=False)
    except requests.RequestException as error:
        print(f"Healthcheck failed: {error}", file=sys.stderr)
        return 1
    if not 200 <= response.status_code < 300:
        print(f"Healthcheck failed: unexpected status {response.status_code}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        print("usage: healthcheck.py <url> [timeout]", file=sys.stderr)
        sys.exit(2)
    try:
        timeout = float(sys.argv[2]) if len(sys.argv) == 3 else DEFAULT_TIMEOUT
    except ValueError:
        print(f"invalid timeout: {sys.argv[2]}", file=sys.stderr)
        sys.exit(2)
    sys.exit(probe(sys.argv[1], timeout))
