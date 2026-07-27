"""Reconciliation of Keys API used keys against Lido's on-chain ``depositedValidators`` counter.

``LidoValidatorsProvider._validate_total_validators_count`` requires

    len(active_lido_validators) + len(pending_lido_validators) == lido.depositedValidators

These tests build the protocol states that break that equality while the Keys API response is
*complete and correct*, so any failure is attributable to the reconciliation rule itself rather
than to a KAPI defect.

Deposit signatures are produced with real BLS keys and checked by the production verifier
(``src.services.deposit_signature_verification``). Both failure modes below hinge on whether a
signature actually verifies, so mocking the verifier away would make the tests vacuous.

Shared fixture state (see ``lido_protocol``): one staking module, one node operator with
``total_deposited_validators == 3``, and three used keys at indexes 0/1/2:

  * key 0 -- already a validator on the CL       -> counted as *active*
  * key 1 -- valid 32 ETH deposit to Lido WC     -> counted as *pending*
  * key 2 -- the variable under test
"""

from unittest.mock import Mock

import blst
import pytest
from eth_typing import HexStr

from src.constants import DOMAIN_DEPOSIT_TYPE, ETH1_ADDRESS_WITHDRAWAL_PREFIX
from src.modules.oracles.accounting.accounting import Accounting
from src.modules.oracles.accounting.types import BeaconStat
from src.providers.consensus.types import PendingDeposit
from src.services.deposit_signature_verification import (
    _POP_DST,
    DepositMessage,
    compute_domain,
    compute_signing_root,
)
from src.types import Gwei, NodeOperatorId, SlotNumber
from src.utils.cache import clear_global_cache
from src.utils.types import hex_str_to_bytes
from src.web3py.extensions.lido_validators import CountOfKeysDiffersException
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.no_registry import (
    LidoKeyFactory,
    NodeOperatorFactory,
    StakingModuleFactory,
    ValidatorFactory,
    ValidatorStateFactory,
)


DEPOSITED_VALIDATORS = 3

# Seeds for deterministic BLS keys. Seed N is the key at operator key index N.
_ACTIVE_KEY = 1
_PENDING_KEY = 2
_SUBJECT_KEY = 3

_LIDO_WITHDRAWAL_VAULT = '0x' + 'ab' * 20
_OPERATOR_OWN_VAULT = '0x' + 'cd' * 20

_GENESIS_FORK_VERSION = HexStr('0x10000038')
_DEPOSIT_AMOUNT = Gwei(32 * 10**9)
_DEPOSIT_SLOT = SlotNumber(1)

# 96-byte value that is well-formed for `blst.P2_Affine` but verifies against nothing.
_GARBAGE_SIGNATURE = HexStr('0x' + 'c0' + '00' * 95)


def _withdrawal_credentials(vault_address: str) -> HexStr:
    """Mirror `LidoValidatorsProvider.get_lido_wc_list` 0x01 credential layout."""
    return HexStr(ETH1_ADDRESS_WITHDRAWAL_PREFIX + '0' * 22 + vault_address[2:].lower())


_LIDO_WC = _withdrawal_credentials(_LIDO_WITHDRAWAL_VAULT)
_OPERATOR_WC = _withdrawal_credentials(_OPERATOR_OWN_VAULT)


def _secret_key(seed: int) -> blst.SecretKey:
    secret_key = blst.SecretKey()
    secret_key.keygen(seed.to_bytes(32, 'big'))
    return secret_key


def _pubkey(seed: int) -> HexStr:
    return HexStr('0x' + blst.P1(_secret_key(seed)).compress().hex())


def _proof_of_possession(seed: int, withdrawal_credentials: HexStr) -> HexStr:
    """Produce a genuinely valid deposit signature.

    Only the holder of the validator's secret key can sign a deposit for an arbitrary
    withdrawal credential -- which is exactly why the "front run" branch in
    `_collect_valid_pending_deposits` describes a malicious *key owner*, not an outsider.
    """
    message = DepositMessage(
        pubkey=hex_str_to_bytes(_pubkey(seed)),
        withdrawal_credentials=hex_str_to_bytes(withdrawal_credentials),
        amount=_DEPOSIT_AMOUNT,
    )
    signing_root = compute_signing_root(
        message, compute_domain(DOMAIN_DEPOSIT_TYPE, hex_str_to_bytes(_GENESIS_FORK_VERSION))
    )
    signature = blst.P2().hash_to(signing_root, _POP_DST).sign_with(_secret_key(seed)).compress()
    return HexStr('0x' + signature.hex())


