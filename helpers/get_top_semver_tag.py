import subprocess
import typing as t
import sys
import re

# input_str = ''.join(sys.stdin)

regex_str=r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
regex = re.compile(regex_str)

class TooMuchSemVerTags(Exception):
    pass


def get_semver_tag(input_str: str) -> t.Optional[str]:
    groups = list(regex.finditer(input_str, re.MULTILINE))
    if len(groups) > 1:
        print('too much semver tags')
        print('groups: %s' % '\n'.join(g[0] for g in groups))
        raise TooMuchSemVerTags()
    elif len(groups) == 0:
        return None
    else:
        assert len(groups) == 1
        group = groups[0]
        # print(group)
        matched = group.group(0)
        # groupdict = group.groupdict()
        # found = ".".join([groupdict['major'], groupdict['minor'], groupdict['patch']])
        # print(groupdict)
        # print(found)
        return matched


def get_deep_hash(ref: str) -> str:
    process = subprocess.run(["git", "rev-parse", "--short", ref], capture_output=True)
    assert process.returncode == 0, f"failed with stdout: {process.stdout.decode('utf-8')}, stderr: {process.stderr.decode('utf-8')}"
    return process.stdout.decode('utf-8').strip()


def get_git_tags(commit: str) -> str:
    process = subprocess.run(["git", "tag", "--points-at", commit], capture_output=True)
    assert process.returncode == 0, f"failed with stdout: {process.stdout.decode('utf-8')}, stderr: {process.stderr.decode('utf-8')}"
    return process.stdout.decode('utf-8')


def get_top_semver_tag() -> str:
    deep_index = 0
    commit = f"HEAD~{deep_index}"
    semver_tag = get_semver_tag(get_git_tags(commit))
    while semver_tag is None:
        deep_index += 1
        commit = f"HEAD~{deep_index}"
        semver_tag = get_semver_tag(get_git_tags(commit))
    if deep_index != 0:
        semver_tag = f'{semver_tag}-{get_deep_hash(commit)}'
    return semver_tag


if __name__ == '__main__':
    print(get_top_semver_tag())
