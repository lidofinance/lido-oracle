"""
Unit tests for _get_validated_pending_balances_by_pubkey, _calculate_pending_deposits_balance,
and _get_modules_balances.
Uses real BLS signatures for deposit validation.
"""

from unittest.mock import Mock

import pytest
from py_ecc.bls import G2ProofOfPossession as BLS

from src.modules.accounting.accounting import Accounting, logger as accounting_logger
from src.providers.consensus.types import PendingDeposit
from src.types import Gwei, SlotNumber, StakingModuleType
from src.utils.deposit_signature import DepositMessage, compute_domain, compute_signing_root
from src.constants import DOMAIN_DEPOSIT_TYPE
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.no_registry import LidoKeyFactory, LidoValidatorFactory, StakingModuleFactory, ValidatorStateFactory

# --- BLS helpers ---

GENESIS_FORK_VERSION = b'\x00\x00\x00\x00'
GENESIS_VALIDATORS_ROOT = b'\x00' * 32
LIDO_WC = '0x010000000000000000000000b9d7934878b5fb9610b3fe8a5e441e8fad7e293f'
OTHER_WC = '0x010000000000000000000000aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'


def _make_bls_keypair():
    """Generate a BLS private key and derive the public key."""
    import secrets

    # BLS12-381 curve order
    CURVE_ORDER = 0x73EDA753299D7D483339D80809A1D80553BDA402FFFE5BFEFFFFFFFF00000001
    privkey = (int.from_bytes(secrets.token_bytes(32)) % (CURVE_ORDER - 1)) + 1
    pubkey = BLS.SkToPk(privkey)
    return privkey, pubkey


def _sign_deposit(privkey: int, pubkey: bytes, wc: str, amount_gwei: int) -> bytes:
    """Create a valid BLS deposit signature."""
    message = DepositMessage(
        pubkey,
        bytes.fromhex(wc[2:]),
        amount_gwei,
    )
    domain = compute_domain(DOMAIN_DEPOSIT_TYPE, GENESIS_FORK_VERSION, GENESIS_VALIDATORS_ROOT)
    signing_root = compute_signing_root(message, domain)
    return BLS.Sign(privkey, signing_root)


def _make_pending_deposit(privkey: int, pubkey: bytes, wc: str, amount_gwei: int, slot: int = 100) -> PendingDeposit:
    """Create a PendingDeposit with a valid BLS signature."""
    sig = _sign_deposit(privkey, pubkey, wc, amount_gwei)
    return PendingDeposit(
        pubkey='0x' + pubkey.hex(),
        withdrawal_credentials=wc,
        amount=Gwei(amount_gwei),
        signature='0x' + sig.hex(),
        slot=SlotNumber(slot),
    )


def _make_invalid_pending_deposit(pubkey: bytes, wc: str, amount_gwei: int, slot: int = 100) -> PendingDeposit:
    """Create a PendingDeposit with an invalid BLS signature."""
    return PendingDeposit(
        pubkey='0x' + pubkey.hex(),
        withdrawal_credentials=wc,
        amount=Gwei(amount_gwei),
        signature='0x' + (b'\xaa' * 96).hex(),
        slot=SlotNumber(slot),
    )


# --- Fixtures ---


@pytest.fixture(autouse=True)
def silence_logger():
    accounting_logger.disabled = True


@pytest.fixture
def accounting(web3):
    return Accounting(web3)


@pytest.fixture
def ref_bs():
    return ReferenceBlockStampFactory.build()


@pytest.fixture
def genesis_config():
    return Mock(
        genesis_fork_version='0x' + GENESIS_FORK_VERSION.hex(),
        genesis_validators_root='0x' + GENESIS_VALIDATORS_ROOT.hex(),
    )


# --- Tests for _get_validated_pending_balances_by_pubkey ---


@pytest.mark.unit
def test_validated_pending_no_deposits(accounting, ref_bs, genesis_config):
    """No pending deposits -> empty result."""
    accounting.w3.cc.get_pending_deposits = Mock(return_value=[])
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=[])

    result = accounting._get_validated_pending_balances_by_pubkey(ref_bs)

    assert result == {}


