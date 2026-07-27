"""Ether Lido paid for but cannot withdraw must never be reported as TVL.

``clValidatorsBalance`` and ``clPendingBalance`` are the only CL-side TVL inputs the contract takes
(``ReportSimulationPayload``); ``depositedValidators`` is not one of them, since deposits are tracked
on-chain by nonce (``BalanceStats``). So whatever the oracle leaves out of the active and pending
sets is what leaves TVL -- the oracle is the only thing that can carry such a loss.

The oracle never writes such a loss off on its own: it refuses to report and leaves the incident to
governance. Two causes, two exceptions:

* `FrontRunAttackError` -- someone else holds the withdrawal credentials. Raised whether the deposit
  is still queued or its validator already exists.
* `CountOfKeysDiffersException` -- the CL discarded the deposit, so the key is in neither set.

Deposit signatures are produced with real BLS keys and checked by the production verifier
(``src.services.deposit_signature_verification``). The scenarios turn on whether a signature
actually verifies -- only the key's owner can sign a deposit onto foreign credentials -- so mocking
the verifier away would make these tests vacuous.

Shared fixture state (see ``lido_protocol``): one staking module, one node operator with
``total_deposited_validators == 3``, and three used keys at indexes 0/1/2 -- a complete, correct
Keys API response, so nothing here is attributable to a KAPI defect:

  * key 0 -- already a validator on the CL       -> *active*
  * key 1 -- valid 32 ETH deposit to Lido WC     -> *pending*
  * key 2 -- the variable under test

None of these refusals clear on their own.
"""

from unittest.mock import Mock

import blst
import pytest
from eth_typing import HexStr

from src.constants import DOMAIN_DEPOSIT_TYPE, ETH1_ADDRESS_WITHDRAWAL_PREFIX
from src.modules.oracles.accounting.accounting import Accounting
from src.modules.oracles.accounting.types import (
    BeaconStat,
)
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
from src.web3py.extensions.lido_validators import CountOfKeysDiffersException, FrontRunAttackError
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

# Pinned so the TVL assertions below can name exact Gwei figures.
_VALIDATOR_BALANCE = Gwei(32_100_000_000)

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
                balance=_VALIDATOR_BALANCE,
                validator=ValidatorStateFactory.build(
                    pubkey=_pubkey(seed),
                    withdrawal_credentials=wc,
                    effective_balance=_DEPOSIT_AMOUNT,
                ),
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


@pytest.fixture
def accounting(lido_protocol) -> Accounting:
    return Accounting(lido_protocol.web3)


# ---- baselines: states with nothing to write off ------------------------------------------------
#
# Without these, the failing tests below would prove nothing -- they could be failing because the
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


# ---- a used key on a validator with non-Lido credentials must be refused, not written off -------


@pytest.mark.unit
def test_report__frontrun_validator_created_on_cl__reporting_is_refused(lido_protocol, accounting, caplog):
    """A used Lido key whose CL validator holds non-Lido withdrawal credentials must stop the report.

    Refused rather than filtered out of TVL: silently writing the ether off would drop TVL with no
    explanation and let a captured deposit pass as an ordinary loss. This state means a node
    operator holds the credentials for ether Lido paid for, and it needs a human, not an adjustment.

    Nothing detects it today. `_collect_valid_pending_deposits` drops a front-run pubkey, but that
    governs only *new* validators -- its `filter_pubkeys` is the set of Lido keys not yet on the CL.
    Once the CL creates the validator the pubkey leaves that set, and nothing downstream reinstates
    the exclusion: `compute_lido_validators` decides which CL validators are Lido's **by pubkey
    alone**, and no caller consults `get_lido_wc_list` on the active path (it is checked for pending
    deposits and in `abnormal_cl_rebase`, never for active validators).

    So the ether is reported as Lido's through both TVL terms -- measured here, 64.2 ETH in
    `clValidatorsBalance` and 64.0 ETH in `clPendingBalance`, i.e. 64.1 ETH attributed to a key only
    the operator can withdraw from. Note that summing the two is *not* double counting: a
    `pending_topup` is ether that has left the deposit contract but is not yet in `validator.balance`,
    and the two contributions to `clPendingBalance` are disjoint by construction. One gap, two
    contaminated terms.

    Caveat for whoever implements this: `0x01` withdrawal credentials are immutable, so unlike a
    front run still sitting in the deposit queue, this state never resolves on its own. Without a
    way for operators to acknowledge a known pubkey, the refusal is permanent and accounting stops
    reporting for good.

    What is pinned: no balance reaches the report, and the offending pubkey is named so an operator
    can act on it.
    """
    # Arrange: the front-run validator now exists on the CL with the operator's own credentials,
    # and Lido's own deposit for the same pubkey is still queued -- now a top-up, not a new deposit.
    lido_protocol.set_cl_validators((_ACTIVE_KEY, _LIDO_WC), (_SUBJECT_KEY, _OPERATOR_WC))
    lido_protocol.set_pending_deposits(
        _deposit(_PENDING_KEY, _LIDO_WC),
        _deposit(_SUBJECT_KEY, _LIDO_WC),
    )

    # Act / Assert: the balance must not be handed to the report at all.
    with pytest.raises(FrontRunAttackError) as raised:
        accounting._get_cl_validators_balance(ref_bs)

    # And the operator has to be able to find out which key is at fault.
    assert _pubkey(_SUBJECT_KEY) in str(raised.value) + caplog.text, (
        'the offending pubkey must be reported in the error or the logs'
    )


