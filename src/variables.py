import os

from eth_account import Account

# - Providers-
EXECUTION_CLIENT_URI = os.getenv('EXECUTION_CLIENT_URI', '').split(',')
CONSENSUS_CLIENT_URI = os.getenv('CONSENSUS_CLIENT_URI', '').split(',')
KEYS_API_URI = os.getenv('KEYS_API_URI', '').split(',')

# - Account -
ACCOUNT = None
MEMBER_PRIV_KEY = os.getenv('MEMBER_PRIV_KEY')
if MEMBER_PRIV_KEY:
    ACCOUNT = Account.from_key(MEMBER_PRIV_KEY)  # False-positive. pylint: disable=no-value-for-parameter

# - App specific -
LIDO_LOCATOR_ADDRESS = os.getenv('LIDO_LOCATOR_ADDRESS')
FINALIZATION_BATCH_MAX_REQUEST_COUNT = os.getenv('FINALIZATION_BATCH_MAX_REQUEST_COUNT', 1000)
ALLOW_NEGATIVE_REBASE_REPORTING = os.getenv('ALLOW_NEGATIVE_REBASE_REPORTING', 'False').lower() == 'true'
TX_GAS_MULTIPLIER = float(os.getenv('TX_GAS_MULTIPLIER', 1.25))

# Default delay for default Oracle members. Member with submit data role should submit data first.
# If contract is reportable each member in order will submit data with difference with this amount of slots
SUBMIT_DATA_DELAY_IN_SLOTS = int(os.getenv('SUBMIT_DATA_DELAY_IN_SLOTS', 6))
CYCLE_SLEEP_IN_SECONDS = int(os.getenv('CYCLE_SLEEP_IN_SECONDS', 12))
HTTP_REQUEST_RETRY_COUNT = int(os.getenv('HTTP_REQUEST_RETRY_COUNT', 5))
HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS = int(os.getenv('HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS', 5))
HTTP_REQUEST_TIMEOUT = int(os.getenv('HTTP_REQUEST_TIMEOUT', 5 * 60))

# - Metrics -
PROMETHEUS_PORT = int(os.getenv('PROMETHEUS_PORT', 9000))
PROMETHEUS_PREFIX = os.getenv("PROMETHEUS_PREFIX", "lido_oracle")

HEALTHCHECK_SERVER_PORT = int(os.getenv('HEALTHCHECK_SERVER_PORT', 9010))

MAX_CYCLE_LIFETIME_IN_SECONDS = int(os.getenv("MAX_CYCLE_LIFETIME_IN_SECONDS", 3000))
