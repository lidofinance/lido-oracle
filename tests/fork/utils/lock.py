import os
import subprocess
import time
from pathlib import Path


class LockedDir:
    def __init__(self, path):
        self.path = path
        self._lock_file = ".locked"
        self._lock_file_path = Path(self.path) / self._lock_file

    def __enter__(self):
        while os.path.exists(self._lock_file_path):
            time.sleep(1)
        subprocess.run(["mkdir", "-p", self.path], check=True)
        subprocess.run(["touch", self._lock_file_path], check=True)

    def __exit__(self, exc_type, exc_val, exc_tb):
        subprocess.run(["rm", self._lock_file_path], check=True)

    def is_unlocked(self):
        return not os.path.exists(self._lock_file_path)