@pytest.mark.unit
def test_validated_pending_valid_deposit(accounting, ref_bs, genesis_config):
    """Single valid deposit with correct WC -> included."""
    privkey, pubkey = _make_bls_keypair()
    deposit = _make_pending_deposit(privkey, pubkey, LIDO_WC, 32_000_000_000)

    accounting.w3.cc.get_pending_deposits = Mock(return_value=[deposit])
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=[])
    accounting.w3.lido_contracts.lido.get_withdrawal_credentials = Mock(return_value=LIDO_WC)
    accounting.get_cc_genesis_config = Mock(return_value=genesis_config)

    result = accounting._get_validated_pending_balances_by_pubkey(ref_bs)

    assert len(result) == 1
    assert result[deposit.pubkey] == Gwei(32_000_000_000)


@pytest.mark.unit
def test_validated_pending_invalid_bls_signature(accounting, ref_bs, genesis_config):
    """Deposit with invalid BLS signature -> excluded."""
    _, pubkey = _make_bls_keypair()
    deposit = _make_invalid_pending_deposit(pubkey, LIDO_WC, 32_000_000_000)

    accounting.w3.cc.get_pending_deposits = Mock(return_value=[deposit])
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=[])
    accounting.w3.lido_contracts.lido.get_withdrawal_credentials = Mock(return_value=LIDO_WC)
    accounting.get_cc_genesis_config = Mock(return_value=genesis_config)

    result = accounting._get_validated_pending_balances_by_pubkey(ref_bs)

    assert result == {}


@pytest.mark.unit
def test_validated_pending_wrong_wc(accounting, ref_bs, genesis_config):
    """Valid BLS but WC != Lido -> all-or-nothing, returns 0 for that pubkey."""
    privkey, pubkey = _make_bls_keypair()
    deposit = _make_pending_deposit(privkey, pubkey, OTHER_WC, 32_000_000_000)

    accounting.w3.cc.get_pending_deposits = Mock(return_value=[deposit])
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=[])
    accounting.w3.lido_contracts.lido.get_withdrawal_credentials = Mock(return_value=LIDO_WC)
    accounting.get_cc_genesis_config = Mock(return_value=genesis_config)

    result = accounting._get_validated_pending_balances_by_pubkey(ref_bs)

    assert result == {}


@pytest.mark.unit
def test_validated_pending_counts_existing_validator_topup(accounting, ref_bs, genesis_config):
    """Deposits for existing Lido validators are counted (MaxEB top-up)."""
    privkey, pubkey = _make_bls_keypair()
    pubkey_hex = '0x' + pubkey.hex()
    deposit = _make_pending_deposit(privkey, pubkey, LIDO_WC, 32_000_000_000)

    # Validator already exists with this pubkey
    existing_validator = LidoValidatorFactory.build(
        validator=ValidatorStateFactory.build(pubkey=pubkey_hex),
        balance=Gwei(32_000_000_000),
    )

    accounting.w3.cc.get_pending_deposits = Mock(return_value=[deposit])
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=[existing_validator])
    accounting.w3.lido_contracts.lido.get_withdrawal_credentials = Mock(return_value=LIDO_WC)
    accounting.get_cc_genesis_config = Mock(return_value=genesis_config)

    result = accounting._get_validated_pending_balances_by_pubkey(ref_bs)

    assert len(result) == 1
    assert result[pubkey_hex] == Gwei(32_000_000_000)


