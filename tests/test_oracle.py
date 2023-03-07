import os
import subprocess

env = os.environ.copy()
env['CONSIDER_WITHDRAWALS_FROM_EPOCH'] = '32'


def test_interactive_oracle_with_no_response():
    with subprocess.Popen(
        ['python3', './app/oracle.py'],
        bufsize=0,
        universal_newlines=True,
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    ) as proc:
        while True:
            if 'Tx data' in proc.stdout.readline():
                break
        expected_output = "Should we send this TX? [y/n]: "
        assert expected_output in proc.stdout.read(len(expected_output))
        proc.stdin.write('\r\n')
        expected_output = "Please respond with [y or n]: "
        assert expected_output in proc.stdout.read(len(expected_output))
        proc.stdin.write('hz\n')
        assert expected_output in proc.stdout.read(len(expected_output))
        proc.stdin.write('n\n')
        proc.wait()


def test_interactive_oracle_with_yes_response():
    with subprocess.Popen(
        ['python3', './app/oracle.py'],
        bufsize=0,
        universal_newlines=True,
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    ) as proc:
        while True:
            if 'Calling tx locally succeeded' in proc.stdout.readline():
                break
        while True:
            if 'Tx data' in proc.stdout.readline():
                break
        expected_output = "Should we send this TX? [y/n]: "
        assert expected_output in proc.stdout.read(len(expected_output))
        proc.stdin.write('\r\n')
        expected_output = "Please respond with [y or n]: "
        assert expected_output in proc.stdout.read(len(expected_output))
        proc.stdin.write('hz\n')
        assert expected_output in proc.stdout.read(len(expected_output))
        proc.stdin.write('y\n')
        assert "Preparing TX" in proc.stdout.read(60)
        proc.kill()
