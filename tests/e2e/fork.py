import subprocess
import time


class anvil_fork:
    """
    --dump-state
    --load-state

    --state
    """

    def __init__(self, path_to_anvil, fork_url, block_number=None, port='8545'):
        self.path_to_anvil = path_to_anvil
        self.fork_url = fork_url
        self.port = port
        self.block_number = block_number

    def __enter__(self):
        block_command = tuple()
        if self.block_number is not None:
            block_command = ('--fork-block-number', str(self.block_number))

        self.process = subprocess.Popen(
            [
                f'{self.path_to_anvil}anvil',
                '-f',
                self.fork_url,
                '-p',
                self.port,
                *block_command,
                '--block-time',
                '12',
                '--auto-impersonate',
            ],
        )
        # Wait until server is ready
        time.sleep(5)
        return self.process

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.process.terminate()
