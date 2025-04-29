import os
from pathlib import Path
from typing import Final

from eth_account import Account

from src.types import OracleModule
from src.utils.env import from_file_or_env

# - Providers-
EXECUTION_CLIENT_URI: Final = os.getenv('EXECUTION_CLIENT_URI', '').split(',')
CONSENSUS_CLIENT_URI: Final = os.getenv('CONSENSUS_CLIENT_URI', '').split(',')
KEYS_API_URI: Final = os.getenv('KEYS_API_URI', '').split(',')

GW3_ACCESS_KEY: Final = from_file_or_env('GW3_ACCESS_KEY')
GW3_SECRET_KEY: Final = from_file_or_env('GW3_SECRET_KEY')
PINATA_JWT: Final = from_file_or_env('PINATA_JWT')
KUBO_HOST: Final = os.getenv('KUBO_HOST')
KUBO_GATEWAY_PORT: Final = int(os.getenv('KUBO_GATEWAY_PORT', 8080))
KUBO_RPC_PORT: Final = int(os.getenv('KUBO_RPC_PORT', 5001))

# - Account -
ACCOUNT = None
MEMBER_PRIV_KEY = from_file_or_env('MEMBER_PRIV_KEY')

if MEMBER_PRIV_KEY:
    ACCOUNT = Account.from_key(MEMBER_PRIV_KEY)  # False-positive. pylint: disable=no-value-for-parameter

# - App specific -
LIDO_LOCATOR_ADDRESS: Final = os.getenv('LIDO_LOCATOR_ADDRESS')
CSM_MODULE_ADDRESS: Final = os.getenv('CSM_MODULE_ADDRESS')
FINALIZATION_BATCH_MAX_REQUEST_COUNT: Final = int(os.getenv('FINALIZATION_BATCH_MAX_REQUEST_COUNT', 1000))
EL_REQUESTS_BATCH_SIZE: Final = int(os.getenv('EL_REQUESTS_BATCH_SIZE', 500))
CSM_ORACLE_MAX_CONCURRENCY: Final = int(os.getenv('CSM_ORACLE_MAX_CONCURRENCY', 2)) or None
CHAIN_ID: Final = int(os.getenv('CHAIN_ID', 1))

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

# - OpsGenie -
OPSGENIE_API_KEY: Final[str] = os.getenv('OPSGENIE_API_KEY', '')
OPSGENIE_API_URL: Final[str] = os.getenv('OPSGENIE_API_URL', '')

HEALTHCHECK_SERVER_PORT: Final = int(os.getenv('HEALTHCHECK_SERVER_PORT', 9010))

MAX_CYCLE_LIFETIME_IN_SECONDS: Final = int(os.getenv("MAX_CYCLE_LIFETIME_IN_SECONDS", 3000))

CACHE_PATH: Final = Path(os.getenv("CACHE_PATH", "."))


def check_all_required_variables(module: OracleModule):
    errors = check_uri_required_variables()
    if not LIDO_LOCATOR_ADDRESS:
        errors.append('LIDO_LOCATOR_ADDRESS')

    if module is OracleModule.CSM and not CSM_MODULE_ADDRESS:
        errors.append('CSM_MODULE_ADDRESS')

    return errors


def check_uri_required_variables():
    required_uris = {
        'EXECUTION_CLIENT_URI': EXECUTION_CLIENT_URI,
        'CONSENSUS_CLIENT_URI': CONSENSUS_CLIENT_URI,
        'KEYS_API_URI': KEYS_API_URI,
    }
    return [name for name, uri in required_uris.items() if '' in uri]


def raise_from_errors(errors):
    if errors:
        raise ValueError("The following variables are required: " + ", ".join(errors))