@pytest.mark.unit
def test_validated_pending_existing_validator_multiple_topups(accounting, ref_bs, genesis_config):
    """Multiple top-up deposits for existing validator — all counted."""
    privkey, pubkey = _make_bls_keypair()
    pubkey_hex = '0x' + pubkey.hex()
    deposit1 = _make_pending_deposit(privkey, pubkey, LIDO_WC, 16_000_000_000, slot=100)
    deposit2 = _make_pending_deposit(privkey, pubkey, LIDO_WC, 15_000_000_000, slot=101)

    existing_validator = LidoValidatorFactory.build(
        validator=ValidatorStateFactory.build(pubkey=pubkey_hex),
        balance=Gwei(32_000_000_000),
    )

    accounting.w3.cc.get_pending_deposits = Mock(return_value=[deposit1, deposit2])
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=[existing_validator])
    accounting.w3.lido_contracts.lido.get_withdrawal_credentials = Mock(return_value=LIDO_WC)
    accounting.get_cc_genesis_config = Mock(return_value=genesis_config)

    result = accounting._get_validated_pending_balances_by_pubkey(ref_bs)

    assert result[pubkey_hex] == Gwei(16_000_000_000 + 15_000_000_000)


@pytest.mark.unit
def test_validated_pending_existing_validator_no_bls_check(accounting, ref_bs, genesis_config):
    """Deposits for existing validators bypass BLS check (Eligible status per spec)."""
    _, pubkey = _make_bls_keypair()
    pubkey_hex = '0x' + pubkey.hex()
    # Invalid BLS signature — still counted for existing validator
    deposit = _make_invalid_pending_deposit(pubkey, LIDO_WC, 31_000_000_000)

    existing_validator = LidoValidatorFactory.build(
        validator=ValidatorStateFactory.build(pubkey=pubkey_hex),
        balance=Gwei(32_000_000_000),
    )

    accounting.w3.cc.get_pending_deposits = Mock(return_value=[deposit])
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=[existing_validator])
    accounting.w3.lido_contracts.lido.get_withdrawal_credentials = Mock(return_value=LIDO_WC)
    accounting.get_cc_genesis_config = Mock(return_value=genesis_config)

    result = accounting._get_validated_pending_balances_by_pubkey(ref_bs)

    assert len(result) == 1
    assert result[pubkey_hex] == Gwei(31_000_000_000)


@pytest.mark.unit
def test_validated_pending_multiple_deposits_same_pubkey(accounting, ref_bs, genesis_config):
    """Multiple deposits for same pubkey: first valid -> all subsequent accepted (front-run protection)."""
    privkey, pubkey = _make_bls_keypair()

    valid_deposit = _make_pending_deposit(privkey, pubkey, LIDO_WC, 32_000_000_000)
    # Second deposit with different WC — accepted because first was valid
    frontrun_deposit = PendingDeposit(
        pubkey='0x' + pubkey.hex(),
        withdrawal_credentials=OTHER_WC,
        amount=Gwei(1_000_000_000),
        signature='0x' + (b'\xbb' * 96).hex(),
        slot=SlotNumber(101),
    )

    accounting.w3.cc.get_pending_deposits = Mock(return_value=[valid_deposit, frontrun_deposit])
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=[])
    accounting.w3.lido_contracts.lido.get_withdrawal_credentials = Mock(return_value=LIDO_WC)
    accounting.get_cc_genesis_config = Mock(return_value=genesis_config)

    result = accounting._get_validated_pending_balances_by_pubkey(ref_bs)

    assert len(result) == 1
    assert result[valid_deposit.pubkey] == Gwei(32_000_000_000 + 1_000_000_000)


@pytest.mark.unit
def test_validated_pending_mixed_pubkeys(accounting, ref_bs, genesis_config):
    """Multiple pubkeys: one valid, one invalid BLS, one wrong WC."""
    priv1, pub1 = _make_bls_keypair()
    _, pub2 = _make_bls_keypair()
    priv3, pub3 = _make_bls_keypair()

    deposit_valid = _make_pending_deposit(priv1, pub1, LIDO_WC, 32_000_000_000)
    deposit_invalid_bls = _make_invalid_pending_deposit(pub2, LIDO_WC, 16_000_000_000)
    deposit_wrong_wc = _make_pending_deposit(priv3, pub3, OTHER_WC, 64_000_000_000)

    accounting.w3.cc.get_pending_deposits = Mock(return_value=[deposit_valid, deposit_invalid_bls, deposit_wrong_wc])
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=[])
    accounting.w3.lido_contracts.lido.get_withdrawal_credentials = Mock(return_value=LIDO_WC)
    accounting.get_cc_genesis_config = Mock(return_value=genesis_config)

    result = accounting._get_validated_pending_balances_by_pubkey(ref_bs)

    assert len(result) == 1
    pub1_hex = '0x' + pub1.hex()
    assert result[pub1_hex] == Gwei(32_000_000_000)


