import os

from prometheus_client import Gauge, Counter

PREFIX = os.getenv('PROMETHEUS_PREFIX', 'lido_oracle')

MODULE_PREFIX = 'accounting_'
MODULE_NAME = '[Accounting] '

ACCOUNTING_NEXT_REPORTABLE_EPOCH = Gauge(
    f'{MODULE_PREFIX}next_reportable_epoch',
    f'{MODULE_NAME}Last reportable epoch',
    namespace=PREFIX,
)

ACCOUNTING_ACTIVE_VALIDATORS = Gauge(
    f'{MODULE_PREFIX}total_validators_count',
    f'{MODULE_NAME}Total validators count.',
    namespace=PREFIX,
)
ACCOUNTING_EXITED_VALIDATORS = Gauge(
    f'{MODULE_PREFIX}exited_validators_count',
    f'{MODULE_NAME}Exited validatos count.',
    namespace=PREFIX,
)
ACCOUNTING_VALIDATORS_BALANCE = Gauge(
    f'{MODULE_PREFIX}total_validators_balance',
    f'{MODULE_NAME}Total validators balance.',
    namespace=PREFIX,
)

WEI_TO_RESERVE = Gauge(
    f'{MODULE_PREFIX}reserved_buffered_ether',
    f'{MODULE_NAME}Reserved buffered ether.',
    namespace=PREFIX,
)

WC_BALANCE = Gauge(
    f'{MODULE_PREFIX}total_wc_balance',
    f'{MODULE_NAME}Total Withdrawal Credential balance.',
    namespace=PREFIX,
)

LAST_FINALIZED_WITHDRAWAL_REQUEST = Gauge(
    f'{MODULE_PREFIX}last_finalized_withdrawal_request',
    f'{MODULE_NAME}Last finalized withdrawal request.',
    namespace=PREFIX,
)
