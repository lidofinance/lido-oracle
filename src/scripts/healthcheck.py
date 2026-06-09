import sys

import requests


def probe(url: str, timeout: float = 2.0) -> int:
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
    if len(sys.argv) != 2:
        print("usage: healthcheck.py <url>", file=sys.stderr)
        sys.exit(2)
    sys.exit(probe(sys.argv[1]))