def _deposit(seed: int, withdrawal_credentials: HexStr, signature: HexStr | None = None) -> PendingDeposit:
    return PendingDeposit(
        pubkey=_pubkey(seed),
        withdrawal_credentials=withdrawal_credentials,
        amount=_DEPOSIT_AMOUNT,
        signature=signature if signature is not None else _proof_of_possession(seed, withdrawal_credentials),
        slot=_DEPOSIT_SLOT,
    )


ref_bs = ReferenceBlockStampFactory.build()


@pytest.fixture(autouse=True)
def _isolate_global_cache():
    clear_global_cache()
    yield
    clear_global_cache()


@pytest.fixture
def lido_protocol(web3):
    """Wire a minimal but complete protocol state around the real `LidoValidatorsProvider`.

    Only the provider's collaborators (CL, EL contracts, Keys API) are mocked -- every method
    under test runs for real, including BLS verification.
    """
    staking_module = StakingModuleFactory.build()
    operator = NodeOperatorFactory.build(
        id=NodeOperatorId(0),
        staking_module=staking_module,
        total_deposited_validators=DEPOSITED_VALIDATORS,
    )

    lido_keys = [
        LidoKeyFactory.build(
            index=index,
            key=_pubkey(seed),
            operator_index=operator.id,
            module_address=staking_module.staking_module_address,
            used=True,
        )
        for index, seed in enumerate((_ACTIVE_KEY, _PENDING_KEY, _SUBJECT_KEY))
    ]

    # Keys API response is complete: indexes 0..2 for the only operator, all used.
    web3.kac.get_used_lido_keys = Mock(return_value=lido_keys)

    web3.lido_contracts.lido.get_beacon_stat = Mock(
        return_value=BeaconStat(deposited_validators=DEPOSITED_VALIDATORS, beacon_validators=1, beacon_balance=0)
    )
    web3.lido_contracts.lido_locator.withdrawal_vault = Mock(return_value=_LIDO_WITHDRAWAL_VAULT)
    web3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[staking_module])
    web3.lido_contracts.staking_router.get_all_node_operator_digests = Mock(return_value=[operator])

    web3.cc.get_genesis = Mock(return_value=Mock(genesis_fork_version=_GENESIS_FORK_VERSION))
    web3.cc.get_pending_consolidations = Mock(return_value=[])
    web3.cc.get_pending_deposits = Mock(return_value=[])

    def set_cl_validators(*seeds_with_wc: tuple[int, HexStr]) -> None:
        validators = [
            ValidatorFactory.build(
                index=index,
                validator=ValidatorStateFactory.build(pubkey=_pubkey(seed), withdrawal_credentials=wc),
            )
            for index, (seed, wc) in enumerate(seeds_with_wc)
        ]
        web3.cc.get_validators = Mock(return_value=validators)
        web3.cc.get_validators_by_indexes = Mock(return_value={v.index: v for v in validators})

    # Key 0 is live on the CL with Lido withdrawal credentials.
    set_cl_validators((_ACTIVE_KEY, _LIDO_WC))

    def set_pending_deposits(*deposits: PendingDeposit) -> None:
        web3.cc.get_pending_deposits = Mock(return_value=list(deposits))

    return Mock(
        web3=web3,
        keys=lido_keys,
        operator=operator,
        staking_module=staking_module,
        set_cl_validators=set_cl_validators,
        set_pending_deposits=set_pending_deposits,
    )


# ---- baseline: the reconciliation must hold on a healthy state ----------------------------------
#
# Without this test the failing ones below would prove nothing -- they could be failing because the
# fixture is wired wrong rather than because of the state under test.


