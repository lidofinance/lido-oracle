from prometheus_client import Gauge

from src.variables import PROMETHEUS_PREFIX


EJECTOR_TO_WITHDRAW_WEI_AMOUNT = Gauge(
    "ejector_withdrawal_wei_amount",
    "Withdrawal wei amount",
    namespace=PROMETHEUS_PREFIX,
)

EJECTOR_MAX_WITHDRAWAL_EPOCH = Gauge(
    "ejector_max_withdrawal_epoch",
    "The max exit epoch",
    namespace=PROMETHEUS_PREFIX,
)

EJECTOR_VALIDATORS_COUNT_TO_EJECT = Gauge(
    "ejector_validators_count_to_eject",
    "Validators with a withdrawal request (full or partial) in the report",
    namespace=PROMETHEUS_PREFIX,
)

EJECTOR_WITHDRAWAL_REQUESTS = Gauge(
    "ejector_withdrawal_requests",
    "Withdrawal requests in the report by type",
    ["type"],
    namespace=PROMETHEUS_PREFIX,
)

EJECTOR_PARTIAL_WITHDRAWAL_GWEI_AMOUNT = Gauge(
    "ejector_partial_withdrawal_gwei_amount",
    "Total amount of the partial withdrawal requests in the report",
    namespace=PROMETHEUS_PREFIX,
)
