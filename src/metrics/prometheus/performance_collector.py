from prometheus_client import Counter, Gauge

from src.variables import PROMETHEUS_PREFIX


PERFORMANCE_COLLECTOR_DB_MIN_EPOCH = Gauge(
    "performance_collector_db_min_epoch",
    "Minimum epoch stored in performance DB",
    namespace=PROMETHEUS_PREFIX,
)

PERFORMANCE_COLLECTOR_DB_MAX_EPOCH = Gauge(
    "performance_collector_db_max_epoch",
    "Maximum epoch stored in performance DB",
    namespace=PROMETHEUS_PREFIX,
)

PERFORMANCE_COLLECTOR_DB_EPOCHS_COUNT = Gauge(
    "performance_collector_db_epochs_count",
    "Count of stored epochs in performance DB (duties rows)",
    namespace=PROMETHEUS_PREFIX,
)

PERFORMANCE_COLLECTOR_DB_DEMAND_COUNT = Gauge(
    "performance_collector_db_demand_count",
    "Count of active epoch demands in performance DB",
    namespace=PROMETHEUS_PREFIX,
)

PERFORMANCE_COLLECTOR_ERRORS_TOTAL = Counter(
    "performance_collector_errors_total",
    "Total number of collector errors by type",
    ["type"],
    namespace=PROMETHEUS_PREFIX,
)
