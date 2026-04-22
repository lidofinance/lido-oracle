from prometheus_client import Gauge

from src.variables import PROMETHEUS_PREFIX


ACCOUNTING_IS_BUNKER = Gauge(
    "accounting_is_bunker",
    "Is bunker mode enabled",
    namespace=PROMETHEUS_PREFIX,
)

ACCOUNTING_BALANCE_GWEI = Gauge(
    "accounting_balance_gwei",
    "Reported balance gwei",
    ['type'],
    namespace=PROMETHEUS_PREFIX,
)

ACCOUNTING_EXITED_VALIDATORS = Gauge(
    "accounting_exited_validators",
    "Reported exited validators count",
    ["module_id", "no_id"],
    namespace=PROMETHEUS_PREFIX,
)

VAULTS_TOTAL_VALUE = Gauge(
    "accounting_vaults_total_value",
    "Reported cumulated total value of staking vaults",
    namespace=PROMETHEUS_PREFIX,
)
