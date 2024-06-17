import os
from typing import Final

from eth_account import Account

# - Providers-
EXECUTION_CLIENT_URI: Final = os.getenv('EXECUTION_CLIENT_URI', '').split(',')
CONSENSUS_CLIENT_URI: Final = os.getenv('CONSENSUS_CLIENT_URI', '').split(',')
KEYS_API_URI: Final = os.getenv('KEYS_API_URI', '').split(',')
GW3_ACCESS_KEY: Final = os.getenv('GW3_ACCESS_KEY')
GW3_SECRET_KEY: Final = os.getenv('GW3_SECRET_KEY')
PINATA_JWT: Final = os.getenv('PINATA_JWT')

# - Account -
ACCOUNT = None
MEMBER_PRIV_KEY = os.getenv('MEMBER_PRIV_KEY')

MEMBER_PRIV_KEY_FILE: Final = os.getenv('MEMBER_PRIV_KEY_FILE')
if MEMBER_PRIV_KEY_FILE:
    if not os.path.exists(MEMBER_PRIV_KEY_FILE):
        raise ValueError(f'File {MEMBER_PRIV_KEY_FILE} does not exist. '
                         f'Fix MEMBER_PRIV_KEY_FILE variable or remove it.')

    with open(MEMBER_PRIV_KEY_FILE) as f:
        MEMBER_PRIV_KEY = f.read().rstrip()

if MEMBER_PRIV_KEY:
    ACCOUNT = Account.from_key(MEMBER_PRIV_KEY)  # False-positive. pylint: disable=no-value-for-parameter

# - App specific -
LIDO_LOCATOR_ADDRESS: Final = os.getenv('LIDO_LOCATOR_ADDRESS')
CSM_ORACLE_ADDRESS: Final = os.getenv('CSM_ORACLE_ADDRESS')
CSM_MODULE_ADDRESS: Final = os.getenv('CSM_MODULE_ADDRESS')
FINALIZATION_BATCH_MAX_REQUEST_COUNT: Final = int(os.getenv('FINALIZATION_BATCH_MAX_REQUEST_COUNT', 1000))
CSM_ORACLE_MAX_CONCURRENCY: Final = int(os.getenv('CSM_ORACLE_MAX_CONCURRENCY', 0)) or None

# We add some gas to the transaction to be sure that we have enough gas to execute corner cases
# eg when we tried to submit a few reports in a single block
# In this case the second report will force report finalization and will consume more gas
TX_GAS_ADDITION: Final = int(os.getenv('TX_GAS_ADDITION', 100_000))

# Maximum length of a range for eth_getLogs method calls.
EVENTS_SEARCH_STEP: Final = int(os.getenv('EVENTS_SEARCH_STEP', 10_000))
assert EVENTS_SEARCH_STEP, "EVENTS_SEARCH_STEP must be more than 0"

# Transactions fee calculation variables
MIN_PRIORITY_FEE: Final = int(os.getenv('MIN_PRIORITY_FEE', 50_000_000))
MAX_PRIORITY_FEE: Final = int(os.getenv('MIN_PRIORITY_FEE', 100_000_000_000))
PRIORITY_FEE_PERCENTILE: Final = int(os.getenv('PRIORITY_FEE_PERCENTILE', 3))

DAEMON: Final = os.getenv('DAEMON', 'True').lower() == 'true'
if DAEMON:
    # Default delay for default Oracle members. Member with submit data role should submit data first.
    # If contract is reportable each member in order will submit data with difference with this amount of slots
    SUBMIT_DATA_DELAY_IN_SLOTS = int(os.getenv('SUBMIT_DATA_DELAY_IN_SLOTS', 6))
    CYCLE_SLEEP_IN_SECONDS = int(os.getenv('CYCLE_SLEEP_IN_SECONDS', 12))
    ALLOW_REPORTING_IN_BUNKER_MODE = os.getenv('ALLOW_REPORTING_IN_BUNKER_MODE', 'False').lower() == 'true'
else:
    # Remove all sleep in manual mode
    ALLOW_REPORTING_IN_BUNKER_MODE = True
    SUBMIT_DATA_DELAY_IN_SLOTS = 0
    CYCLE_SLEEP_IN_SECONDS = 0

# HTTP variables
HTTP_REQUEST_TIMEOUT_EXECUTION: Final = int(os.getenv('HTTP_REQUEST_TIMEOUT_EXECUTION', 2 * 60))

HTTP_REQUEST_TIMEOUT_CONSENSUS: Final = int(os.getenv('HTTP_REQUEST_TIMEOUT_CONSENSUS', 5 * 60))
HTTP_REQUEST_RETRY_COUNT_CONSENSUS: Final = int(os.getenv('HTTP_REQUEST_RETRY_COUNT_CONSENSUS', 5))
HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_CONSENSUS: Final = int(
    os.getenv('HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_CONSENSUS', 5)
)

HTTP_REQUEST_TIMEOUT_KEYS_API: Final = int(os.getenv('HTTP_REQUEST_TIMEOUT_KEYS_API', 120))
HTTP_REQUEST_RETRY_COUNT_KEYS_API: Final = int(os.getenv('HTTP_REQUEST_RETRY_COUNT_KEYS_API', 5))
HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_KEYS_API: Final = int(
    os.getenv('HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_KEYS_API', 5)
)

HTTP_REQUEST_TIMEOUT_IPFS: Final = int(os.getenv('HTTP_REQUEST_TIMEOUT_IPFS', 30))
HTTP_REQUEST_RETRY_COUNT_IPFS: Final = int(os.getenv('HTTP_REQUEST_RETRY_COUNT_IPFS', 3))

# - Metrics -
PROMETHEUS_PORT: Final = int(os.getenv('PROMETHEUS_PORT', 9000))
PROMETHEUS_PREFIX: Final = os.getenv("PROMETHEUS_PREFIX", "lido_oracle")

HEALTHCHECK_SERVER_PORT: Final = int(os.getenv('HEALTHCHECK_SERVER_PORT', 9010))

MAX_CYCLE_LIFETIME_IN_SECONDS: Final = int(os.getenv("MAX_CYCLE_LIFETIME_IN_SECONDS", 3000))


def check_all_required_variables():
    errors = check_uri_required_variables()
    if LIDO_LOCATOR_ADDRESS in (None, ''):
        errors.append('LIDO_LOCATOR_ADDRESS')
    return errors


def check_uri_required_variables():
    errors = []
    if '' in EXECUTION_CLIENT_URI:
        errors.append('EXECUTION_CLIENT_URI')
    if '' in CONSENSUS_CLIENT_URI:
        errors.append('CONSENSUS_CLIENT_URI')
    if '' in KEYS_API_URI:
        errors.append('KEYS_API_URI')
    return errors


def raise_from_errors(errors):
    if errors:
        raise ValueError("The following variables are required: " + ", ".join(errors))
