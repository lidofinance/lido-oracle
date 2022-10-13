import pytest

from helpers.get_git_info import get_semver_tag


def test_empty():
    result = get_semver_tag('')
    assert result is None


def test_nothing():
    result = get_semver_tag(
        """aaa
some-tag
blabla
0xy789roirjnq
1-2-3
"""
    )
    assert result is None


def test_incorrect1():
    result = get_semver_tag('v0.1.2release')
    assert result is None


def test_incorrect2():
    result = get_semver_tag('0.1.2release')
    assert result is None


def test_incorrect3():
    result = get_semver_tag('0.1.2-release')
    assert result is None


def test_incorrect4():
    result = get_semver_tag('v0.1')
    assert result is None


def test_incorrect5():
    result = get_semver_tag('v0.1-release')
    assert result is None


def test_incorrect6():
    result = get_semver_tag('v0.1.2.3')
    assert result is None


def test_correct1():
    result = get_semver_tag("""v0.1.2""")
    assert result == 'v0.1.2'


def test_correct2():
    result = get_semver_tag("""v0.1.2-release""")
    assert result == 'v0.1.2-release'


def test_one_semver_and_others():
    result = get_semver_tag(
        """aaa
some-tag
v0.1.2-release
0xy789roirjnq
1-2-3
"""
    )
    assert result == 'v0.1.2-release'


def test_several_semver_tags():
    with pytest.raises(ValueError):
        get_semver_tag(
            """aaa
some-tag
v0.1.2-release
0xy789roirjnq
1-2-3
v0.1.3
"""
        )
