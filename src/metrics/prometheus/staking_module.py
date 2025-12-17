from prometheus_client import Gauge

from src.variables import PROMETHEUS_PREFIX


STAKING_MODULE_CURRENT_FRAME_RANGE_L_EPOCH = Gauge(
    "staking_module_current_frame_range_l_epoch",
    "Left epoch of the current frame range",
    namespace=PROMETHEUS_PREFIX,
)

STAKING_MODULE_CURRENT_FRAME_RANGE_R_EPOCH = Gauge(
    "staking_module_current_frame_range_r_epoch",
    "Right epoch of the current frame range",
    namespace=PROMETHEUS_PREFIX,
)
