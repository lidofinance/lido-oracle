from enum import Enum

from prometheus_client import Counter, Gauge, Histogram, Info
from prometheus_client.utils import INF

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
    buckets=(.1, .5, 1.0, 2.5, 5.0, 7.5, 10.0, 20.0, 30.0, 60.0, 120.0, 180.0, 240.0, 300.0, 600.0, INF),
)

requests_buckets = (.01, .05, .1, .25, .5, .75, 1.0, 2.5, 5.0, 7.5, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 120.0, INF)

CL_REQUESTS_DURATION = Histogram(
    'cl_requests_duration',
    'Duration of requests to CL API',
    ['endpoint', 'code', 'domain'],
    namespace=PROMETHEUS_PREFIX,
    buckets=requests_buckets,
)

KEYS_API_REQUESTS_DURATION = Histogram(
    'keys_api_requests_duration',
    'Duration of requests to Keys API',
    ['endpoint', 'code', 'domain'],
    namespace=PROMETHEUS_PREFIX,
    buckets=requests_buckets,
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
