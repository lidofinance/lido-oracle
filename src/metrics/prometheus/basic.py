from prometheus_client import Gauge, Histogram, Counter

from src.variables import PROMETHEUS_PREFIX


BUILD_INFO = Gauge(
    'build_info',
    'Build info',
    ['name'],
    namespace=PROMETHEUS_PREFIX,
)

ACCOUNT_BALANCE = Gauge(
    'account_balance',
    'Account balance',
    ['address'],
    namespace=PROMETHEUS_PREFIX,
)

EXCEPTIONS_COUNT = Counter(
    'exceptions_count',
    'Exceptions count',
    ['module'],
    namespace=PROMETHEUS_PREFIX,
)

ETH1_RPC_REQUESTS_DURATION = Histogram(
    'eth_rpc_requests_duration',
    'Duration of requests to ETH1 RPC',
    namespace=PROMETHEUS_PREFIX,
)

ETH1_RPC_REQUESTS = Counter(
    'eth_rpc_requests',
    'Total count of requests to ETH1 RPC',
    ['method', 'code', 'domain'],
    namespace=PROMETHEUS_PREFIX,
)

ETH2_REQUESTS_DURATION = Histogram(
    'eth2_rpc_requests_duration',
    'Duration of requests to ETH2 API',
    namespace=PROMETHEUS_PREFIX,
)

ETH2_REQUESTS = Counter(
    'eth2_rpc_requests',
    'Total count of requests to ETH2 API',
    ['method', 'code', 'domain'],
    namespace=PROMETHEUS_PREFIX,
)

KEYS_API_REQUESTS_DURATION = Histogram(
    'keys_api_requests_duration',
    'Duration of requests to Keys API',
    namespace=PROMETHEUS_PREFIX,
)

KEYS_API_REQUESTS = Counter(
    'keys_api_requests',
    'Total count of requests to Keys API',
    ['method', 'code', 'domain'],
    namespace=PROMETHEUS_PREFIX,
)

TX_SEND = Counter(
    f'tx_send',
    f'Sent tx count.',
    namespace=PROMETHEUS_PREFIX,
)

TX_FAILURE = Counter(
    'tx_failure',
    'Tx failures.',
    namespace=PROMETHEUS_PREFIX,
)
