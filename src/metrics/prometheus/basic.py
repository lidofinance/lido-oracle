import time
from enum import Enum

from prometheus_client import Counter, Gauge, Histogram, Info
from prometheus_client.utils import INF

from src import variables
from src.variables import PROMETHEUS_PREFIX


class Status(Enum):
    SUCCESS = 'success'
    FAILURE = 'failure'


class CycleResult(Enum):
    SUCCESS = 'success'
    ERROR = 'error'


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
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 7.5, 10.0, 20.0, 30.0, 60.0, 120.0, 180.0, 240.0, 300.0, 600.0, INF),
)

requests_buckets = (
    0.01,
    0.05,
    0.1,
    0.25,
    0.5,
    0.75,
    1.0,
    2.5,
    5.0,
    7.5,
    10.0,
    20.0,
    30.0,
    40.0,
    50.0,
    60.0,
    120.0,
    INF,
)

CL_REQUESTS_DURATION = Histogram(
    'cl_requests_duration',
    'Duration of requests to CL API',
    ['endpoint', 'code', 'domain'],
    namespace=PROMETHEUS_PREFIX,
    buckets=requests_buckets,
)

PERFORMANCE_REQUESTS_DURATION = Histogram(
    'performance_requests_duration',
    'Duration of requests to Performance Collector API',
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

CYCLE_COUNT = Counter(
    'cycle_count',
    'Total count of oracle cycles',
    ['result'],
    namespace=PROMETHEUS_PREFIX,
)

LAST_CYCLE_TIMESTAMP = Gauge(
    'last_cycle_timestamp',
    'Unix timestamp of the last completed oracle cycle',
    ['result'],
    namespace=PROMETHEUS_PREFIX,
)


def init_basic_metrics(w3) -> None:
    """
    Initialize metrics with their current values.

    Ensures Gauge metrics (LAST_CYCLE_TIMESTAMP, ACCOUNT_BALANCE) are populated
    with actual values at startup, making them immediately available for monitoring.
    Counter metrics are initialized with label combinations for consistency.
    """
    for status in Status:
        TRANSACTIONS_COUNT.labels(status=status.value)

    for result in CycleResult:
        CYCLE_COUNT.labels(result=result.value)

    LAST_CYCLE_TIMESTAMP.labels(result=CycleResult.SUCCESS.value).set(time.time())

    if variables.ACCOUNT:
        ACCOUNT_BALANCE.labels(address=variables.ACCOUNT.address).set(w3.eth.get_balance(variables.ACCOUNT.address))