@pytest.mark.unit
def test_frontrun_invalid_bls_before_valid(accounting, ref_bs, genesis_config):
    """Front-run: attacker places deposit with invalid BLS before legitimate one.
    Invalid BLS is skipped, legitimate deposit is still counted."""
    privkey, pubkey = _make_bls_keypair()
    pubkey_hex = '0x' + pubkey.hex()

    # Attacker's deposit — same pubkey, invalid BLS signature
    frontrun = PendingDeposit(
        pubkey=pubkey_hex,
        withdrawal_credentials=OTHER_WC,
        amount=Gwei(32_000_000_000),
        signature='0x' + (b'\xcc' * 96).hex(),
        slot=SlotNumber(99),
    )
    # Legitimate Lido deposit
    legit = _make_pending_deposit(privkey, pubkey, LIDO_WC, 32_000_000_000, slot=100)

    accounting.w3.cc.get_pending_deposits = Mock(return_value=[frontrun, legit])
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=[])
    accounting.w3.lido_contracts.lido.get_withdrawal_credentials = Mock(return_value=LIDO_WC)
    accounting.get_cc_genesis_config = Mock(return_value=genesis_config)

    result = accounting._get_validated_pending_balances_by_pubkey(ref_bs)

    # Invalid BLS is skipped, valid deposit is accepted
    assert len(result) == 1
    assert result[pubkey_hex] == Gwei(32_000_000_000)


@pytest.mark.unit
def test_frontrun_valid_bls_wrong_wc_first(accounting, ref_bs, genesis_config):
    """Front-run: attacker places deposit with VALID BLS but wrong WC before legitimate one.
    All-or-nothing: first valid BLS with wrong WC -> entire pubkey returns 0."""
    # If the FIRST valid-BLS deposit has wrong WC, all-or-nothing kicks in.
    privkey, pubkey = _make_bls_keypair()

    # First deposit: valid BLS, wrong WC — triggers all-or-nothing
    wrong_wc_deposit = _make_pending_deposit(privkey, pubkey, OTHER_WC, 1_000_000_000, slot=99)
    # Second deposit: valid BLS, correct WC — should NOT be counted
    legit_deposit = _make_pending_deposit(privkey, pubkey, LIDO_WC, 32_000_000_000, slot=100)

    accounting.w3.cc.get_pending_deposits = Mock(return_value=[wrong_wc_deposit, legit_deposit])
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=[])
    accounting.w3.lido_contracts.lido.get_withdrawal_credentials = Mock(return_value=LIDO_WC)
    accounting.get_cc_genesis_config = Mock(return_value=genesis_config)

    result = accounting._get_validated_pending_balances_by_pubkey(ref_bs)

    # All-or-nothing: first valid deposit had wrong WC -> 0 for this pubkey
    assert result == {}


# --- Tests for _calculate_pending_deposits_balance ---


@pytest.mark.unit
def test_pending_balance_sums_validated(accounting, ref_bs, genesis_config):
    """_calculate_pending_deposits_balance returns sum of all validated pubkey balances."""
    priv1, pub1 = _make_bls_keypair()
    priv2, pub2 = _make_bls_keypair()

    deposit1 = _make_pending_deposit(priv1, pub1, LIDO_WC, 32_000_000_000)
    deposit2 = _make_pending_deposit(priv2, pub2, LIDO_WC, 64_000_000_000)

    accounting.w3.cc.get_pending_deposits = Mock(return_value=[deposit1, deposit2])
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=[])
    accounting.w3.lido_contracts.lido.get_withdrawal_credentials = Mock(return_value=LIDO_WC)
    accounting.get_cc_genesis_config = Mock(return_value=genesis_config)

    result = accounting._calculate_pending_deposits_balance(ref_bs)

    assert result == Gwei(32_000_000_000 + 64_000_000_000)


