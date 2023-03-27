from enum import Enum

from prometheus_client import Gauge, Histogram, Counter, Info

from src.variables import PROMETHEUS_PREFIX


class Status(Enum):
    SUCCESS = 'success'
    FAILURE = 'failure'


BUILD_INFO = Info(
    'build',
    'Build info',
    namespace=PROMETHEUS_PREFIX,
)

ENV_VARIABLES_INFO = Info(
    'env_variables',
    'Env variables for the app',
    namespace=PROMETHEUS_PREFIX,
)

GENESIS_TIME = Gauge(
    'genesis_time',
    'Genesis time',
    namespace=PROMETHEUS_PREFIX,
)

ACCOUNT_BALANCE = Gauge(
    'account_balance',
    'Account balance',
    ['address'],
    namespace=PROMETHEUS_PREFIX,
)

ORACLE_SLOT_NUMBER = Gauge(
    "slot_number",
    "Oracle head or finalized slot number",
    ["state"],  # "head" or "finalized"
    namespace=PROMETHEUS_PREFIX,
)

ORACLE_BLOCK_NUMBER = Gauge(
    "block_number",
    "Oracle head or finalized block number",
    ["state"],  # "head" or "finalized"
    namespace=PROMETHEUS_PREFIX,
)

FUNCTIONS_DURATION = Histogram(
    'functions_duration',
    'Duration of oracle daemon tasks',
    ['name', 'status'],
    namespace=PROMETHEUS_PREFIX,
)

EL_REQUESTS_DURATION = Histogram(
    'el_requests_duration',
    'Duration of requests to EL RPC',
    ['endpoint', 'call_method', 'call_to', 'code', 'domain'],
    namespace=PROMETHEUS_PREFIX,
)

CL_REQUESTS_DURATION = Histogram(
    'cl_requests_duration',
    'Duration of requests to CL API',
    ['endpoint', 'code', 'domain'],
    namespace=PROMETHEUS_PREFIX,
)

KEYS_API_REQUESTS_DURATION = Histogram(
    'keys_api_requests_duration',
    'Duration of requests to Keys API',
    ['endpoint', 'code', 'domain'],
    namespace=PROMETHEUS_PREFIX,
)

KEYS_API_LATEST_BLOCKNUMBER = Gauge(
    'keys_api_latest_blocknumber',
    'Latest blocknumber from Keys API metadata',
    namespace=PROMETHEUS_PREFIX,
)

TRANSACTIONS_COUNT = Counter(
    'transactions_count',
    'Total count of transactions. Success or failure',
    ['status'],
    namespace=PROMETHEUS_PREFIX,
)
