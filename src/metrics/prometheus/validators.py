from prometheus_client import Gauge

from src.variables import PROMETHEUS_PREFIX


ALL_VALIDATORS = Gauge(
    "all_validators",
    "All validators",
    namespace=PROMETHEUS_PREFIX,
)

LIDO_VALIDATORS = Gauge(
    "lido_validators",
    "Lido validators",
    namespace=PROMETHEUS_PREFIX,
)

ALL_SLASHED_VALIDATORS = Gauge(
    "all_slashed_validators",
    "All slashed validators",
    namespace=PROMETHEUS_PREFIX,
)

LIDO_SLASHED_VALIDATORS = Gauge(
    "lido_slashed_validators",
    "Lido slashed validators",
    namespace=PROMETHEUS_PREFIX,
)
