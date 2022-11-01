import fcntl
import os
import subprocess
import time
import typing as t

DEFAULT_LOGS_TIMEOUT = 10


def get_log_lines(
    proc: subprocess.Popen,
    n_lines: int = 1,
    timeout: int = DEFAULT_LOGS_TIMEOUT,
    stop_on_substring: t.Optional[str] = None,
) -> t.List[str]:
    lines = []

    start_at = time.time()
    assert proc.stderr is None  # do not use stderr in tests (for now), it messes up output
    stdout_reader = non_block_read(proc.stdout)
    while time.time() < start_at + timeout and len(lines) < n_lines:
        if proc.returncode is not None:
            break
        try:
            line = next(stdout_reader)
        except StopIteration:
            break
        if line:
            lines.append(line)
            if len(lines) >= n_lines:
                break
            if stop_on_substring is not None and stop_on_substring in line:
                break
    return lines


# inspired by https://gist.github.com/sebclaeys/1232088
def non_block_read(output) -> t.Optional[str]:
    """works on Unix only"""
    fd = output.fileno()
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
    while True:
        try:
            data = output.read()
        except TypeError as exc:
            assert "can't concat NoneType to bytes" in str(exc)
            yield None
            continue
        else:
            assert isinstance(data, str)
            for line in data.split('\n'):
                yield line
