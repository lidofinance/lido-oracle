"""Reading a scenario network descriptor whose endpoints come from the environment.

Devnet endpoints are internal infrastructure, so a checked-in descriptor names the environment
variable that carries each URL rather than the URL itself. Contract addresses stay inline: they are
public on-chain data, and they pin the exact deployment a cassette was recorded against.

Endpoints resolve lazily, one at a time. Recording and refreshing a cassette needs live URLs;
replaying one does not, and Layer 2 replaying from a checked-in EL archive must keep working with
nothing exported at all. Resolving on first use is what keeps those two paths independent.

A literal URL is also accepted, so a developer can point a descriptor at a local devnet without
exporting anything.
"""

import json
import os
import re
from pathlib import Path
from typing import Any


_PLACEHOLDER = re.compile(r'^\$\{([A-Z0-9_]+)\}$')


def load_network_config(path: str | Path) -> dict[str, Any]:
    """Read a network descriptor. Endpoints are returned unresolved -- see `network_endpoint`."""
    return json.loads(Path(path).read_text(encoding='utf-8'))


def network_endpoint(config: dict[str, Any], name: str) -> str:
    """Resolve one endpoint of a loaded descriptor, raising only if it is actually needed."""
    value = config['endpoints'][name]
    match = _PLACEHOLDER.match(value)
    if not match:
        return value

    variable = match.group(1)
    url = os.getenv(variable)
    if not url:
        raise RuntimeError(
            f'Network "{config.get("network", "?")}" declares its {name} endpoint as '
            f'${{{variable}}}, but that environment variable is unset. Export it with the devnet '
            f'URL, or edit the descriptor to hold a literal URL for a local devnet. Only recording, '
            f'refreshing and scanning need live endpoints; replaying a checked-in cassette does not.'
        )
    return url
