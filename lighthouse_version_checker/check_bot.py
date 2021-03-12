"""
Checks latest
"""

import typing as t
import logging
import os
import time

import requests

logger = logging.getLogger('lighthouse_version_checker')

SLEEP = int(os.environ.get('SLEEP', 60))
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
LIGHTHOUSE_RELEASES = os.environ.get('LIGHTHOUSE_RELEASES', 'https://api.github.com/repos/sigp/lighthouse/releases')
ORACLE_ISSUES = os.environ.get('ORACLE_ISSUES', 'https://api.github.com/repos/lidofinance/lido-oracle/issues')
LAST_RELEASE_FILE = os.environ.get('LAST_RELEASE_FILE', '/volume/lighthouse_release.txt')
GITHUB_USERNAME = os.environ['GITHUB_USERNAME']
GITHUB_TOKEN = os.environ['GITHUB_TOKEN']


def get_stored_last_version() -> t.Optional[str]:
    if not os.path.exists(LAST_RELEASE_FILE):
        return None
    with open(LAST_RELEASE_FILE) as f:
        return f.read().strip()


def write_stored_last_version(version: str):
    with open(LAST_RELEASE_FILE, 'w') as f:
        return f.write(version + '\n')


def get_github_last_version() -> str:
    response = requests.get(LIGHTHOUSE_RELEASES, headers={'Accept': 'application/vnd.github.v3+json'})
    assert response.status_code == 200
    return response.json()[0]['tag_name']


def create_issue(version: str):
    response = requests.post(
        ORACLE_ISSUES,
        headers={'Accept': 'application/vnd.github.v3+json'},
        json={
            "title": f"New LightHouse release {version}",
            "body": "Please check that it does not break the oracle.",
        },
        auth=(GITHUB_USERNAME, GITHUB_TOKEN),
    )
    assert response.status_code == 201, f'{response.status_code=} {response.content=}'


def check_once():
    stored_version = get_stored_last_version()
    logger.debug(f'{stored_version=}')
    github_version = get_github_last_version()
    logger.debug(f'{github_version=}')
    if github_version != stored_version:
        logger.info(f'NEW VERSION {github_version=} {stored_version=}')
        if stored_version is None:  # probably the first run
            logger.info(f'stored version does not exist, do not create the issue')
        else:
            logger.info(f'create the issue')
            create_issue(github_version)
        write_stored_last_version(github_version)


def main():
    logging.basicConfig(format='%(levelname)8s %(asctime)s <daemon> %(message)s', level=LOG_LEVEL)
    while True:
        try:
            logger.debug(f'check_once')
            check_once()
        except Exception as exc:
            logger.exception(f'unhandled exception {type(exc)}')
        finally:
            time.sleep(SLEEP)


if __name__ == '__main__':
    main()
