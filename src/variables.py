import os

from eth_account import Account

# - Providers-
EXECUTION_CLIENT_URI = os.getenv('EXECUTION_CLIENT_URI', '').split(',')
CONSENSUS_CLIENT_URI = os.getenv('CONSENSUS_CLIENT_URI')
KEYS_API_URI = os.getenv('KEYS_API_URI')

# - Account -
ACCOUNT = None
MEMBER_PRIV_KEY = os.getenv('MEMBER_PRIV_KEY')
if MEMBER_PRIV_KEY:
    ACCOUNT = Account.from_key(MEMBER_PRIV_KEY)  # False-positive. pylint: disable=no-value-for-parameter

# - App specific -
LIDO_LOCATOR_ADDRESS = os.getenv('LIDO_LOCATOR_ADDRESS')
GAS_LIMIT = int(os.getenv('GAS_LIMIT', 2_000_000))

# - Metrics -
PROMETHEUS_PORT = int(os.getenv('PROMETHEUS_PORT', 9000))
PROMETHEUS_PREFIX = os.getenv("PROMETHEUS_PREFIX", "lido_oracle")

HEALTHCHECK_SERVER_PORT = int(os.getenv('HEALTHCHECK_SERVER_PORT', 9010))

MAX_CYCLE_LIFETIME_IN_SECONDS = int(os.getenv("MAX_CYCLE_LIFETIME_IN_SECONDS", 3000))
