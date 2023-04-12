import os

from eth_account import Account

# - Providers-
EXECUTION_CLIENT_URI = os.getenv('EXECUTION_CLIENT_URI', '').split(',')
CONSENSUS_CLIENT_URI = os.getenv('CONSENSUS_CLIENT_URI', '').split(',')
KEYS_API_URI = os.getenv('KEYS_API_URI', '').split(',')

# - Account -
ACCOUNT = None
MEMBER_PRIV_KEY = os.getenv('MEMBER_PRIV_KEY')

MEMBER_PRIV_KEY_FILE = os.getenv('MEMBER_PRIV_KEY_FILE')
if MEMBER_PRIV_KEY_FILE:
    if not os.path.exists(MEMBER_PRIV_KEY_FILE):
        raise ValueError(f'File {MEMBER_PRIV_KEY_FILE} does not exist. '
                         f'Fix MEMBER_PRIV_KEY_FILE variable or remove it.')

    with open(MEMBER_PRIV_KEY_FILE) as f:
        MEMBER_PRIV_KEY = f.read().rstrip()

if MEMBER_PRIV_KEY:
    ACCOUNT = Account.from_key(MEMBER_PRIV_KEY)  # False-positive. pylint: disable=no-value-for-parameter

# - App specific -
LIDO_LOCATOR_ADDRESS = os.getenv('LIDO_LOCATOR_ADDRESS')
FINALIZATION_BATCH_MAX_REQUEST_COUNT = os.getenv('FINALIZATION_BATCH_MAX_REQUEST_COUNT', 1000)
ALLOW_REPORTING_IN_BUNKER_MODE = os.getenv('ALLOW_REPORTING_IN_BUNKER_MODE', 'False').lower() == 'true'
# We add some gas to the transaction to be sure that we have enough gas to execute corner cases
# eg when we tried to submit a few reports in a single block
# In this case the second report will force report finalization and will consume more gas
TX_GAS_ADDITION = int(os.getenv('TX_GAS_ADDITION', 100_000))

# Transactions fee calculation variables
MIN_PRIORITY_FEE = int(os.getenv('MIN_PRIORITY_FEE', 50_000_000))
MAX_PRIORITY_FEE = int(os.getenv('MIN_PRIORITY_FEE', 100_000_000_000))
PRIORITY_FEE_PERCENTILE = int(os.getenv('PRIORITY_FEE_PERCENTILE', 3))

# Default delay for default Oracle members. Member with submit data role should submit data first.
# If contract is reportable each member in order will submit data with difference with this amount of slots
SUBMIT_DATA_DELAY_IN_SLOTS = int(os.getenv('SUBMIT_DATA_DELAY_IN_SLOTS', 6))
CYCLE_SLEEP_IN_SECONDS = int(os.getenv('CYCLE_SLEEP_IN_SECONDS', 12))

HTTP_REQUEST_TIMEOUT_CONSENSUS = int(os.getenv('HTTP_REQUEST_TIMEOUT_CONSENSUS', 5 * 60))
HTTP_REQUEST_RETRY_COUNT_CONSENSUS = int(os.getenv('HTTP_REQUEST_RETRY_COUNT_CONSENSUS', 5))
HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_CONSENSUS = int(
    os.getenv('HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_CONSENSUS', 5)
)


HTTP_REQUEST_TIMEOUT_KEYS_API = int(os.getenv('HTTP_REQUEST_TIMEOUT_KEYS_API', 5 * 60))
HTTP_REQUEST_RETRY_COUNT_KEYS_API = int(os.getenv('HTTP_REQUEST_RETRY_COUNT_KEYS_API', 5))
HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_KEYS_API = int(
    os.getenv('HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_KEYS_API', 5)
)

# - Metrics -
PROMETHEUS_PORT = int(os.getenv('PROMETHEUS_PORT', 9000))
PROMETHEUS_PREFIX = os.getenv("PROMETHEUS_PREFIX", "lido_oracle")

HEALTHCHECK_SERVER_PORT = int(os.getenv('HEALTHCHECK_SERVER_PORT', 9010))

MAX_CYCLE_LIFETIME_IN_SECONDS = int(os.getenv("MAX_CYCLE_LIFETIME_IN_SECONDS", 3000))


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
