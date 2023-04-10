# https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#misc
FAR_FUTURE_EPOCH = 2 ** 64 - 1
# https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#time-parameters-1
MIN_VALIDATOR_WITHDRAWABILITY_DELAY = 2**8
SHARD_COMMITTEE_PERIOD = 256
MAX_SEED_LOOKAHEAD = 4
# https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#state-list-lengths
EPOCHS_PER_SLASHINGS_VECTOR = 2**13
# https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#rewards-and-penalties
PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX = 3
# https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#gwei-values
EFFECTIVE_BALANCE_INCREMENT = 2 ** 0 * 10 ** 9
MAX_EFFECTIVE_BALANCE = 32 * 10 ** 9
# https://github.com/ethereum/consensus-specs/blob/dev/specs/capella/beacon-chain.md#execution
MAX_WITHDRAWALS_PER_PAYLOAD = 2 ** 4
# https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#withdrawal-prefixes
ETH1_ADDRESS_WITHDRAWAL_PREFIX = '0x01'
# https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#validator-cycle
MIN_PER_EPOCH_CHURN_LIMIT = 2 ** 2
CHURN_LIMIT_QUOTIENT = 2 ** 16

# Local constants
GWEI_TO_WEI = 10 ** 9
SHARE_RATE_PRECISION_E27 = 10**27
TOTAL_BASIS_POINTS = 10000

MAX_BLOCK_GAS_LIMIT = 30_000_000
