import os

from eth_account import Account


# Providers
WEB3_PROVIDER_URI = os.getenv('WEB3_PROVIDER_URI', '').split(',')
BEACON_NODE = os.getenv('BEACON_NODE')
KEY_API_URI = os.getenv('KEY_API_URI')

# Contract address
LIDO_CONTRACT_ADDRESS = os.getenv('LIDO_CONTRACT_ADDRESS')
MERKLE_PRICE_ORACLE_CONTRACT = os.getenv('MERKLE_PRICE_ORACLE_CONTRACT', '0x3a6bd15abf19581e411621d669b6a2bbe741ffd6')

# Account
ACCOUNT = None
MEMBER_PRIV_KEY = os.getenv('MEMBER_PRIV_KEY')
if MEMBER_PRIV_KEY:
    ACCOUNT = Account.from_key(MEMBER_PRIV_KEY)

# Other settings
GAS_LIMIT = int(os.getenv('GAS_LIMIT', 2_000_000))

# Metrics, Status
PROMETHEUS_PORT = int(os.getenv('PROMETHEUS_PORT', 9000))
HEALTHCHECK_SERVER_PORT = int(os.getenv('HEALTHCHECK_SERVER_PORT', 9010))

# Mode
DAEMON = os.getenv('DAEMON')
