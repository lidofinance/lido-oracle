from prometheus_client import Gauge, Info

from src.variables import PROMETHEUS_PREFIX


ORACLE_MEMBER_INFO = Info(
    "member",
    "Oracle member info",
    namespace=PROMETHEUS_PREFIX,
)

ORACLE_MEMBER_LAST_REPORT_REF_SLOT = Gauge(
    "member_last_report_ref_slot",
    "Member last report ref slot",
    namespace=PROMETHEUS_PREFIX,
)

ORACLE_SLOT_NUMBER = Gauge(
    "slot_number",
    "Oracle head slot number",
    ["state"],  # "head" or "finalized"
    namespace=PROMETHEUS_PREFIX,
)

FRAME_CURRENT_REF_SLOT = Gauge(
    "frame_current_ref_slot",
    "Oracle frame current ref slot",
    namespace=PROMETHEUS_PREFIX,
)

FRAME_DEADLINE_SLOT = Gauge(
    "frame_deadline_slot",
    "Oracle frame deadline slot",
    namespace=PROMETHEUS_PREFIX,
)

FRAME_LAST_REPORT_REF_SLOT = Gauge(
    "frame_last_report_ref_slot",
    "Oracle frame last report ref slot",
    namespace=PROMETHEUS_PREFIX,
)
