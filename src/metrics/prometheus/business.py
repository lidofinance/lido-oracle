from prometheus_client import Gauge

from src.variables import PROMETHEUS_PREFIX

DRY_RUN = Gauge(
    "oracle_dry_run",
    "Oracle dry run",
    namespace=PROMETHEUS_PREFIX,
)

ORACLE_MEMBER = Gauge(
    "oracle_member",
    "Account is oracle member",
    namespace=PROMETHEUS_PREFIX,
)

ORACLE_MEMBER_IS_SUBMITTER = Gauge(
    "oracle_member_is_submitter",
    "Member is submitter",
    namespace=PROMETHEUS_PREFIX,
)

ORACLE_MEMBER_IS_FAST_LANE = Gauge(
    "oracle_member_is_fast_lane",
    "Member is fast lane",
    namespace=PROMETHEUS_PREFIX,
)

ORACLE_MEMBER_LAST_REPORT_REF_SLOT = Gauge(
    "oracle_member_last_report_ref_slot",
    "Member last report ref slot",
    namespace=PROMETHEUS_PREFIX,
)

FRAME_CURRENT_REF_SLOT = Gauge(
    "oracle_frame_current_ref_slot",
    "Oracle frame current ref slot",
    namespace=PROMETHEUS_PREFIX,
)

FRAME_DEADLINE_SLOT = Gauge(
    "oracle_frame_deadline_slot",
    "Oracle frame deadline slot",
    namespace=PROMETHEUS_PREFIX,
)

FRAME_LAST_REPORT_REF_SLOT = Gauge(
    "oracle_frame_last_report_ref_slot",
    "Oracle frame last report ref slot",
    namespace=PROMETHEUS_PREFIX,
)

ACCOUNT_BALANCE = Gauge(
    "oracle_account_balance",
    "Oracle account balance",
    namespace=PROMETHEUS_PREFIX,
)

SLOT_NUMBER_INFO = Gauge(
    "oracle_slot_number",
    "Oracle head slot number",
    ["state"],  # "head" or "finalized"
    namespace=PROMETHEUS_PREFIX,
)