@pytest.mark.unit
def test_pending_balance_empty(accounting, ref_bs):
    """No pending deposits -> balance is 0."""
    accounting.w3.cc.get_pending_deposits = Mock(return_value=[])
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=[])

    result = accounting._calculate_pending_deposits_balance(ref_bs)

    assert result == Gwei(0)


@pytest.mark.unit
def test_pending_balance_excludes_invalid(accounting, ref_bs, genesis_config):
    """Only valid deposits contribute to total balance."""
    priv1, pub1 = _make_bls_keypair()
    _, pub2 = _make_bls_keypair()

    valid_deposit = _make_pending_deposit(priv1, pub1, LIDO_WC, 32_000_000_000)
    invalid_deposit = _make_invalid_pending_deposit(pub2, LIDO_WC, 16_000_000_000)

    accounting.w3.cc.get_pending_deposits = Mock(return_value=[valid_deposit, invalid_deposit])
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=[])
    accounting.w3.lido_contracts.lido.get_withdrawal_credentials = Mock(return_value=LIDO_WC)
    accounting.get_cc_genesis_config = Mock(return_value=genesis_config)

    result = accounting._calculate_pending_deposits_balance(ref_bs)

    assert result == Gwei(32_000_000_000)


# --- Tests for _get_modules_balances ---


MODULE_ADDRESS_1 = '0x1111111111111111111111111111111111111111'
MODULE_ADDRESS_2 = '0x2222222222222222222222222222222222222222'
MODULE_ADDRESS_3 = '0x3333333333333333333333333333333333333333'


def _make_staking_module(module_id, address):
    return StakingModuleFactory.build(id=module_id, staking_module_address=address)


def _make_lido_key(pubkey_hex, module_address, operator_index=0):
    return LidoKeyFactory.build(key=pubkey_hex, moduleAddress=module_address, operatorIndex=operator_index)


@pytest.mark.unit
def test_modules_balances_active_balances(accounting, ref_bs):
    """Active validator balances are distributed correctly across modules."""
    module = _make_staking_module(1, MODULE_ADDRESS_1)

    validator = LidoValidatorFactory.build(
        balance=Gwei(32_000_000_000),
        lido_id=_make_lido_key('0x' + b'\x01'.hex().zfill(96), MODULE_ADDRESS_1),
    )

    accounting.w3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[module])
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=[validator])
    accounting.w3.cc.get_pending_deposits = Mock(return_value=[])
    accounting.w3.kac.get_used_lido_keys = Mock(return_value=[])

    module_ids, active_balances, pending_balances = accounting._get_modules_balances(ref_bs)

    assert module_ids == [1]
    assert active_balances == [Gwei(32_000_000_000)]
    assert pending_balances == [Gwei(0)]


@pytest.mark.unit
def test_modules_balances_uses_validated_pending(accounting, ref_bs, genesis_config):
    """Module pending balances use BLS-validated deposits, not raw sums."""
    module = _make_staking_module(1, MODULE_ADDRESS_1)

    privkey, pubkey = _make_bls_keypair()
    pubkey_hex = '0x' + pubkey.hex()
    valid_deposit = _make_pending_deposit(privkey, pubkey, LIDO_WC, 32_000_000_000)

    lido_key = _make_lido_key(pubkey_hex, MODULE_ADDRESS_1)

    accounting.w3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[module])
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=[])
    accounting.w3.cc.get_pending_deposits = Mock(return_value=[valid_deposit])
    accounting.w3.kac.get_used_lido_keys = Mock(return_value=[lido_key])
    accounting.w3.lido_contracts.lido.get_withdrawal_credentials = Mock(return_value=LIDO_WC)
    accounting.get_cc_genesis_config = Mock(return_value=genesis_config)

    module_ids, active_balances, pending_balances = accounting._get_modules_balances(ref_bs)

    assert module_ids == [1]
    assert pending_balances == [Gwei(32_000_000_000)]


