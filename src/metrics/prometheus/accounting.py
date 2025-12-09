from prometheus_client import Gauge

from src.variables import PROMETHEUS_PREFIX

ACCOUNTING_IS_BUNKER = Gauge(
    "accounting_is_bunker",
    "Is bunker mode enabled",
    namespace=PROMETHEUS_PREFIX,
)

ACCOUNTING_CL_BALANCE_GWEI = Gauge(
    "accounting_cl_balance_gwei",
    "Reported CL balance in gwei",
    namespace=PROMETHEUS_PREFIX,
)

ACCOUNTING_EL_REWARDS_VAULT_BALANCE_WEI = Gauge(
    "accounting_el_rewards_vault_wei",
    "Reported EL rewards",
    namespace=PROMETHEUS_PREFIX,
)

ACCOUNTING_WITHDRAWAL_VAULT_BALANCE_WEI = Gauge(
    "accounting_withdrawal_vault_balance_wei",
    "Reported withdrawal vault balance",
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
