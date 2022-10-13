import datetime
import time
import json
import re
import subprocess
import typing as t

# https://semver.org/#is-there-a-suggested-regular-expression-regex-to-check-a-semver-string
# official SemVer regexp (with `v` at the beginning)
regex_str = r"^v(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
regex = re.compile(regex_str, flags=re.MULTILINE)


def shell(cmd: t.List[str]) -> str:
    process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='UTF-8')
    assert process.returncode == 0, f"failed with stdout: {process.stdout}, stderr: {process.stderr}"
    return process.stdout.strip()


def get_semver_tag(tags_raw: str) -> t.Optional[str]:
    """try to get SemVer tag from `tags` with regexp
    :param tags_raw:
    :return:
    """
    groups = list(regex.finditer(tags_raw))
    if len(groups) > 1:
        print('too much semver tags')
        print('groups: %s' % '\n'.join(g[0] for g in groups))
        raise ValueError('Too Much SemVer Tags')
    elif len(groups) == 0:
        return None
    else:
        assert len(groups) == 1
        group = groups[0]
        matched = group.group(0)
        return matched


def get_short_ref_hash(ref: str) -> str:
    """get short git hash by reference"""
    return shell(["git", "rev-parse", "--short", ref])


def get_git_tags(commit: str) -> str:
    """list of git tags, newline separated"""
    return shell(["git", "tag", "--points-at", commit])


def get_top_semver_tag() -> str:
    """get SemVer tag from the nearest commit from the HEAD.
    If the SemVer tag is under the HEAD, adds short git hash to the end.
    """
    deep_index = 0
    commit = f"HEAD~{deep_index}"
    semver_tag = get_semver_tag(get_git_tags(commit))
    while semver_tag is None:
        deep_index += 1
        commit = f"HEAD~{deep_index}"
        semver_tag = get_semver_tag(get_git_tags(commit))
    if deep_index != 0:
        current_commit = get_short_ref_hash("HEAD")
        semver_tag = f'{semver_tag}-{current_commit}'
    return semver_tag


def get_commit_datetime(ref):
    return shell(['git', 'show', '-s', '--format=%ci', ref])


def get_commit_timestamp(ref) -> float:
    return float(shell(['git', 'show', '-s', '--format=%ct', ref]))


def get_branch() -> str:
    return shell(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])


def get_message_first_list(ref) -> str:
    out = shell(['git', 'log', '--oneline', r'--format=%B', '-n', '1', ref])
    lines = out.split('\n')
    return lines[0]


def get_git_tags_list(ref) -> t.List[str]:
    tags_raw = get_git_tags(ref)
    tags = [line.strip() for line in tags_raw.split('\n') if line.strip()]
    return tags


def get_git_info() -> t.Dict:
    tags_list = get_git_tags_list('HEAD')
    commit_timestamp = get_commit_timestamp('HEAD')
    build_timestamp = time.time()
    commit_datetime = datetime.datetime.utcfromtimestamp(commit_timestamp).strftime('%Y-%m-%dT%H:%M:%SZ')
    build_datetime_utc = datetime.datetime.utcfromtimestamp(build_timestamp).strftime('%Y-%m-%dT%H:%M:%SZ')
    return {
        'version': get_top_semver_tag(),
        'commit_datetime': commit_datetime,
        'build_datetime': build_datetime_utc,
        'commit_message': get_message_first_list('HEAD'),
        'commit_hash': get_short_ref_hash('HEAD'),
        'tags': ' '.join(tags_list) if tags_list else '',
        'branch': get_branch(),
    }


if __name__ == '__main__':
    print(json.dumps(get_git_info()))
