from packaging.version import Version

from src.types import Gwei

# https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#misc
FAR_FUTURE_EPOCH = 2**64 - 1
# https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#time-parameters-1
MIN_VALIDATOR_WITHDRAWABILITY_DELAY = 2**8
MAX_SEED_LOOKAHEAD = 4
# https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#state-list-lengths
EPOCHS_PER_SLASHINGS_VECTOR = 2**13
# https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#rewards-and-penalties
PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX = 3
# https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#gwei-values
EFFECTIVE_BALANCE_INCREMENT = Gwei(2**0 * 10**9)
MAX_EFFECTIVE_BALANCE = Gwei(32 * 10**9)
MIN_DEPOSIT_AMOUNT = Gwei(2**0 * 10**9)
# https://github.com/ethereum/consensus-specs/blob/dev/specs/electra/beacon-chain.md#gwei-values
MAX_EFFECTIVE_BALANCE_ELECTRA = Gwei(2**11 * 10**9)
MIN_ACTIVATION_BALANCE = Gwei(2**5 * 10**9)
# https://github.com/ethereum/consensus-specs/blob/dev/specs/capella/beacon-chain.md#execution
MAX_WITHDRAWALS_PER_PAYLOAD = 2**4
# https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#withdrawal-prefixes
ETH1_ADDRESS_WITHDRAWAL_PREFIX = '0x01'
# https://github.com/ethereum/consensus-specs/blob/dev/specs/electra/beacon-chain.md#withdrawal-prefixes
COMPOUNDING_WITHDRAWAL_PREFIX = '0x02'
# https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#validator-cycle
MIN_PER_EPOCH_CHURN_LIMIT = 2**2
CHURN_LIMIT_QUOTIENT = 2**16
# https://github.com/ethereum/consensus-specs/blob/dev/specs/electra/beacon-chain.md#validator-cycle
MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA = Gwei(2**7 * 10**9)
MAX_PER_EPOCH_ACTIVATION_EXIT_CHURN_LIMIT = Gwei(2**8 * 10**9)
# https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#time-parameters
SLOTS_PER_HISTORICAL_ROOT = 2**13  # 8192
# https://github.com/ethereum/consensus-specs/blob/dev/specs/altair/beacon-chain.md#sync-committee
EPOCHS_PER_SYNC_COMMITTEE_PERIOD = 256
# https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#domain-types
DOMAIN_DEPOSIT_TYPE = bytes.fromhex("03000000")  # 0x03000000

# https://github.com/ethereum/consensus-specs/blob/dev/specs/electra/beacon-chain.md#withdrawals-processing
MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP = 2**3

# Lido contracts constants
# We assume that the Lido deposit amount is currently 32 ETH (MIN_ACTIVATION_BALANCE).
# If Lido decides to support 0x2 withdrawal credentials in the future, this variable
# should be revisited to accommodate potential changes in deposit requirements.
LIDO_DEPOSIT_AMOUNT = MIN_ACTIVATION_BALANCE
PRECISION_E27 = 27
SHARE_RATE_PRECISION_E27 = 10**PRECISION_E27
TOTAL_BASIS_POINTS = 10000

# Lido CSM constants for network performance calculation
ATTESTATIONS_WEIGHT = 54
BLOCKS_WEIGHT = 8
SYNC_WEIGHT = 2

# Local constants
GWEI_TO_WEI = 10**9
MAX_BLOCK_GAS_LIMIT = 30_000_000
UINT64_MAX = 2**64 - 1
UINT256_MAX = 2**256 - 1

ALLOWED_KAPI_VERSION = Version('1.5.0')
CSM_STATE_VERSION = 1

GENESIS_VALIDATORS_ROOT = bytes([0] * 32)  # all zeros for deposits