@pytest.mark.unit
def test_modules_balances_excludes_invalid_bls(accounting, ref_bs, genesis_config):
    """Deposit with invalid BLS should NOT appear in module pending balances."""
    module = _make_staking_module(1, MODULE_ADDRESS_1)

    _, pubkey = _make_bls_keypair()
    pubkey_hex = '0x' + pubkey.hex()
    invalid_deposit = _make_invalid_pending_deposit(pubkey, LIDO_WC, 32_000_000_000)

    lido_key = _make_lido_key(pubkey_hex, MODULE_ADDRESS_1)

    accounting.w3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[module])
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=[])
    accounting.w3.cc.get_pending_deposits = Mock(return_value=[invalid_deposit])
    accounting.w3.kac.get_used_lido_keys = Mock(return_value=[lido_key])
    accounting.w3.lido_contracts.lido.get_withdrawal_credentials = Mock(return_value=LIDO_WC)
    accounting.get_cc_genesis_config = Mock(return_value=genesis_config)

    module_ids, active_balances, pending_balances = accounting._get_modules_balances(ref_bs)

    # No valid pending deposits, no active validators -> empty result
    assert module_ids == []
    assert pending_balances == []


@pytest.mark.unit
def test_modules_balances_invariant(accounting, ref_bs, genesis_config):
    """Invariant: sum(pending_balances_by_module) == clPendingBalance for same blockstamp."""
    module1 = _make_staking_module(1, MODULE_ADDRESS_1)
    module2 = _make_staking_module(2, MODULE_ADDRESS_2)

    priv1, pub1 = _make_bls_keypair()
    priv2, pub2 = _make_bls_keypair()
    pub1_hex = '0x' + pub1.hex()
    pub2_hex = '0x' + pub2.hex()

    deposit1 = _make_pending_deposit(priv1, pub1, LIDO_WC, 32_000_000_000)
    deposit2 = _make_pending_deposit(priv2, pub2, LIDO_WC, 64_000_000_000)

    key1 = _make_lido_key(pub1_hex, MODULE_ADDRESS_1)
    key2 = _make_lido_key(pub2_hex, MODULE_ADDRESS_2)

    accounting.w3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[module1, module2])
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=[])
    accounting.w3.cc.get_pending_deposits = Mock(return_value=[deposit1, deposit2])
    accounting.w3.kac.get_used_lido_keys = Mock(return_value=[key1, key2])
    accounting.w3.lido_contracts.lido.get_withdrawal_credentials = Mock(return_value=LIDO_WC)
    accounting.get_cc_genesis_config = Mock(return_value=genesis_config)

    # Get per-module pending balances
    module_ids, _, pending_balances = accounting._get_modules_balances(ref_bs)

    # Get total clPendingBalance
    cl_pending = accounting._calculate_pending_deposits_balance(ref_bs)

    # Invariant: sum of module pending balances == clPendingBalance
    assert sum(pending_balances) == cl_pending
    assert cl_pending == Gwei(32_000_000_000 + 64_000_000_000)


# --- Tests for _get_operator_balances module type filtering ---


def _mock_get_staking_module_type(type_map):
    """Return a mock that maps module_address -> StakingModuleType."""
    def _get_type(module_address, _block_identifier='latest'):
        return type_map[module_address]
    return _get_type


