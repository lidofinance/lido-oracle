import subprocess
import time


class anvil_fork:
    """
    --dump-state
    --load-state

    --state
    """
    def __init__(self, path_to_anvil, fork_url, block_number, port='8545'):
        self.path_to_anvil = path_to_anvil
        self.fork_url = fork_url
        self.port = str(port)
        self.block_number = str(block_number)

    def __enter__(self):
        self.process = subprocess.Popen(
            [
                f'{self.path_to_anvil}anvil',
                '-f', self.fork_url,
                '-p', self.port,
                '--fork-block-number', self.block_number,
                '--auto-impersonate',
            ],
        )
        # Wait until server is ready
        time.sleep(1)
        return self.process

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.process.terminate()
