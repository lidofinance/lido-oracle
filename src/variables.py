import os

from eth_account import Account


# Web3 settings
WEB3_PROVIDER_URIS = os.getenv('WEB3_PROVIDER_URIS', '').split(',')
BEACON_NODE = os.getenv('BEACON_NODE')

LIDO_CONTRACT_ADDRESS = os.getenv('LIDO_CONTRACT_ADDRESS')
GAS_LIMIT = int(os.getenv('GAS_LIMIT', 1_500_000))

ACCOUNT = None
MEMBER_PRIV_KEY = os.getenv('MEMBER_PRIV_KEY')
if MEMBER_PRIV_KEY:
    ACCOUNT = Account.from_key(MEMBER_PRIV_KEY)

# Metrics, Status
PROMETHEUS_PORT = int(os.getenv('PROMETHEUS_PORT', 9000))
HEALTHCHECK_SERVER_PORT = int(os.getenv('HEALTHCHECK_SERVER_PORT', 9010))

# Mode
DAEMON = os.getenv('DAEMON')
