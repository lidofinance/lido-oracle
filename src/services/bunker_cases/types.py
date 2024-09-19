from dataclasses import dataclass


@dataclass
class BunkerConfig:
    normalized_cl_reward_per_epoch: int
    normalized_cl_reward_mistake_rate: float
    rebase_check_nearest_epoch_distance: int
    rebase_check_distant_epoch_distance: int
