from prometheus_client import Gauge

from src.variables import PROMETHEUS_PREFIX


CSM_CURRENT_FRAME_RANGE_L_EPOCH = Gauge(
    "csm_current_frame_range_l_epoch",
    "Left epoch of the current frame range",
    namespace=PROMETHEUS_PREFIX,
)

CSM_CURRENT_FRAME_RANGE_R_EPOCH = Gauge(
    "csm_current_frame_range_r_epoch",
    "Right epoch of the current frame range",
    namespace=PROMETHEUS_PREFIX,
)

CSM_UNPROCESSED_EPOCHS_COUNT = Gauge(
    "csm_unprocessed_epochs_count",
    "Unprocessed epochs count",
    namespace=PROMETHEUS_PREFIX,
)


CSM_MIN_UNPROCESSED_EPOCH = Gauge(
    "csm_min_unprocessed_epoch",
    "Minimum unprocessed epoch",
    namespace=PROMETHEUS_PREFIX,
)
