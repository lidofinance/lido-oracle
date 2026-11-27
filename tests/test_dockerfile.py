import re
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.unit
class TestBlstSource:
    def test_dockerfile__blst_commit__equals_submodule_commit(self):
        dockerfile = (REPO_ROOT / 'Dockerfile').read_text()
        pinned = re.findall(r'^ADD https://github\.com/supranational/blst\.git#([0-9a-f]{40}) ', dockerfile, re.M)
        try:
            tree = subprocess.run(
                ['git', 'ls-tree', 'HEAD', 'vendor/blst'], cwd=REPO_ROOT, capture_output=True, text=True, check=True
            ).stdout
        except (OSError, subprocess.CalledProcessError):
            pytest.skip('Not a git checkout: the submodule commit is unknown.')

        submodule_commit = tree.split()[2]

        assert pinned == [submodule_commit]