@pytest.mark.unit
def test_get_active_lido_validators__every_used_key_active_or_pending__reconciles(lido_protocol):
    # Arrange: keys 1 and 2 both have valid 32 ETH deposits to the Lido withdrawal vault.
    lido_protocol.set_pending_deposits(
        _deposit(_PENDING_KEY, _LIDO_WC),
        _deposit(_SUBJECT_KEY, _LIDO_WC),
    )

    # Act
    active = lido_protocol.web3.lido_validators.get_active_lido_validators(ref_bs)
    pending = lido_protocol.web3.lido_validators.get_pending_lido_validators(ref_bs)

    # Assert
    assert len(active) == 1
    assert len(pending) == 2
    assert len(active) + len(pending) == DEPOSITED_VALIDATORS


@pytest.mark.unit
def test_get_active_lido_validators__garbage_signature_then_lido_deposit__reconciles(lido_protocol):
    """An outsider cannot grief the reconciliation.

    Anyone may queue a deposit for a known Lido pubkey, but without the secret key the signature
    cannot verify. `_collect_valid_pending_deposits` skips such a deposit without blacklisting the
    pubkey, so Lido's own deposit behind it still counts as pending -- and the CL likewise ignores
    the unverifiable deposit when creating the validator.
    """
    # Arrange
    lido_protocol.set_pending_deposits(
        _deposit(_PENDING_KEY, _LIDO_WC),
        _deposit(_SUBJECT_KEY, _OPERATOR_WC, signature=_GARBAGE_SIGNATURE),
        _deposit(_SUBJECT_KEY, _LIDO_WC),
    )

    # Act
    active = lido_protocol.web3.lido_validators.get_active_lido_validators(ref_bs)
    pending = lido_protocol.web3.lido_validators.get_pending_lido_validators(ref_bs)

    # Assert
    assert len(active) + len(pending) == DEPOSITED_VALIDATORS
    assert _pubkey(_SUBJECT_KEY) in pending


# ---- failure mode 1: node operator front-runs its own key --------------------------------------


@pytest.mark.unit
def test_get_active_lido_validators__operator_frontran_own_key__blocks_reporting(lido_protocol):
    """A key owner can stall the reconciliation on demand.

    The operator signs a deposit for its own pubkey with its own withdrawal credentials and lands
    it ahead of Lido's. `_collect_valid_pending_deposits` deliberately drops that pubkey entirely
    ("Ignoring key. Possible front run attack") so its balance is not credited to Lido -- which is
    the conservative, intended behaviour. `depositedValidators` was already incremented on the EL,
    so the key is now counted in neither `active` nor `pending` and the equality cannot hold.
    """
    # Arrange
    lido_protocol.set_pending_deposits(
        _deposit(_PENDING_KEY, _LIDO_WC),
        _deposit(_SUBJECT_KEY, _OPERATOR_WC),  # front run, validly signed by the key owner
        _deposit(_SUBJECT_KEY, _LIDO_WC),  # Lido's own deposit, right behind it
    )

    # Act / Assert: the front-run key is excluded from pending, so 1 + 1 != 3
    pending = lido_protocol.web3.lido_validators.get_pending_lido_validators(ref_bs)
    assert _pubkey(_SUBJECT_KEY) not in pending
    assert len(pending) == 1

    with pytest.raises(CountOfKeysDiffersException, match=r'\(2\).*does not match deposited validators count \(3\)'):
        lido_protocol.web3.lido_validators.get_active_lido_validators(ref_bs)


@pytest.mark.unit
def test_get_active_lido_validators__frontrun_validator_created_on_cl__reconciles_again(lido_protocol):
    """The stall above lasts exactly as long as the deposit sits in the CL queue.

    Once the CL creates the validator, `compute_lido_validators` matches it by pubkey regardless of
    its withdrawal credentials, so it counts as active and the equality holds again. This bounds
    the outage to the pending-deposit queue delay -- but the operator can repeat it per key.
    """
    # Arrange: the front-run validator now exists on the CL with the operator's own credentials.
    lido_protocol.set_cl_validators((_ACTIVE_KEY, _LIDO_WC), (_SUBJECT_KEY, _OPERATOR_WC))
    lido_protocol.set_pending_deposits(
        _deposit(_PENDING_KEY, _LIDO_WC),
        _deposit(_SUBJECT_KEY, _LIDO_WC),
    )

    # Act
    active = lido_protocol.web3.lido_validators.get_active_lido_validators(ref_bs)

    # Assert
    assert len(active) == 2
    assert len(active) + len(lido_protocol.web3.lido_validators.get_pending_lido_validators(ref_bs)) == 3


