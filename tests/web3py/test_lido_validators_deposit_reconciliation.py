"""A deposit the protocol lost must drop out of TVL.

Ether that Lido sent to the deposit contract but can no longer withdraw -- redirected by a node
operator's front run, or discarded outright by the CL -- must not be reported as TVL. The oracle is
what carries that write-off: ``clValidatorsBalance`` and ``clPendingBalance`` are the only CL-side
TVL inputs the contract takes (``ReportSimulationPayload``), and ``depositedValidators`` is not one
of them -- deposits are tracked on-chain by nonce (``BalanceStats``). So a lost key simply falling
out of both the active and the pending set *is* the mechanism by which the loss reaches TVL.

Deposit signatures are produced with real BLS keys and checked by the production verifier
(``src.services.deposit_signature_verification``). Both loss scenarios turn on whether a signature
actually verifies, so mocking the verifier away would make these tests vacuous.

Shared fixture state (see ``lido_protocol``): one staking module, one node operator with
``total_deposited_validators == 3``, and three used keys at indexes 0/1/2 -- a complete, correct
Keys API response, so nothing here is attributable to a KAPI defect:

  * key 0 -- already a validator on the CL       -> *active*
  * key 1 -- valid 32 ETH deposit to Lido WC     -> *pending*
  * key 2 -- the variable under test

Four tests state the write-off requirement and **all four fail on this branch**, deliberately and
without an ``xfail`` marker -- marking them expected-failures would turn the suite green and report
no problem, which is the opposite of what they exist for. They fail for two independent reasons:

1. Three of them are blocked by ``LidoValidatorsProvider._validate_total_validators_count``, which
   requires ``active + pending == depositedValidators`` -- an equality between "ether still owned on
   the CL" and "ether ever sent to the deposit contract", and so a prohibition on the write-off.
   Introduced by the branch under review; these pass unchanged once it stops blocking the report.

2. ``test_report_balances__frontrun_validator_created_on_cl__lost_ether_stays_out_of_tvl`` fails for
   a different and pre-existing reason: which CL validators count as Lido's is decided by pubkey
   alone, with no check that their withdrawal credentials are Lido's, so the write-off silently
   reverses the moment the CL creates the front-run validator. One gap, but it shows up in both
   reported balances. See that test's docstring for the measured figures.
"""

from unittest.mock import Mock

import blst
import pytest
from eth_typing import HexStr
from web3.types import Wei