@pytest.mark.unit
def test_operator_balances_includes_allowed_module_types(accounting, ref_bs):
    """Modules with CURATED_ONCHAIN_V2_TYPE and COMMUNITY_ONCHAIN_V1_TYPE are included."""
    module1 = _make_staking_module(1, MODULE_ADDRESS_1)
    module2 = _make_staking_module(2, MODULE_ADDRESS_2)

    validator1 = LidoValidatorFactory.build(
        balance=Gwei(32_000_000_000),
        lido_id=_make_lido_key('0x' + b'\x01'.hex().zfill(96), MODULE_ADDRESS_1, operator_index=0),
    )
    validator2 = LidoValidatorFactory.build(
        balance=Gwei(31_000_000_000),
        lido_id=_make_lido_key('0x' + b'\x02'.hex().zfill(96), MODULE_ADDRESS_2, operator_index=0),
    )

    accounting.w3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[module1, module2])
    accounting.w3.lido_contracts.staking_router.get_staking_module_type = Mock(
        side_effect=_mock_get_staking_module_type({
            MODULE_ADDRESS_1: StakingModuleType.CURATED_ONCHAIN_V2_TYPE,
            MODULE_ADDRESS_2: StakingModuleType.COMMUNITY_ONCHAIN_V1_TYPE,
        })
    )
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=[validator1, validator2])
    accounting.w3.cc.get_pending_deposits = Mock(return_value=[])
    accounting.w3.kac.get_used_lido_keys = Mock(return_value=[])

    result = accounting._get_operator_balances(ref_bs)

    assert (1, 0) in result
    assert (2, 0) in result
    assert result[(1, 0)] == (32_000_000_000, 0)
    assert result[(2, 0)] == (31_000_000_000, 0)


@pytest.mark.unit
def test_operator_balances_excludes_unsupported_module_types(accounting, ref_bs):
    """Modules with CURATED_ONCHAIN_V1_TYPE are excluded from operator balances."""
    module_v1 = _make_staking_module(1, MODULE_ADDRESS_1)
    module_v2 = _make_staking_module(2, MODULE_ADDRESS_2)

    validator_v1 = LidoValidatorFactory.build(
        balance=Gwei(32_000_000_000),
        lido_id=_make_lido_key('0x' + b'\x01'.hex().zfill(96), MODULE_ADDRESS_1, operator_index=0),
    )
    validator_v2 = LidoValidatorFactory.build(
        balance=Gwei(31_000_000_000),
        lido_id=_make_lido_key('0x' + b'\x02'.hex().zfill(96), MODULE_ADDRESS_2, operator_index=0),
    )

    accounting.w3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[module_v1, module_v2])
    accounting.w3.lido_contracts.staking_router.get_staking_module_type = Mock(
        side_effect=_mock_get_staking_module_type({
            MODULE_ADDRESS_1: StakingModuleType.CURATED_ONCHAIN_V1_TYPE,
            MODULE_ADDRESS_2: StakingModuleType.CURATED_ONCHAIN_V2_TYPE,
        })
    )
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=[validator_v1, validator_v2])
    accounting.w3.cc.get_pending_deposits = Mock(return_value=[])
    accounting.w3.kac.get_used_lido_keys = Mock(return_value=[])

    result = accounting._get_operator_balances(ref_bs)

    # Module 1 (curated-onchain-v1) excluded, module 2 (curated-onchain-v2) included
    assert (1, 0) not in result
    assert (2, 0) in result
    assert result[(2, 0)] == (31_000_000_000, 0)


@pytest.mark.unit
def test_operator_balances_excludes_csm_module(accounting, ref_bs):
    """CSM module (community-staking-module) is excluded from operator balances."""
    module_csm = _make_staking_module(1, MODULE_ADDRESS_1)
    module_curated = _make_staking_module(2, MODULE_ADDRESS_2)

    validator_csm = LidoValidatorFactory.build(
        balance=Gwei(32_000_000_000),
        lido_id=_make_lido_key('0x' + b'\x01'.hex().zfill(96), MODULE_ADDRESS_1, operator_index=0),
    )
    validator_curated = LidoValidatorFactory.build(
        balance=Gwei(31_000_000_000),
        lido_id=_make_lido_key('0x' + b'\x02'.hex().zfill(96), MODULE_ADDRESS_2, operator_index=0),
    )

    accounting.w3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[module_csm, module_curated])
    accounting.w3.lido_contracts.staking_router.get_staking_module_type = Mock(
        side_effect=_mock_get_staking_module_type({
            MODULE_ADDRESS_1: StakingModuleType.COMMUNITY_ONCHAIN_DEVNET0_V1_TYPE,
            MODULE_ADDRESS_2: StakingModuleType.COMMUNITY_ONCHAIN_V1_TYPE,
        })
    )
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=[validator_csm, validator_curated])
    accounting.w3.cc.get_pending_deposits = Mock(return_value=[])
    accounting.w3.kac.get_used_lido_keys = Mock(return_value=[])

    result = accounting._get_operator_balances(ref_bs)

    # CSM module excluded, community-onchain-v1 included
    assert (1, 0) not in result
    assert (2, 0) in result


