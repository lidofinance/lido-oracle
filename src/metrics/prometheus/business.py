from prometheus_client import Gauge, Info

from src.variables import PROMETHEUS_PREFIX


ORACLE_MEMBER_INFO = Info(
    "oracle_member",
    "Oracle member info",
    namespace=PROMETHEUS_PREFIX,
)

ORACLE_MEMBER_LAST_REPORT_REF_SLOT = Gauge(
    "oracle_member_last_report_ref_slot",
    "Member last report ref slot",
    namespace=PROMETHEUS_PREFIX,
)

ORACLE_SLOT_NUMBER = Gauge(
    "oracle_slot_number",
    "Oracle head slot number",
    ["state"],  # "head" or "finalized"
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