# ---- a queued front run is refused as well ------------------------------------------------------


@pytest.mark.unit
def test_report__operator_frontran_own_key__reporting_is_refused(lido_protocol, accounting, caplog):
    """The other half of the same attack: the front run is still sitting in the CL queue.

    `_collect_valid_pending_deposits` detects it here -- the pubkey is a Lido key not yet on the CL
    and its first valid-signature deposit carries someone else's credentials -- and refuses rather
    than dropping the key out of `clPendingBalance`. Same reasoning as the created-validator half
    above: a captured deposit must not pass as an ordinary loss.

    Only the key's owner can sign a deposit onto foreign credentials, so a node operator can reach
    this state at will. It clears when the CL creates the validator, at which point the check above
    takes over -- permanently, since credentials are immutable.
    """
    # Arrange
    lido_protocol.set_pending_deposits(
        _deposit(_PENDING_KEY, _LIDO_WC),
        _deposit(_SUBJECT_KEY, _OPERATOR_WC),  # front run, validly signed by the key owner
        _deposit(_SUBJECT_KEY, _LIDO_WC),  # Lido's own deposit, right behind it
    )

    # Act / Assert
    with pytest.raises(FrontRunAttackError):
        accounting._get_cl_pending_validators_balance(ref_bs)

    assert _pubkey(_SUBJECT_KEY) in caplog.text, 'the offending pubkey must be logged'


@pytest.mark.unit
def test_calculate_report__operator_frontran_own_key__report_is_refused(lido_protocol, accounting):
    """The refusal has to reach the report build, not just the balance helper."""
    # Arrange
    lido_protocol.set_pending_deposits(
        _deposit(_PENDING_KEY, _LIDO_WC),
        _deposit(_SUBJECT_KEY, _OPERATOR_WC),
        _deposit(_SUBJECT_KEY, _LIDO_WC),
    )
    accounting.get_consensus_version = Mock(return_value=4)

    # Act / Assert
    with pytest.raises(FrontRunAttackError):
        accounting.build_report(ref_bs)


# ---- the CL discarded the deposit ---------------------------------------------------------------


@pytest.mark.unit
def test_report__cl_discarded_the_deposit__reporting_is_refused(lido_protocol, accounting):
    """A used key the CL knows nothing about blocks the report, and stays blocked.

    Electra `apply_pending_deposit` creates a validator only if the signature verifies, and
    `process_pending_deposits` pops the entry either way -- so an invalid-signature deposit leaves no
    validator and no queue entry, while `depositedValidators` never decreases.

    `CountOfKeysDiffersException`, not `FrontRunAttackError`: nobody captured the ether, so there is
    no key to escalate -- only a count that stopped adding up.
    """
    # Arrange: key 2 is used and deposited, but the CL has neither a validator nor a queued deposit.
    lido_protocol.set_pending_deposits(_deposit(_PENDING_KEY, _LIDO_WC))

    # Act / Assert
    with pytest.raises(CountOfKeysDiffersException, match=r'Active \(1\) \+ pending \(1\)'):
        accounting._get_cl_validators_balance(ref_bs)
