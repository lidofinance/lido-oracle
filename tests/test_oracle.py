import subprocess
import pytest
from app.oracle import prompt


def test_interactive_oracle_with_no_response():
    with subprocess.Popen(['python3', './app/oracle.py'], bufsize=0,
                          universal_newlines=True, stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        while True:
            if 'Tx data' in proc.stdout.readline():
                break
        expected_output = "Should we sent this TX? [y/n]: "
        assert expected_output in proc.stdout.read(len(expected_output))
        proc.stdin.write('\r\n')
        expected_output = "Please respond with [y or n]: "
        assert expected_output in proc.stdout.read(len(expected_output))
        proc.stdin.write('hz\n')
        assert expected_output in proc.stdout.read(len(expected_output))
        proc.stdin.write('n\n')
        proc.wait()


def test_interactive_oracle_with_yes_response():
    with subprocess.Popen(['python3', './app/oracle.py'], bufsize=0,
                          universal_newlines=True, stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        while True:
            if 'Calling tx locally is succeeded' in proc.stderr.readline():
                break
        while True:
            if 'Tx data' in proc.stdout.readline():
                break
        expected_output = "Should we sent this TX? [y/n]: "
        assert expected_output in proc.stdout.read(len(expected_output))
        proc.stdin.write('\r\n')
        expected_output = "Please respond with [y or n]: "
        assert expected_output in proc.stdout.read(len(expected_output))
        proc.stdin.write('hz\n')
        assert expected_output in proc.stdout.read(len(expected_output))
        proc.stdin.write('y\n')
        assert "Preparing TX" in proc.stderr.read(60)
        proc.kill()