@pytest.mark.unit
def test_operator_balances_all_modules_excluded(accounting, ref_bs):
    """If all modules have unsupported types, result is empty."""
    module1 = _make_staking_module(1, MODULE_ADDRESS_1)
    module2 = _make_staking_module(2, MODULE_ADDRESS_2)

    validator1 = LidoValidatorFactory.build(
        balance=Gwei(32_000_000_000),
        lido_id=_make_lido_key('0x' + b'\x01'.hex().zfill(96), MODULE_ADDRESS_1, operator_index=0),
    )
    validator2 = LidoValidatorFactory.build(
        balance=Gwei(31_000_000_000),
        lido_id=_make_lido_key('0x' + b'\x02'.hex().zfill(96), MODULE_ADDRESS_2, operator_index=0),
    )

    accounting.w3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[module1, module2])
    accounting.w3.lido_contracts.staking_router.get_staking_module_type = Mock(
        side_effect=_mock_get_staking_module_type({
            MODULE_ADDRESS_1: StakingModuleType.CURATED_ONCHAIN_V1_TYPE,
            MODULE_ADDRESS_2: StakingModuleType.COMMUNITY_ONCHAIN_DEVNET0_V1_TYPE,
        })
    )
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=[validator1, validator2])
    accounting.w3.cc.get_pending_deposits = Mock(return_value=[])
    accounting.w3.kac.get_used_lido_keys = Mock(return_value=[])

    result = accounting._get_operator_balances(ref_bs)

    assert result == {}


@pytest.mark.unit
def test_operator_balances_pending_filtered_by_module_type(accounting, ref_bs, genesis_config):
    """Pending balances for excluded module types are not included."""
    module_csm = _make_staking_module(1, MODULE_ADDRESS_1)
    module_v2 = _make_staking_module(2, MODULE_ADDRESS_2)

    privkey, pubkey = _make_bls_keypair()
    pubkey_hex = '0x' + pubkey.hex()
    valid_deposit = _make_pending_deposit(privkey, pubkey, LIDO_WC, 32_000_000_000)

    # Key belongs to excluded CSM module
    lido_key_csm = _make_lido_key(pubkey_hex, MODULE_ADDRESS_1, operator_index=0)

    accounting.w3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[module_csm, module_v2])
    accounting.w3.lido_contracts.staking_router.get_staking_module_type = Mock(
        side_effect=_mock_get_staking_module_type({
            MODULE_ADDRESS_1: StakingModuleType.COMMUNITY_ONCHAIN_DEVNET0_V1_TYPE,
            MODULE_ADDRESS_2: StakingModuleType.CURATED_ONCHAIN_V2_TYPE,
        })
    )
    accounting.w3.lido_validators.get_lido_validators = Mock(return_value=[])
    accounting.w3.cc.get_pending_deposits = Mock(return_value=[valid_deposit])
    accounting.w3.kac.get_used_lido_keys = Mock(return_value=[lido_key_csm])
    accounting.w3.lido_contracts.lido.get_withdrawal_credentials = Mock(return_value=LIDO_WC)
    accounting.get_cc_genesis_config = Mock(return_value=genesis_config)

    result = accounting._get_operator_balances(ref_bs)

    # Pending deposit key belongs to CSM module (excluded), so result is empty
    assert result == {}
