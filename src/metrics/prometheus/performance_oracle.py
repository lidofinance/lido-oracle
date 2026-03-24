from prometheus_client import Gauge

from src.variables import PROMETHEUS_PREFIX


PERFORMANCE_ORACLE_TARGET_L_EPOCH = Gauge(
    "performance_oracle_target_l_epoch",
    "Left epoch currently required by performance oracle",
    ["consumer"],
    namespace=PROMETHEUS_PREFIX,
)

PERFORMANCE_ORACLE_TARGET_R_EPOCH = Gauge(
    "performance_oracle_target_r_epoch",
    "Right epoch currently required by performance oracle",
    ["consumer"],
    namespace=PROMETHEUS_PREFIX,
)

# XXX: What's reason to have this metric since we can have multiple ranges anyway.
PERFORMANCE_ORACLE_LAST_RANGE_CHECK_UNIXTIME = Gauge(
    "performance_oracle_last_range_check_unixtime",
    "Unix timestamp of the last required-range availability check",
    ["consumer"],
    namespace=PROMETHEUS_PREFIX,
)

PERFORMANCE_ORACLE_WAITING_FOR_DATA = Gauge(
    "performance_oracle_waiting_for_data",
    "1 if oracle is waiting for performance data for required range, else 0",
    ["consumer"],
    namespace=PROMETHEUS_PREFIX,
)
