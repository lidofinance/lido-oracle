import json
import os
import subprocess
import time

TIMEOUT = 10


def test_show_version_with_correct_file():
    env = os.environ.copy()
    env['VERSION_JSON_PATH'] = '/tmp/test-version.json'
    start_at = time.time()
    with open(env['VERSION_JSON_PATH'], 'w') as fout:
        sample_version = {
            "version": "v0.1.0-rc.1-3295e13",
            "commit_datetime": "2020-12-08T07:50:13Z",
            "build_datetime": "2020-12-08T08:45:14.623010Z",
            "commit_message": "write version.json #55",
            "commit_hash": "3295e13",
            "tags": "some tags",
            "branch": "issue-55-write-version-to-docker-and-file",
        }
        json.dump(sample_version, fout)
    with subprocess.Popen(
            ['python3', './app/oracle.py'],
            bufsize=0,
            universal_newlines=True,
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
    ) as proc:
        n_lines = 7
        lines = []
        while time.time() < start_at + TIMEOUT and len(lines) < n_lines:
            line = proc.stdout.readline()
            line = line.strip()
            if line:
                lines.append(line)

        assert lines[0].endswith(f'version: {sample_version["version"]}')
        assert lines[1].endswith(f'commit_message: {sample_version["commit_message"]}')
        assert lines[2].endswith(f'commit_hash: {sample_version["commit_hash"]}')
        assert lines[3].endswith(f'commit_datetime: {sample_version["commit_datetime"]}')
        assert lines[4].endswith(f'build_datetime: {sample_version["build_datetime"]}')
        assert lines[5].endswith(f'tags: {sample_version["tags"]}')
        assert lines[6].endswith(f'branch: {sample_version["branch"]}')
        assert all(line.startswith('INFO') for line in lines)


def test_show_version_with_incorrect_file():
    env = os.environ.copy()
    env['VERSION_JSON_PATH'] = '/some/path/which/does/not/exist'
    start_at = time.time()
    with subprocess.Popen(
            ['python3', './app/oracle.py'],
            bufsize=0,
            universal_newlines=True,
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
    ) as proc:
        n_lines = 1
        lines = []
        while time.time() < start_at + TIMEOUT and len(lines) < n_lines:
            line = proc.stdout.readline()
            line = line.strip()
            if line:
                lines.append(line)

        assert lines[0].endswith(f'version json file does not exist')
        assert all(line.startswith('INFO') for line in lines)
