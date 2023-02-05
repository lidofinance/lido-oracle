import os

from prometheus_client import Gauge, Histogram, Counter


PREFIX = os.getenv('PROMETHEUS_PREFIX', 'lido_oracle')


# TODO
BUILD_INFO = Gauge(
    'build_info',
    'Build info',
    ['name'],
    namespace=PREFIX,
)

# TODO
ACCOUNT_BALANCE = Gauge(
    'account_balance',
    'Account balance',
    ['address'],
    namespace=PREFIX,
)

EXCEPTIONS_COUNT = Counter(
    'exceptions_count',
    'Exceptions count',
    ['module'],
    namespace=PREFIX,
)

ETH1_RPC_REQUESTS_DURATION = Histogram(
    'eth_rpc_requests_duration',
    'Duration of requests to ETH1 RPC',
    namespace=PREFIX,
)

ETH1_RPC_REQUESTS = Counter(
    'eth_rpc_requests',
    'Total count of requests to ETH1 RPC',
    ['method', 'code', 'domain'],
    namespace=PREFIX,
)

ETH2_REQUESTS_DURATION = Histogram(
    'eth2_rpc_requests_duration',
    'Duration of requests to ETH2 API',
    namespace=PREFIX,
)

ETH2_REQUESTS = Counter(
    'eth2_rpc_requests',
    'Total count of requests to ETH2 API',
    ['method', 'code', 'domain'],
    namespace=PREFIX,
)

KEYS_API_REQUESTS_DURATION = Histogram(
    'keys_api_requests_duration',
    'Duration of requests to Keys API',
    namespace=PREFIX,
)

KEYS_API_REQUESTS = Counter(
    'keys_api_requests',
    'Total count of requests to Keys API',
    ['method', 'code', 'domain'],
    namespace=PREFIX,
)

TX_SEND = Counter(
    f'tx_send',
    f'Sent tx count.',
    namespace=PREFIX,
)

TX_FAILURE = Counter(
    'tx_failure',
    'Tx failures.',
    namespace=PREFIX,
)