# ---- failure mode 2: the CL discarded the deposit ----------------------------------------------


@pytest.mark.unit
def test_get_active_lido_validators__cl_discarded_the_deposit__blocks_reporting_permanently(lido_protocol):
    """A used key can be absent from both the validator registry and the deposit queue, forever.

    Per Electra `apply_pending_deposit`, a deposit for an unknown pubkey creates a validator only
    if `is_valid_deposit_signature` passes; otherwise it is ignored. `process_pending_deposits`
    pops the entry either way, so an invalid-signature deposit leaves no trace on the CL. Lido's
    `depositedValidators` counter was incremented at deposit time on the EL and never decreases,
    so `active + pending == depositedValidators` is violated for the lifetime of the protocol.

    Deposit signatures are supplied by node operators and are not validated on-chain; the DSM
    guardians check them off-chain, which makes this a process guarantee rather than a protocol one.
    """
    # Arrange: key 2 is used and deposited, but the CL has neither a validator nor a queued deposit.
    lido_protocol.set_pending_deposits(_deposit(_PENDING_KEY, _LIDO_WC))

    # Act / Assert
    with pytest.raises(CountOfKeysDiffersException, match=r'\(2\).*does not match deposited validators count \(3\)'):
        lido_protocol.web3.lido_validators.get_active_lido_validators(ref_bs)


# ---- the same states, driven through the accounting oracle --------------------------------------


@pytest.fixture
def accounting(lido_protocol) -> Accounting:
    return Accounting(lido_protocol.web3)


@pytest.fixture
def _frontrun_state(lido_protocol):
    lido_protocol.set_pending_deposits(
        _deposit(_PENDING_KEY, _LIDO_WC),
        _deposit(_SUBJECT_KEY, _OPERATOR_WC),
        _deposit(_SUBJECT_KEY, _LIDO_WC),
    )
    return lido_protocol


@pytest.mark.unit
def test_calculate_report__frontrun_key__aborts_before_any_report_data(accounting, _frontrun_state):
    """`_calculate_report` reads the CL balance second, so the whole report build dies there."""
    # Arrange
    accounting.get_consensus_version = Mock(return_value=4)

    # Act / Assert
    with pytest.raises(CountOfKeysDiffersException):
        accounting.build_report(ref_bs)


@pytest.mark.unit
def test_daemon_cycle__frontrun_key__no_report_submitted_and_cycle_retries(accounting, _frontrun_state, caplog):
    """Operational consequence: the daemon does not crash -- it silently stops reporting.

    `OracleModule.exception_handler` catches `CountOfKeysDiffersException`, so the cycle is
    abandoned and `_slot_threshold` is left untouched, i.e. the next cycle retries the same
    reference slot. For a state that never resolves (see `cl_discarded_the_deposit`) that is an
    indefinite reporting outage visible only in the logs.
    """
    # Arrange
    accounting._receive_last_finalized_slot = Mock(return_value=ref_bs)
    accounting.refresh_contracts_if_address_change = Mock()
    accounting.get_blockstamp_for_report = Mock(return_value=ref_bs)
    accounting._check_compatibility = Mock(return_value=True)
    accounting.get_consensus_version = Mock(return_value=4)
    accounting._process_report_hash = Mock()
    accounting._process_report_data = Mock()
    accounting.process_extra_data = Mock()

    # Act: a full daemon cycle, with only the report-frame selection and submission stubbed out.
    accounting._cycle()

    # Assert
    accounting._process_report_hash.assert_not_called()
    accounting._process_report_data.assert_not_called()
    accounting.process_extra_data.assert_not_called()
    assert accounting._slot_threshold == 0, 'cycle must not advance, so the next cycle retries'
    assert 'Keys API service returned incorrect number of keys' in caplog.text
