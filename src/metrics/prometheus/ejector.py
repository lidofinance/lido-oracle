from prometheus_client import Gauge

from src.variables import PROMETHEUS_PREFIX


EJECTOR_TO_WITHDRAW_WEI_AMOUNT = Gauge(
    "ejector_withdrawal_wei_amount",
    "Withdrawal wei amount",
    namespace=PROMETHEUS_PREFIX,
)

EJECTOR_MAX_EXIT_EPOCH = Gauge(
    "ejector_max_exit_epoch",
    "The max exit epoch",
    namespace=PROMETHEUS_PREFIX,
)

EJECTOR_VALIDATORS_COUNT_TO_EJECT = Gauge(
    "ejector_validators_count_to_eject",
    "Reported validators count to eject",
    namespace=PROMETHEUS_PREFIX,
)