from src.constants import DOMAIN_DEPOSIT_TYPE, ETH1_ADDRESS_WITHDRAWAL_PREFIX
from src.modules.common.types import ZERO_HASH
from src.modules.oracles.accounting.accounting import Accounting
from src.modules.oracles.accounting.third_phase.types import FormatList
from src.modules.oracles.accounting.types import (
    BeaconStat,
    FinalizationShareRate,
    VaultsTreeCid,
    VaultsTreeRoot,
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


# ---- the write-off must not reverse once the CL creates the validator ---------------------------


@pytest.mark.unit
def test_report_balances__frontrun_validator_created_on_cl__lost_ether_stays_out_of_tvl(lido_protocol, accounting):
    """The front-run write-off currently lasts only while the deposit sits in the CL queue.

    `_collect_valid_pending_deposits` drops a front-run pubkey, but that governs only *new*
    validators: its `filter_pubkeys` is the set of Lido keys not yet on the CL. Once the CL creates
    the validator the pubkey leaves that set, and nothing downstream reinstates the exclusion --
    `compute_lido_validators` decides which CL validators are Lido's **by pubkey alone**, and no
    caller consults `get_lido_wc_list` on the active path (it is checked for pending deposits and in
    `abnormal_cl_rebase`, never for active validators).

    That single gap contaminates both TVL terms, which are each computed correctly over the wrong
    set. Note that summing them is *not* double counting: a `pending_topup` is ether that has left
    the deposit contract but is not yet in `validator.balance`, and the two contributions to
    `clPendingBalance` are disjoint by construction -- `new_validators_pending` comes from keys not
    on the CL, `topups_pending` from keys that are.

      * the validator's own balance lands in `clValidatorsBalance`;
      * Lido's still-queued deposit for that pubkey is reclassified from a new-validator deposit
        into a `pending_topup` and lands in `clPendingBalance`.

    Measured on this branch: `clValidatorsBalance` 64.2 ETH and `clPendingBalance` 64.0 ETH, i.e.
    64.1 ETH attributed to a key only the operator can withdraw from. Excluding the validator from
    the Lido set fixes both terms at once, which is why this test asserts on the reported balances
    rather than prescribing where the check goes.
    """
    # Arrange: the front-run validator now exists on the CL with the operator's own credentials,
    # and Lido's own deposit for the same pubkey is still queued -- now a top-up, not a new deposit.
    lido_protocol.set_cl_validators((_ACTIVE_KEY, _LIDO_WC), (_SUBJECT_KEY, _OPERATOR_WC))
    lido_protocol.set_pending_deposits(
        _deposit(_PENDING_KEY, _LIDO_WC),
        _deposit(_SUBJECT_KEY, _LIDO_WC),
    )

    # Assert: only the honest validator and the honest pending deposit may be reported.
    assert accounting._get_cl_validators_balance(ref_bs) == _VALIDATOR_BALANCE
    assert accounting._get_cl_pending_validators_balance(ref_bs) == _DEPOSIT_AMOUNT


# ---- the two states where a used key is neither active nor pending -----------------------------
#
# In both cases 32 ETH is gone: the operator's front run redirected it, or the CL discarded the
# deposit outright. The oracle's job is to drop that ether out of TVL, and the report is what
# carries the loss -- `clValidatorsBalance` and `clPendingBalance` are the only CL-side TVL inputs
# the contract has (`ReportSimulationPayload`), and `depositedValidators` is not one of them.
#
# These tests state that requirement, and they FAIL on this branch. That is the point: they are
# left red rather than marked xfail, because the check they contradict is still under review and a
# green suite would report no problem at all. `_validate_total_validators_count` demands
# `active + pending == depositedValidators` -- an equality between "ether still owned on the CL"
# and "ether ever sent to the deposit contract" -- and so forbids the write-off. They go green
# once that check stops blocking the report; nothing else about them needs to change.


def _assert_lost_deposit_excluded_from_tvl(accounting: Accounting) -> None:
    """The surviving key's ether is reported; the lost key's 32 ETH appears in neither TVL term."""
    cl_balance = accounting._get_cl_validators_balance(ref_bs)
    cl_pending_balance = accounting._get_cl_pending_validators_balance(ref_bs)

    assert cl_balance == _VALIDATOR_BALANCE, 'only the one active validator contributes'
    assert cl_pending_balance == _DEPOSIT_AMOUNT, 'only the one healthy pending deposit contributes'
    assert cl_balance + cl_pending_balance == _VALIDATOR_BALANCE + _DEPOSIT_AMOUNT
    # The written-off key contributed nothing, i.e. 32 ETH left TVL.
    assert cl_pending_balance != 2 * _DEPOSIT_AMOUNT


@pytest.mark.unit
def test_report_balances__operator_frontran_own_key__lost_deposit_excluded_from_tvl(lido_protocol, accounting):
    """A key owner redirects its own deposit, so that ether must leave TVL.

    The operator signs a deposit for its own pubkey with its own withdrawal credentials and lands
    it ahead of Lido's. Only the holder of the secret key can produce that proof of possession,
    which is why `_collect_valid_pending_deposits` treats it as a front run and drops the pubkey --
    the ether is no longer withdrawable by the protocol, so crediting it would overstate TVL.
    """
    # Arrange
    lido_protocol.set_pending_deposits(
        _deposit(_PENDING_KEY, _LIDO_WC),
        _deposit(_SUBJECT_KEY, _OPERATOR_WC),  # front run, validly signed by the key owner
        _deposit(_SUBJECT_KEY, _LIDO_WC),  # Lido's own deposit, right behind it
    )

    # Act / Assert
    assert _pubkey(_SUBJECT_KEY) not in lido_protocol.web3.lido_validators.get_pending_lido_validators(ref_bs)
    _assert_lost_deposit_excluded_from_tvl(accounting)


@pytest.mark.unit
def test_report_balances__cl_discarded_the_deposit__lost_deposit_excluded_from_tvl(lido_protocol, accounting):
    """The CL can drop a deposit permanently, and TVL has to follow.

    Per Electra `apply_pending_deposit`, a deposit for an unknown pubkey creates a validator only
    if `is_valid_deposit_signature` passes; `process_pending_deposits` pops the entry either way.
    An invalid-signature deposit therefore leaves neither a validator nor a queue entry, while
    Lido's `depositedValidators` was incremented on the EL and never decreases -- so this state is
    permanent, and so is the write-off. Deposit signatures come from node operators and are not
    validated on-chain; the DSM guardians check them off-chain, which makes this a process
    guarantee rather than a protocol one.
    """
    # Arrange: key 2 is used and deposited, but the CL has neither a validator nor a queued deposit.
    lido_protocol.set_pending_deposits(_deposit(_PENDING_KEY, _LIDO_WC))

    # Act / Assert
    _assert_lost_deposit_excluded_from_tvl(accounting)


# ---- the write-off must also survive the report build ------------------------------------------


@pytest.mark.unit
def test_calculate_report__operator_frontran_own_key__report_is_built(lido_protocol, accounting):
    """A written-off deposit must not stop the frame from being reported at all.

    `_calculate_report` reads the CL balance second, so a raise there costs the whole report --
    and because `CountOfKeysDiffersException` is caught by `OracleModule.exception_handler`, the
    daemon does not crash, it just abandons the cycle and retries the same reference slot. For the
    permanent state above that is an indefinite reporting outage visible only in the logs.
    """
    # Arrange: everything `_calculate_report` needs after the two balance terms.
    lido_protocol.set_pending_deposits(
        _deposit(_PENDING_KEY, _LIDO_WC),
        _deposit(_SUBJECT_KEY, _OPERATOR_WC),
        _deposit(_SUBJECT_KEY, _LIDO_WC),
    )
    accounting.get_consensus_version = Mock(return_value=4)
    accounting._get_newly_exited_validators_by_modules = Mock(return_value=([], []))
    accounting._get_balances_by_modules = Mock(return_value=([], []))
    accounting.w3.lido_contracts.get_withdrawal_balance = Mock(return_value=Wei(0))
    accounting.w3.lido_contracts.get_el_vault_balance = Mock(return_value=Wei(0))
    accounting.get_shares_to_burn = Mock(return_value=0)
    accounting._get_finalization_data = Mock(return_value=([], FinalizationShareRate(0)))
    accounting._is_bunker = Mock(return_value=False)
    accounting._handle_vaults_report = Mock(return_value=(VaultsTreeRoot(ZERO_HASH), VaultsTreeCid('')))
    accounting.get_extra_data = Mock(
        return_value=Mock(format=FormatList.EXTRA_DATA_FORMAT_LIST_EMPTY.value, data_hash=ZERO_HASH, items_count=0)
    )

    # Act
    report_data = accounting._calculate_report(ref_bs)

    # Assert: the lost 32 ETH is in neither TVL term of the report that goes on-chain.
    assert report_data.cl_validators_balance_gwei == _VALIDATOR_BALANCE
    assert report_data.cl_pending_balance_gwei == _DEPOSIT_AMOUNT