# All non-private env variables to the logs in main
PUBLIC_ENV_VARS = {
    key: str(value)
    for key, value in {
        'ACCOUNT': 'Dry' if ACCOUNT is None else ACCOUNT.address,
        'LIDO_LOCATOR_ADDRESS': LIDO_LOCATOR_ADDRESS,
        'CSM_MODULE_ADDRESS': CSM_MODULE_ADDRESS,
        'FINALIZATION_BATCH_MAX_REQUEST_COUNT': FINALIZATION_BATCH_MAX_REQUEST_COUNT,
        'EL_REQUESTS_BATCH_SIZE': EL_REQUESTS_BATCH_SIZE,
        'CSM_ORACLE_MAX_CONCURRENCY': CSM_ORACLE_MAX_CONCURRENCY,
        'TX_GAS_ADDITION': TX_GAS_ADDITION,
        'EVENTS_SEARCH_STEP': EVENTS_SEARCH_STEP,
        'MIN_PRIORITY_FEE': MIN_PRIORITY_FEE,
        'MAX_PRIORITY_FEE': MAX_PRIORITY_FEE,
        'PRIORITY_FEE_PERCENTILE': PRIORITY_FEE_PERCENTILE,
        'DAEMON': DAEMON,
        'SUBMIT_DATA_DELAY_IN_SLOTS': SUBMIT_DATA_DELAY_IN_SLOTS,
        'CYCLE_SLEEP_IN_SECONDS': CYCLE_SLEEP_IN_SECONDS,
        'ALLOW_REPORTING_IN_BUNKER_MODE': ALLOW_REPORTING_IN_BUNKER_MODE,
        'HTTP_REQUEST_TIMEOUT_EXECUTION': HTTP_REQUEST_TIMEOUT_EXECUTION,
        'HTTP_REQUEST_TIMEOUT_CONSENSUS': HTTP_REQUEST_TIMEOUT_CONSENSUS,
        'HTTP_REQUEST_RETRY_COUNT_CONSENSUS': HTTP_REQUEST_RETRY_COUNT_CONSENSUS,
        'HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_CONSENSUS': HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_CONSENSUS,
        'HTTP_REQUEST_TIMEOUT_KEYS_API': HTTP_REQUEST_TIMEOUT_KEYS_API,
        'HTTP_REQUEST_RETRY_COUNT_KEYS_API': HTTP_REQUEST_RETRY_COUNT_KEYS_API,
        'HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_KEYS_API': HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_KEYS_API,
        'HTTP_REQUEST_TIMEOUT_IPFS': HTTP_REQUEST_TIMEOUT_IPFS,
        'HTTP_REQUEST_RETRY_COUNT_IPFS': HTTP_REQUEST_RETRY_COUNT_IPFS,
        'PROMETHEUS_PORT': PROMETHEUS_PORT,
        'PROMETHEUS_PREFIX': PROMETHEUS_PREFIX,
        'HEALTHCHECK_SERVER_PORT': HEALTHCHECK_SERVER_PORT,
        'MAX_CYCLE_LIFETIME_IN_SECONDS': MAX_CYCLE_LIFETIME_IN_SECONDS,
        'CACHE_PATH': CACHE_PATH,
    }.items()
}

PRIVATE_ENV_VARS = {
    'EXECUTION_CLIENT_URI': EXECUTION_CLIENT_URI,
    'CONSENSUS_CLIENT_URI': CONSENSUS_CLIENT_URI,
    'KEYS_API_URI': KEYS_API_URI,
    'GW3_ACCESS_KEY': GW3_ACCESS_KEY,
    'GW3_SECRET_KEY': GW3_SECRET_KEY,
    'PINATA_JWT': PINATA_JWT,
    'MEMBER_PRIV_KEY': MEMBER_PRIV_KEY,
    'OPSGENIE_API_KEY': OPSGENIE_API_KEY,
    'OPSGENIE_API_URL': OPSGENIE_API_URL,
}

assert not set(PRIVATE_ENV_VARS.keys()).intersection(set(PUBLIC_ENV_VARS.keys()))
