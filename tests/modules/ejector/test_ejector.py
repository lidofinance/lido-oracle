from typing import cast
from unittest.mock import Mock, patch

import pytest
from web3.exceptions import ContractCustomError

from src.constants import (
    COMPOUNDING_WITHDRAWAL_PREFIX,
    EFFECTIVE_BALANCE_INCREMENT,
    ETH1_ADDRESS_WITHDRAWAL_PREFIX,
    FAR_FUTURE_EPOCH,
    GWEI_TO_WEI,
    MAX_EFFECTIVE_BALANCE,
    MAX_EFFECTIVE_BALANCE_ELECTRA,
    MAX_SEED_LOOKAHEAD,
    MIN_ACTIVATION_BALANCE,
    MIN_VALIDATOR_WITHDRAWABILITY_DELAY,
)
from src.metrics.prometheus.ejector import (
    EJECTOR_PARTIAL_WITHDRAWAL_GWEI_AMOUNT,
    EJECTOR_VALIDATORS_COUNT_TO_EJECT,
    EJECTOR_WITHDRAWAL_REQUESTS,
)
from src.modules.common.types import ChainConfig, CurrentFrame, ModuleExecuteDelay
from src.modules.oracles.ejector import ejector as ejector_module
from src.modules.oracles.ejector.data_encode import (
    FWR_AMOUNT,
    InvalidWithdrawalRequestsError,
    WithdrawalRequest,
    encode_data,
)
from src.modules.oracles.ejector.ejector import Ejector, logger as ejector_logger
from src.modules.oracles.ejector.types import EjectorProcessingState
from src.providers.consensus.types import (
    BeaconStateView,
)
from src.providers.execution.contracts.exit_bus_oracle import ExitBusOracleContract
from src.services.exit_order_iterator import WeightsNotUpdatedError, WithdrawalStep
from src.services.prediction import RewardsPerEpoch
from src.services.validator_state import InFlightInbound
from src.types import BlockStamp, EpochNumber, Gwei, ReferenceBlockStamp, SlotNumber, Wei
from src.utils.validator_balance import (
    get_predictable_full_inbound_balance,
    get_predictable_inbound_balance,
    get_predictable_inbound_sweep,
)
from src.web3py.extensions.lido_validators import (
    LidoValidator,
    NodeOperatorId,
    StakingModuleId,
)
from src.web3py.types import Web3
from tests.factory.base_oracle import EjectorProcessingStateFactory
from tests.factory.blockstamp import BlockStampFactory, ReferenceBlockStampFactory
from tests.factory.configs import ChainConfigFactory
from tests.factory.no_registry import LidoValidatorFactory, ValidatorStateFactory


def build_extended_validator(**kwargs) -> LidoValidator:
    lido_validator = LidoValidatorFactory.build(**kwargs)
    return LidoValidator(
        index=lido_validator.index,
        balance=lido_validator.balance,
        validator=lido_validator.validator,
        lido_id=lido_validator.lido_id,
        pending_topups=[],
        consolidating_as_source=lido_validator.consolidating_as_source,
        consolidating_as_target=[],
    )


def build_extended_validator_with_balance(balance: float, meb: int = MAX_EFFECTIVE_BALANCE, **kwargs) -> LidoValidator:
    lido_validator = LidoValidatorFactory.build_with_balance(balance, meb, **kwargs)
    return LidoValidator(
        index=lido_validator.index,
        balance=lido_validator.balance,
        validator=lido_validator.validator,
        lido_id=lido_validator.lido_id,
        pending_topups=[],
        consolidating_as_source=lido_validator.consolidating_as_source,
        consolidating_as_target=[],
    )


@pytest.fixture(autouse=True)
def silence_logger() -> None:
    ejector_logger.disabled = True


@pytest.fixture()
def chain_config():
    return cast(ChainConfig, ChainConfigFactory.build())


@pytest.fixture()
def blockstamp() -> BlockStamp:
    return cast(BlockStamp, BlockStampFactory.build())


@pytest.fixture()
def ref_blockstamp() -> ReferenceBlockStamp:
    return cast(ReferenceBlockStamp, ReferenceBlockStampFactory.build())


@pytest.fixture()
def ejector(web3: Web3) -> Ejector:
    web3.lido_contracts.validators_exit_bus_oracle.get_consensus_version = Mock(return_value=1)
    return Ejector(web3)


@pytest.fixture()
def set_consensus(ejector):
    ejector.get_consensus_version = Mock(return_value=3)


@pytest.mark.unit
def test_ejector_execute_module(ejector: Ejector, blockstamp: BlockStamp) -> None:
    ejector.get_blockstamp_for_report = Mock(return_value=None)
    assert ejector.execute_module(last_finalized_blockstamp=blockstamp) is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH, (
        "execute_module should wait for the next finalized epoch"
    )
    ejector.get_blockstamp_for_report.assert_called_once_with(blockstamp)

    ejector.get_blockstamp_for_report = Mock(return_value=blockstamp)
    ejector.process_report = Mock(return_value=None)
    ejector._check_compatibility = Mock(return_value=True)
    assert ejector.execute_module(last_finalized_blockstamp=blockstamp) is ModuleExecuteDelay.NEXT_SLOT, (
        "execute_module should wait for the next slot"
    )
    ejector.get_blockstamp_for_report.assert_called_once_with(blockstamp)
    ejector.process_report.assert_called_once_with(blockstamp)


@pytest.mark.unit
def test_execute_module__weights_not_updated__returns_next_finalized_epoch(
    ejector: Ejector, blockstamp: BlockStamp
) -> None:
    ejector.get_blockstamp_for_report = Mock(return_value=blockstamp)
    ejector._check_compatibility = Mock(return_value=True)
    ejector.process_report = Mock(side_effect=WeightsNotUpdatedError("Fake exception"))

    result = ejector.execute_module(last_finalized_blockstamp=blockstamp)

    assert result is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH, "execute_module should wait for the next finalized epoch"
    ejector.process_report.assert_called_once_with(blockstamp)


@pytest.mark.unit
def test_ejector_execute_module_on_pause(ejector: Ejector, blockstamp: BlockStamp) -> None:
    ejector.report_contract.abi = ExitBusOracleContract.load_abi(ExitBusOracleContract.abi_path)
    ejector.w3.lido_contracts.validators_exit_bus_oracle.get_contract_version = Mock(
        return_value=ejector.COMPATIBLE_CONTRACT_VERSION
    )
    ejector.w3.lido_contracts.validators_exit_bus_oracle.get_consensus_version = Mock(
        return_value=ejector.COMPATIBLE_CONSENSUS_VERSION
    )
    ejector.get_blockstamp_for_report = Mock(return_value=blockstamp)
    ejector.build_report = Mock(return_value=(1, 294271, 0, b''))
    ejector.w3.lido_contracts.validators_exit_bus_oracle.is_paused = Mock(return_value=True)

    result = ejector.execute_module(last_finalized_blockstamp=blockstamp)

    assert result is ModuleExecuteDelay.NEXT_SLOT, "execute_module should wait for the next slot"
    # Compatibility check reads versions both at the report block and at the chain head
    vebo = ejector.w3.lido_contracts.validators_exit_bus_oracle
    vebo.get_contract_version.assert_any_call(blockstamp.block_hash)
    vebo.get_contract_version.assert_any_call('latest')
    vebo.get_consensus_version.assert_any_call(blockstamp.block_hash)
    vebo.get_consensus_version.assert_any_call('latest')
    # Pause state is intentionally checked at the chain head
    vebo.is_paused.assert_called_once_with('latest')


@pytest.mark.unit
def test_ejector_build_report(ejector: Ejector, ref_blockstamp: ReferenceBlockStamp) -> None:
    ejector.get_withdrawal_requests = Mock(return_value=[])
    ejector.w3.lido_contracts.validators_exit_bus_oracle.get_last_processing_ref_slot.return_value = SlotNumber(0)
    ejector.w3.lido_contracts.validators_exit_bus_oracle.get_max_requests_per_report.return_value = 400

    _, ref_slot, _, data = ejector.build_report(ref_blockstamp)
    ejector.build_report(ref_blockstamp)

    assert ref_slot == ref_blockstamp.ref_slot, "Unexpected blockstamp.ref_slot"
    assert data == b"", "Unexpected encoded data"
    ejector.get_withdrawal_requests.assert_called_once_with(ref_blockstamp)


@pytest.mark.unit
def test_ejector_build_report_keeps_iterator_order(ejector: Ejector, ref_blockstamp: ReferenceBlockStamp) -> None:
    requests = [
        WithdrawalRequest(StakingModuleId(3), NodeOperatorId(1), 10, FWR_AMOUNT),
        WithdrawalRequest(StakingModuleId(1), NodeOperatorId(7), 5, Gwei(32 * 10**9)),
    ]
    ejector.get_withdrawal_requests = Mock(return_value=requests)
    ejector.w3.lido_contracts.validators_exit_bus_oracle.get_last_processing_ref_slot.return_value = SlotNumber(0)
    ejector.w3.lido_contracts.validators_exit_bus_oracle.get_max_requests_per_report.return_value = 400

    _, _, requests_count, data = ejector.build_report(ref_blockstamp)

    assert requests_count == 2
    assert data == encode_data(requests, 400), "Records must keep the iterator order"


@pytest.mark.unit
def test_build_report__mixed_requests__metrics_by_type(ejector: Ejector, ref_blockstamp: ReferenceBlockStamp) -> None:
    # Arrange: one FWR and two PWRs of 32 and 10 ETH
    ejector.get_withdrawal_requests = Mock(
        return_value=[
            WithdrawalRequest(StakingModuleId(1), NodeOperatorId(1), 1, FWR_AMOUNT),
            WithdrawalRequest(StakingModuleId(1), NodeOperatorId(1), 2, Gwei(32 * 10**9)),
            WithdrawalRequest(StakingModuleId(1), NodeOperatorId(2), 3, Gwei(10 * 10**9)),
        ]
    )
    vebo = ejector.w3.lido_contracts.validators_exit_bus_oracle
    vebo.get_last_processing_ref_slot.return_value = SlotNumber(0)
    vebo.get_max_requests_per_report.return_value = 400

    # Act
    ejector.build_report(ref_blockstamp)

    # Assert
    assert EJECTOR_VALIDATORS_COUNT_TO_EJECT._value.get() == 3
    assert EJECTOR_WITHDRAWAL_REQUESTS.labels(type='full')._value.get() == 1
    assert EJECTOR_WITHDRAWAL_REQUESTS.labels(type='partial')._value.get() == 2
    assert EJECTOR_PARTIAL_WITHDRAWAL_GWEI_AMOUNT._value.get() == 42 * 10**9


@pytest.mark.unit
def test_build_report__more_requests_than_wo_limit__raises(
    ejector: Ejector, ref_blockstamp: ReferenceBlockStamp
) -> None:
    # Arrange: the WO accepts one record, the iterator returned two.
    ejector.get_withdrawal_requests = Mock(
        return_value=[
            WithdrawalRequest(StakingModuleId(1), NodeOperatorId(1), 1, FWR_AMOUNT),
            WithdrawalRequest(StakingModuleId(1), NodeOperatorId(1), 2, FWR_AMOUNT),
        ]
    )
    vebo = ejector.w3.lido_contracts.validators_exit_bus_oracle
    vebo.get_last_processing_ref_slot.return_value = SlotNumber(0)
    vebo.get_max_requests_per_report.return_value = 1

    # Act / Assert
    with pytest.raises(InvalidWithdrawalRequestsError, match='Too many requests in report: 2 > 1'):
        ejector.build_report(ref_blockstamp)
    vebo.get_max_requests_per_report.assert_called_once_with(ref_blockstamp.block_hash)


def fwr_request(gid, validator: LidoValidator) -> WithdrawalRequest:
    return WithdrawalRequest(gid[0], gid[1], validator.lido_id.index, FWR_AMOUNT)


def fwr_step(gid, validator: LidoValidator) -> WithdrawalStep:
    return WithdrawalStep(gid, validator, FWR_AMOUNT, get_predictable_inbound_balance(validator))


class SimpleIterator:
    """Stands in for ValidatorExitIterator: yields FWR steps and reports the taken ones in order."""

    def __init__(self, lst, forced=None, rebalancing=None):
        self.lst = lst
        self.forced = forced or []
        self.rebalancing = rebalancing or []
        self.taken: list = []

    def __iter__(self):
        self.iter = iter(self.lst)
        return self

    def __next__(self):
        gid, validator = next(self.iter)
        self.taken.append((gid, validator))
        return fwr_step(gid, validator)

    def allocate_forced_exits(self):
        self.taken.extend(self.forced)
        return [fwr_step(gid, validator) for gid, validator in self.forced]

    def allocate_active_rebalancing(self):
        self.taken.extend(self.rebalancing)
        return [fwr_step(gid, validator) for gid, validator in self.rebalancing]

    def get_requests(self):
        return [fwr_request(gid, validator) for gid, validator in self.taken]


class TestGetWithdrawalRequests:
    @pytest.mark.unit
    def test_no_validators_to_eject(
        self,
        ejector: Ejector,
        ref_blockstamp: ReferenceBlockStamp,
        chain_config: ChainConfig,
        monkeypatch: pytest.MonkeyPatch,
    ):
        ejector.get_chain_config = Mock(return_value=chain_config)
        ejector.w3.lido_contracts.withdrawal_queue_nft.unfinalized_steth = Mock(return_value=100)
        ejector.w3.lido_contracts.validators_exit_bus_oracle.get_contract_version = Mock(return_value=1)

        ejector.prediction_service.get_rewards_per_epoch = Mock(return_value=RewardsPerEpoch(el=Wei(1), cl=Wei(0)))

        ejector._get_lido_effective_balances = Mock(return_value=(Gwei(0), Gwei(0)))
        ejector._get_total_el_balance = Mock(return_value=Wei(50))
        ejector.validators_state_service.get_in_flight_inbound = Mock(return_value=InFlightInbound())
        ejector._get_predicted_withdrawable_epoch = Mock(return_value=ref_blockstamp.ref_epoch + 1)
        ejector._get_deposit_lock_amount = Mock(return_value=Wei(0))

        with monkeypatch.context() as m:
            ejector.get_consensus_version = Mock(return_value=3)
            val_iter = iter(SimpleIterator([]))
            m.setattr(
                ejector_module.ValidatorExitIterator,
                "__iter__",
                Mock(return_value=val_iter),
            )
            result = ejector.get_withdrawal_requests(ref_blockstamp)
            assert result == [], "Unexpected validators to eject"

    @pytest.mark.unit
    def test_simple(
        self,
        ejector: Ejector,
        ref_blockstamp: ReferenceBlockStamp,
        chain_config: ChainConfig,
        monkeypatch: pytest.MonkeyPatch,
    ):
        ejector.get_chain_config = Mock(return_value=chain_config)
        ejector.w3.lido_contracts.withdrawal_queue_nft.unfinalized_steth = Mock(return_value=200)
        ejector.prediction_service.get_rewards_per_epoch = Mock(return_value=RewardsPerEpoch(el=Wei(1), cl=Wei(0)))
        ejector._get_lido_effective_balances = Mock(return_value=(Gwei(0), Gwei(0)))
        ejector._get_total_el_balance = Mock(return_value=Wei(100))
        ejector.validators_state_service.get_in_flight_inbound = Mock(return_value=InFlightInbound())
        ejector._get_predicted_withdrawable_epoch = Mock(return_value=ref_blockstamp.ref_epoch + 50)
        ejector._get_predicted_withdrawable_balance = Mock(return_value=Wei(50))
        ejector._get_deposit_lock_amount = Mock(return_value=Wei(0))

        validators = [
            ((StakingModuleId(0), NodeOperatorId(1)), build_extended_validator()),
            ((StakingModuleId(0), NodeOperatorId(3)), build_extended_validator()),
            ((StakingModuleId(0), NodeOperatorId(5)), build_extended_validator()),
        ]

        with monkeypatch.context() as m:
            ejector.get_consensus_version = Mock(return_value=3)
            val_iter = iter(SimpleIterator(validators[:2]))
            m.setattr(
                ejector_module.ValidatorExitIterator,
                "__iter__",
                Mock(return_value=val_iter),
            )
            result = ejector.get_withdrawal_requests(ref_blockstamp)
            assert result == [fwr_request(*validators[0])], "Unexpected validators to eject"

    @pytest.mark.unit
    def test_get_withdrawal_requests__exact_coverage_after_first_validator__ejects_only_first(
        self,
        ejector: Ejector,
        ref_blockstamp: ReferenceBlockStamp,
        chain_config: ChainConfig,
    ):
        # Arrange
        ejector.get_chain_config = Mock(return_value=chain_config)
        predicted_el_balance = Wei(100)
        ejector._get_predicted_el_balance = Mock(return_value=predicted_el_balance)

        validators = [
            ((StakingModuleId(0), NodeOperatorId(1)), build_extended_validator_with_balance(32)),
            ((StakingModuleId(0), NodeOperatorId(3)), build_extended_validator_with_balance(32)),
        ]
        first_validator_balance_wei = get_predictable_inbound_balance(validators[0][1]) * GWEI_TO_WEI
        ejector.w3.lido_contracts.withdrawal_queue_nft.unfinalized_steth = Mock(
            return_value=predicted_el_balance + first_validator_balance_wei
        )

        val_iter = iter(SimpleIterator(validators))
        with patch.object(ejector_module.ValidatorExitIterator, "__iter__", Mock(return_value=val_iter)):
            # Act
            result = ejector.get_withdrawal_requests(ref_blockstamp)

        # Assert
        assert result == [fwr_request(*validators[0])], "Exact coverage must not eject extra validator"

    @pytest.mark.unit
    def test_get_withdrawal_requests__exact_coverage_after_second_validator__ejects_two(
        self,
        ejector: Ejector,
        ref_blockstamp: ReferenceBlockStamp,
        chain_config: ChainConfig,
    ):
        # Arrange
        ejector.get_chain_config = Mock(return_value=chain_config)
        predicted_el_balance = Wei(100)
        ejector._get_predicted_el_balance = Mock(return_value=predicted_el_balance)

        validators = [
            ((StakingModuleId(0), NodeOperatorId(1)), build_extended_validator_with_balance(32)),
            ((StakingModuleId(0), NodeOperatorId(3)), build_extended_validator_with_balance(32)),
            ((StakingModuleId(0), NodeOperatorId(5)), build_extended_validator_with_balance(32)),
        ]
        first_two_validators_balance_wei = (
            get_predictable_inbound_balance(validators[0][1]) + get_predictable_inbound_balance(validators[1][1])
        ) * GWEI_TO_WEI
        ejector.w3.lido_contracts.withdrawal_queue_nft.unfinalized_steth = Mock(
            return_value=predicted_el_balance + first_two_validators_balance_wei
        )

        val_iter = iter(SimpleIterator(validators))
        with patch.object(ejector_module.ValidatorExitIterator, "__iter__", Mock(return_value=val_iter)):
            # Act
            result = ejector.get_withdrawal_requests(ref_blockstamp)

        # Assert
        assert result == [fwr_request(*validators[0]), fwr_request(*validators[1])], (
            "Exact coverage after second validator must eject exactly two"
        )

    @pytest.mark.unit
    def test_get_withdrawal_requests__dust_balance_shortfall_after_first__ejects_second_to_cover(
        self,
        ejector: Ejector,
        ref_blockstamp: ReferenceBlockStamp,
        chain_config: ChainConfig,
    ):
        # Validators carry non-32-multiple ("dust") balances. When the withdrawal queue misses
        # coverage by a single Wei after the first validator, the loop must eject the whole second
        # validator instead of stopping short. Dust never causes under-ejection.
        # Arrange
        ejector.get_chain_config = Mock(return_value=chain_config)
        predicted_el_balance = Wei(100)
        ejector._get_predicted_el_balance = Mock(return_value=predicted_el_balance)

        validators = [
            (
                (StakingModuleId(0), NodeOperatorId(1)),
                build_extended_validator_with_balance(100_300_000_000, meb=MAX_EFFECTIVE_BALANCE_ELECTRA),  # 100.3 ETH
            ),
            (
                (StakingModuleId(0), NodeOperatorId(3)),
                build_extended_validator_with_balance(63_700_000_000, meb=MAX_EFFECTIVE_BALANCE_ELECTRA),  # 63.7 ETH
            ),
            (
                (StakingModuleId(0), NodeOperatorId(5)),
                build_extended_validator_with_balance(50_500_000_000, meb=MAX_EFFECTIVE_BALANCE_ELECTRA),  # 50.5 ETH
            ),
        ]
        first_validator_balance_wei = get_predictable_inbound_balance(validators[0][1]) * GWEI_TO_WEI
        ejector.w3.lido_contracts.withdrawal_queue_nft.unfinalized_steth = Mock(
            return_value=predicted_el_balance + first_validator_balance_wei + 1
        )

        val_iter = iter(SimpleIterator(validators))
        with patch.object(ejector_module.ValidatorExitIterator, "__iter__", Mock(return_value=val_iter)):
            # Act
            result = ejector.get_withdrawal_requests(ref_blockstamp)

        # Assert
        assert result == [fwr_request(*validators[0]), fwr_request(*validators[1])], (
            "A one-Wei shortfall after the first dusty validator must eject the second, never under-eject"
        )

    @pytest.mark.unit
    def test_get_withdrawal_requests__dust_exact_coverage_after_first__ejects_only_first(
        self,
        ejector: Ejector,
        ref_blockstamp: ReferenceBlockStamp,
        chain_config: ChainConfig,
    ):
        # With a dusty balance the loop must still stop as soon as coverage is reached and not
        # over-eject beyond one validator.
        # Arrange
        ejector.get_chain_config = Mock(return_value=chain_config)
        predicted_el_balance = Wei(100)
        ejector._get_predicted_el_balance = Mock(return_value=predicted_el_balance)

        validators = [
            (
                (StakingModuleId(0), NodeOperatorId(1)),
                build_extended_validator_with_balance(100_300_000_000, meb=MAX_EFFECTIVE_BALANCE_ELECTRA),  # 100.3 ETH
            ),
            (
                (StakingModuleId(0), NodeOperatorId(3)),
                build_extended_validator_with_balance(63_700_000_000, meb=MAX_EFFECTIVE_BALANCE_ELECTRA),  # 63.7 ETH
            ),
        ]
        first_validator_balance_gwei = Gwei(100 * 10**9 + 300_000_000)  # 100.3 ETH
        assert get_predictable_inbound_balance(validators[0][1]) == first_validator_balance_gwei, (
            "dust must be preserved: predictable inbound balance must keep the full 100.3 ETH"
        )
        ejector.w3.lido_contracts.withdrawal_queue_nft.unfinalized_steth = Mock(
            return_value=predicted_el_balance + first_validator_balance_gwei * GWEI_TO_WEI
        )

        val_iter = iter(SimpleIterator(validators))
        with patch.object(ejector_module.ValidatorExitIterator, "__iter__", Mock(return_value=val_iter)):
            # Act
            result = ejector.get_withdrawal_requests(ref_blockstamp)

        # Assert
        assert result == [fwr_request(*validators[0])], (
            "Exact coverage with a dusty balance must not eject an extra validator"
        )

    @pytest.mark.unit
    def test_get_withdrawal_requests__all_phases__concatenated_in_phase_order(
        self,
        ejector: Ejector,
        ref_blockstamp: ReferenceBlockStamp,
        chain_config: ChainConfig,
    ):
        """The request limit lives in the iterator; the ejector only concatenates its output."""
        # Arrange
        ejector.get_chain_config = Mock(return_value=chain_config)
        ejector._get_predicted_el_balance = Mock(return_value=Wei(0))
        ejector.w3.lido_contracts.withdrawal_queue_nft.unfinalized_steth = Mock(return_value=Wei(10**30))

        demand = [((StakingModuleId(0), NodeOperatorId(1)), build_extended_validator()) for _ in range(3)]
        forced = [((StakingModuleId(0), NodeOperatorId(2)), build_extended_validator()) for _ in range(2)]
        rebalancing = [((StakingModuleId(0), NodeOperatorId(3)), build_extended_validator())]
        simple_iterator = SimpleIterator(demand, forced=forced, rebalancing=rebalancing)

        val_iter = iter(simple_iterator)
        with patch.object(ejector_module.ValidatorExitIterator, "__iter__", Mock(return_value=val_iter)):
            # Act
            result = ejector.get_withdrawal_requests(ref_blockstamp)

        # Assert
        assert result == [fwr_request(*pair) for pair in demand + forced + rebalancing], (
            "The ejector must report the iterator output as is"
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("balance", "meb"),
    [
        # Compounding 0x02 validator: 0.3 ETH of dust above the 2048 ETH cap.
        (2_048_300_000_000, MAX_EFFECTIVE_BALANCE_ELECTRA),  # 2048.3 ETH
        # Regular 0x01 validator: 0.3 ETH of dust above the 32 ETH cap.
        (32_300_000_000, MAX_EFFECTIVE_BALANCE),  # 32.3 ETH
    ],
)
def test_predictable_inbound_plus_sweep__dust_validator__equals_full_inbound(balance: int, meb: int) -> None:
    # A balance above the effective-balance cap splits into a capped inbound part and a sweep excess.
    # The two must always reconstruct the full inbound balance, so dust above the cap is never lost
    # or double-counted.
    # Arrange
    validator = build_extended_validator_with_balance(balance, meb=meb)

    # Act
    inbound = get_predictable_inbound_balance(validator)
    sweep = get_predictable_inbound_sweep(validator)
    full = get_predictable_full_inbound_balance(validator)

    # Assert
    assert sweep > 0, "the balance must exceed the cap so the sweep excess is actually exercised"
    assert inbound + sweep == full, "inbound + sweep must equal the full inbound balance"


@pytest.mark.unit
def test_is_main_data_submitted(ejector: Ejector, blockstamp: BlockStamp) -> None:
    ejector.w3.lido_contracts.validators_exit_bus_oracle.get_processing_state = Mock(
        return_value=Mock(data_submitted=True)
    )
    assert ejector.is_main_data_submitted(blockstamp) is True, "Unexpected is_main_data_submitted result"
    ejector.w3.lido_contracts.validators_exit_bus_oracle.get_processing_state.assert_called_once_with(
        blockstamp.block_hash
    )


@pytest.mark.unit
def test_is_contract_reportable(ejector: Ejector, blockstamp: BlockStamp) -> None:
    ejector.is_main_data_submitted = Mock(return_value=False)
    assert ejector.is_contract_reportable(blockstamp) is True, "Unexpected is_contract_reportable result"
    ejector.is_main_data_submitted.assert_called_once_with(blockstamp)


@pytest.mark.unit
class TestPredictedElBalanceSubtractsDepositLock:
    """The deposit lock is subtracted from the estimate exactly once. How large that charge is gets
    decided in `_get_deposit_lock_amount` and pinned by `test_get_deposit_lock_amount__*`."""

    @pytest.fixture(autouse=True)
    def mock_terms(self, ejector: Ejector, chain_config: ChainConfig, ref_blockstamp: ReferenceBlockStamp) -> None:
        ejector.get_chain_config = Mock(return_value=chain_config)
        ejector._get_predicted_withdrawable_epoch = Mock(return_value=EpochNumber(ref_blockstamp.ref_epoch + 10))
        # Distinct powers of ten, so a missing or duplicated term shows up in the total.
        ejector._get_total_el_balance = Mock(return_value=Wei(10**13))
        # 100 gwei in flight is 10**11 wei.
        ejector.validators_state_service.get_in_flight_inbound = Mock(return_value=InFlightInbound(amount=Gwei(100)))
        # The horizon is 10 epochs, so this projects to 10**12 of rewards.
        ejector.prediction_service.get_rewards_per_epoch = Mock(return_value=RewardsPerEpoch(el=Wei(10**11), cl=Wei(0)))
        ejector._get_lido_effective_balances = Mock(return_value=(Gwei(0), Gwei(0)))

    def test_get_predicted_el_balance__deposit_lock_set__subtracted_once(
        self,
        ejector: Ejector,
        ref_blockstamp: ReferenceBlockStamp,
    ) -> None:
        # Arrange
        ejector._get_deposit_lock_amount = Mock(return_value=Wei(2 * 10**10))

        # Act
        result = ejector._get_predicted_el_balance(Gwei(0), ref_blockstamp)

        # Assert
        assert result == Wei(10**13 + 10**12 + 10**11 - 2 * 10**10), (
            "The charged deposit lock must be subtracted from the estimate exactly once"
        )
        ejector._get_deposit_lock_amount.assert_called_once_with(10, ref_blockstamp)

    def test_get_predicted_el_balance__deposit_lock_zero__nothing_subtracted(
        self,
        ejector: Ejector,
        ref_blockstamp: ReferenceBlockStamp,
    ) -> None:
        # Arrange
        ejector._get_deposit_lock_amount = Mock(return_value=Wei(0))

        # Act
        result = ejector._get_predicted_el_balance(Gwei(0), ref_blockstamp)

        # Assert
        assert result == Wei(10**13 + 10**12 + 10**11)


@pytest.mark.unit
class TestPredictionHorizon:
    def test_get_prediction_horizon__queued_and_report_requests__churned_together(
        self, ejector: Ejector, ref_blockstamp: ReferenceBlockStamp
    ) -> None:
        # Arrange
        ejector._get_predicted_withdrawable_epoch = Mock(return_value=EpochNumber(500))
        in_flight = InFlightInbound(queued_churn=Gwei(40), latest_cl_withdrawable_epoch=EpochNumber(300))

        # Act
        result = ejector._get_prediction_horizon(in_flight, Gwei(2), ref_blockstamp)

        # Assert
        assert result == EpochNumber(500)
        ejector._get_predicted_withdrawable_epoch.assert_called_once_with(Gwei(42), ref_blockstamp)

    def test_get_prediction_horizon__cl_partial_arrives_later__extends_horizon(
        self, ejector: Ejector, ref_blockstamp: ReferenceBlockStamp
    ) -> None:
        # Arrange
        ejector._get_predicted_withdrawable_epoch = Mock(return_value=EpochNumber(500))
        in_flight = InFlightInbound(latest_cl_withdrawable_epoch=EpochNumber(900))

        # Act / Assert
        assert ejector._get_prediction_horizon(in_flight, Gwei(0), ref_blockstamp) == EpochNumber(900)

    def test_get_prediction_horizon__nothing_requested__earliest_new_request_arrival(
        self, ejector: Ejector, ref_blockstamp: ReferenceBlockStamp
    ) -> None:
        # Arrange
        ejector._get_predicted_withdrawable_epoch = Mock(return_value=EpochNumber(500))

        # Act / Assert
        assert ejector._get_prediction_horizon(InFlightInbound(), Gwei(0), ref_blockstamp) == EpochNumber(500)
        ejector._get_predicted_withdrawable_epoch.assert_called_once_with(Gwei(0), ref_blockstamp)


@pytest.mark.unit
def test_get_liquid_rewards__part_of_stake_skimmed__cl_rewards_scaled_by_skimmed_share(
    ejector: Ejector, ref_blockstamp: ReferenceBlockStamp, chain_config: ChainConfig
) -> None:
    # Arrange: 40 of 100 ETH of effective balance is skimmed.
    ejector.get_chain_config = Mock(return_value=chain_config)
    ejector.prediction_service.get_rewards_per_epoch = Mock(return_value=RewardsPerEpoch(el=Wei(3), cl=Wei(10)))
    ejector._get_lido_effective_balances = Mock(return_value=(Gwei(100 * 10**9), Gwei(40 * 10**9)))

    # Act
    result = ejector._get_liquid_rewards(5, ref_blockstamp)

    # Assert: EL 3 * 5 = 15, CL 10 * 5 * 40 / 100 = 20.
    assert result == Wei(35)


@pytest.mark.unit
def test_get_liquid_rewards__no_active_lido_stake__el_rewards_only(
    ejector: Ejector, ref_blockstamp: ReferenceBlockStamp, chain_config: ChainConfig
) -> None:
    # Arrange
    ejector.get_chain_config = Mock(return_value=chain_config)
    ejector.prediction_service.get_rewards_per_epoch = Mock(return_value=RewardsPerEpoch(el=Wei(3), cl=Wei(10)))
    ejector._get_lido_effective_balances = Mock(return_value=(Gwei(0), Gwei(0)))

    # Act / Assert
    assert ejector._get_liquid_rewards(5, ref_blockstamp) == Wei(15)


@pytest.mark.unit
def test_get_lido_effective_balances__mixed_credentials__only_capped_validators_skimmed(
    ejector: Ejector, ref_blockstamp: ReferenceBlockStamp
) -> None:
    # Arrange
    eth = 10**9

    def validator(effective_eth: int, prefix: str, exit_epoch: int = FAR_FUTURE_EPOCH) -> LidoValidator:
        return build_extended_validator(
            validator=ValidatorStateFactory.build(
                effective_balance=Gwei(effective_eth * eth),
                withdrawal_credentials=prefix,
                activation_epoch=EpochNumber(0),
                exit_epoch=EpochNumber(exit_epoch),
            )
        )

    ejector.w3.lido_validators.get_active_lido_validators = Mock(
        return_value=[
            validator(32, ETH1_ADDRESS_WITHDRAWAL_PREFIX),  # skimmed
            validator(31, ETH1_ADDRESS_WITHDRAWAL_PREFIX),  # below its cap: rewards restore the balance
            validator(2048, COMPOUNDING_WITHDRAWAL_PREFIX),  # skimmed
            validator(100, COMPOUNDING_WITHDRAWAL_PREFIX),  # compounds
            validator(32, ETH1_ADDRESS_WITHDRAWAL_PREFIX, exit_epoch=ref_blockstamp.ref_epoch),  # not active
        ]
    )

    # Act
    total, skimmed = ejector._get_lido_effective_balances(ref_blockstamp)

    # Assert
    assert total == Gwei((32 + 31 + 2048 + 100) * eth)
    assert skimmed == Gwei((32 + 2048) * eth)


class TestPredictedWithdrawableEpoch:
    @pytest.fixture
    def ref_blockstamp(self) -> ReferenceBlockStamp:
        return ReferenceBlockStampFactory.build(
            slot_number=10_000_000,
            ref_slot=10_000_000,
            ref_epoch=10_000_000 // 32,
        )

    @pytest.fixture(autouse=True)
    def pre_gloas(self, ejector: Ejector, chain_config: ChainConfig) -> None:
        ejector.get_chain_config = Mock(return_value=chain_config)
        ejector.w3.cc.is_gloas_epoch = Mock(return_value=False)

    @pytest.mark.unit
    def test_earliest_exit_epoch_is_old(
        self, ejector: Ejector, set_consensus, ref_blockstamp: ReferenceBlockStamp
    ) -> None:
        ejector._get_total_active_balance = Mock(return_value=int(2048e9))
        ejector.w3.cc.get_state_view = Mock(
            return_value=BeaconStateView(
                slot=ref_blockstamp.slot_number,
                validators=[],
                balances=[],
                earliest_exit_epoch=ref_blockstamp.ref_epoch,
                exit_balance_to_consume=Gwei(0),
                slashings=[],
            )
        )
        result = ejector._get_predicted_withdrawable_epoch(
            Gwei(sum(v.balance for v in [build_extended_validator_with_balance(MIN_ACTIVATION_BALANCE)])),
            ref_blockstamp,
        )
        assert result == ref_blockstamp.ref_epoch + (1 + MAX_SEED_LOOKAHEAD) + MIN_VALIDATOR_WITHDRAWABILITY_DELAY

    @pytest.mark.unit
    def test_exit_fits_exit_balance_to_consume(
        self, ejector: Ejector, set_consensus, ref_blockstamp: ReferenceBlockStamp
    ) -> None:
        ejector._get_total_active_balance = Mock(return_value=int(2048e9))
        ejector.w3.cc.get_state_view = Mock(
            return_value=BeaconStateView(
                slot=ref_blockstamp.slot_number,
                validators=[],
                balances=[],
                earliest_exit_epoch=ref_blockstamp.ref_epoch + 10_000,
                exit_balance_to_consume=Gwei(int(256e9)),
                slashings=[],
            )
        )
        result = ejector._get_predicted_withdrawable_epoch(
            Gwei(
                sum(
                    v.balance for v in [build_extended_validator_with_balance(129e9, meb=MAX_EFFECTIVE_BALANCE_ELECTRA)]
                )
            ),
            ref_blockstamp,
        )
        assert result == ref_blockstamp.ref_epoch + 10_000 + MIN_VALIDATOR_WITHDRAWABILITY_DELAY

    @pytest.mark.unit
    def test_exit_exceeds_balance_to_consume(
        self, ejector: Ejector, set_consensus, ref_blockstamp: ReferenceBlockStamp
    ) -> None:
        ejector._get_total_active_balance = Mock(return_value=2048e9)
        ejector.w3.cc.get_state_view = Mock(
            return_value=BeaconStateView(
                slot=ref_blockstamp.slot_number,
                validators=[],
                balances=[],
                earliest_exit_epoch=ref_blockstamp.ref_epoch + 10_000,
                exit_balance_to_consume=Gwei(1),
                slashings=[],
            )
        )
        result = ejector._get_predicted_withdrawable_epoch(
            Gwei(
                sum(
                    v.balance for v in [build_extended_validator_with_balance(512e9, meb=MAX_EFFECTIVE_BALANCE_ELECTRA)]
                )
            ),
            ref_blockstamp,
        )
        assert result == ref_blockstamp.ref_epoch + 10_000 + 4 + MIN_VALIDATOR_WITHDRAWABILITY_DELAY

    @pytest.mark.unit
    def test_exit_exceeds_churn_limit(
        self, ejector: Ejector, set_consensus, ref_blockstamp: ReferenceBlockStamp
    ) -> None:
        ejector._get_total_active_balance = Mock(return_value=2048e9)
        ejector.w3.cc.get_state_view = Mock(
            return_value=BeaconStateView(
                slot=ref_blockstamp.slot_number,
                validators=[],
                balances=[],
                earliest_exit_epoch=ref_blockstamp.ref_epoch,
                exit_balance_to_consume=Gwei(0),
                slashings=[],
            )
        )
        result = ejector._get_predicted_withdrawable_epoch(
            Gwei(
                sum(
                    v.balance for v in [build_extended_validator_with_balance(512e9, meb=MAX_EFFECTIVE_BALANCE_ELECTRA)]
                )
            ),
            ref_blockstamp,
        )
        assert result == ref_blockstamp.ref_epoch + (1 + MAX_SEED_LOOKAHEAD) + 3 + MIN_VALIDATOR_WITHDRAWABILITY_DELAY

    @pytest.fixture(autouse=True)
    def _patch_ejector(self, ejector: Ejector):
        ejector.w3.cc = Mock()
        ejector.w3.cc.get_config_spec = Mock(return_value=Mock(ELECTRA_FORK_EPOCH=0))


@pytest.mark.unit
def test_get_total_active_validators(ejector: Ejector) -> None:
    ref_blockstamp = ReferenceBlockStampFactory.build(ref_epoch=3546)
    ejector.w3 = Mock()
    ejector.w3.cc.get_validators = Mock(
        return_value=[
            *[LidoValidatorFactory.build_not_active_vals(ref_blockstamp.ref_epoch) for _ in range(150)],
            *[LidoValidatorFactory.build_active_vals(ref_blockstamp.ref_epoch) for _ in range(100)],
            *[LidoValidatorFactory.build_exit_vals(ref_blockstamp.ref_epoch) for _ in range(50)],
        ]
    )

    assert len(ejector._get_active_validators(ref_blockstamp)) == 100


@pytest.mark.unit
def test_get_total_active_balance(ejector: Ejector) -> None:
    ejector._get_active_validators = Mock(return_value=[])
    assert ejector._get_total_active_balance(Mock()) == EFFECTIVE_BALANCE_INCREMENT
    ejector._get_active_validators.assert_called_once()

    ejector._get_active_validators = Mock(
        return_value=[
            LidoValidatorFactory.build_with_balance(Gwei(32 * 10**9)),
            LidoValidatorFactory.build_with_balance(Gwei(33 * 10**9)),
            LidoValidatorFactory.build_with_balance(Gwei(31 * 10**9)),
        ]
    )
    assert ejector._get_total_active_balance(Mock()) == Gwei(95 * 10**9)
    ejector._get_active_validators.assert_called_once()

    ejector._get_active_validators = Mock(
        return_value=[
            LidoValidatorFactory.build_with_balance(Gwei(32 * 10**9)),
            LidoValidatorFactory.build_with_balance(Gwei(31 * 10**9)),
            LidoValidatorFactory.build_with_balance(Gwei(99 * 10**9), meb=MAX_EFFECTIVE_BALANCE_ELECTRA),
        ]
    )
    assert ejector._get_total_active_balance(Mock()) == Gwei(162 * 10**9)
    ejector._get_active_validators.assert_called_once()


@pytest.mark.unit
def test_get_predicted_withdrawable_balance(ejector: Ejector) -> None:
    validator = build_extended_validator_with_balance(Gwei(0))
    result = get_predictable_inbound_balance(validator)
    assert result == 0, "Expected zero"

    validator = build_extended_validator_with_balance(Gwei(42))
    result = get_predictable_inbound_balance(validator)
    assert result == 42, "Expected validator's balance in gwei"

    validator = build_extended_validator_with_balance(Gwei(MAX_EFFECTIVE_BALANCE + 1))
    result = get_predictable_inbound_balance(validator)
    assert result == MAX_EFFECTIVE_BALANCE, "Expect MAX_EFFECTIVE_BALANCE"

    validator = build_extended_validator_with_balance(
        Gwei(MAX_EFFECTIVE_BALANCE + 1),
        meb=MAX_EFFECTIVE_BALANCE_ELECTRA,
    )
    result = get_predictable_inbound_balance(validator)
    assert result == (MAX_EFFECTIVE_BALANCE + 1), "Expect MAX_EFFECTIVE_BALANCE + 1"


@pytest.mark.unit
def test_get_total_balance(ejector: Ejector, blockstamp: BlockStamp) -> None:
    ejector.w3.lido_contracts.get_withdrawal_balance = Mock(return_value=3)
    ejector.w3.lido_contracts.get_el_vault_balance = Mock(return_value=17)
    ejector.w3.lido_contracts.lido.get_withdrawals_reserve = Mock(return_value=1)

    result = ejector._get_total_el_balance(blockstamp)
    assert result == 21, "Unexpected total balance"

    ejector.w3.lido_contracts.get_withdrawal_balance.assert_called_once_with(blockstamp)
    ejector.w3.lido_contracts.get_el_vault_balance.assert_called_once_with(blockstamp)
    ejector.w3.lido_contracts.lido.get_withdrawals_reserve.assert_called_once_with(blockstamp.block_hash)


@pytest.mark.unit
def test_ejector_get_processing_state_no_yet_init_epoch(ejector: Ejector):
    bs = ReferenceBlockStampFactory.build()

    ejector.report_contract.get_processing_state = Mock(side_effect=ContractCustomError('0xcd0883ea', '0xcd0883ea'))
    ejector.get_initial_or_current_frame = Mock(
        return_value=CurrentFrame(ref_slot=100, report_processing_deadline_slot=200)
    )
    processing_state = ejector._get_processing_state(bs)

    assert isinstance(processing_state, EjectorProcessingState)
    assert processing_state.current_frame_ref_slot == 100
    assert processing_state.processing_deadline_time == 200
    assert processing_state.data_submitted is False
    ejector.report_contract.get_processing_state.assert_called_once_with(bs.block_hash)


@pytest.mark.unit
def test_ejector_get_processing_state(ejector: Ejector):
    bs = ReferenceBlockStampFactory.build()
    accounting_processing_state = EjectorProcessingStateFactory.build()
    ejector.report_contract.get_processing_state = Mock(return_value=accounting_processing_state)
    result = ejector._get_processing_state(bs)

    assert accounting_processing_state == result
    ejector.report_contract.get_processing_state.assert_called_once_with(bs.block_hash)


@pytest.mark.unit
def test_is_reporting_allowed__reflects_pause_state(ejector: Ejector, ref_blockstamp: ReferenceBlockStamp) -> None:
    ejector.report_contract.is_paused = Mock(return_value=False)

    result = ejector.is_reporting_allowed(ref_blockstamp)

    assert result is True
    ejector.report_contract.is_paused.assert_called_once_with('latest')

    ejector.report_contract.is_paused = Mock(return_value=True)

    result = ejector.is_reporting_allowed(ref_blockstamp)

    assert result is False
    ejector.report_contract.is_paused.assert_called_once_with('latest')


@pytest.mark.unit
def test_is_contracts_addresses_changed__returns_w3_result(ejector: Ejector) -> None:
    ejector.w3.lido_contracts.has_contract_address_changed = Mock(return_value=True)

    assert ejector.is_contracts_addresses_changed() is True

    ejector.w3.lido_contracts.has_contract_address_changed = Mock(return_value=False)

    assert ejector.is_contracts_addresses_changed() is False


@pytest.mark.unit
def test_refresh_contracts__updates_report_contract_from_w3(ejector: Ejector) -> None:
    new_contract = Mock()
    ejector.w3.lido_contracts.validators_exit_bus_oracle = new_contract

    ejector.refresh_contracts()

    assert ejector.report_contract is new_contract


@pytest.mark.unit
def test_execute_module__compatibility_check_fails__returns_next_finalized_epoch(
    ejector: Ejector, blockstamp: BlockStamp
) -> None:
    ejector.get_blockstamp_for_report = Mock(return_value=blockstamp)
    ejector._check_compatibility = Mock(return_value=False)

    result = ejector.execute_module(last_finalized_blockstamp=blockstamp)

    assert result is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH
    ejector.get_blockstamp_for_report.assert_called_once_with(blockstamp)


@pytest.mark.unit
def test_get_deposit_lock_amount__calculates_frames_ceiling__scales_by_reserve(
    ejector: Ejector, ref_blockstamp: ReferenceBlockStamp
) -> None:
    reserve_per_frame = Wei(10 * GWEI_TO_WEI)
    epochs_per_frame = 10
    ejector.w3.lido_contracts.lido.get_deposits_reserve_target = Mock(return_value=reserve_per_frame)
    ejector.w3.lido_contracts.withdrawal_queue_nft.max_steth_withdrawal_amount = Mock(
        return_value=Wei(1000 * GWEI_TO_WEI)
    )
    ejector.w3.lido_contracts.accounting_oracle.get_consensus_contract = Mock(return_value="0x" + "0" * 40)
    mock_consensus = Mock()
    mock_consensus.get_frame_config.return_value = Mock(epochs_per_frame=epochs_per_frame)
    ejector.w3.eth.contract = Mock(return_value=mock_consensus)

    # Half of the frame reserve is charged, see `test_get_deposit_lock_amount__reserve_locked__charges_half`
    charge_per_frame = reserve_per_frame // 2

    # 0 epochs → 0 // 10 = 0 frames → 0 locked
    assert ejector._get_deposit_lock_amount(0, ref_blockstamp) == Wei(0)
    # Exactly one frame (10 epochs) → 10 // 10 = 1 frame
    assert ejector._get_deposit_lock_amount(10, ref_blockstamp) == Wei(charge_per_frame)
    # One epoch over one frame → 11 // 10 = 1 frame
    assert ejector._get_deposit_lock_amount(11, ref_blockstamp) == Wei(1 * charge_per_frame)
    # 2.5 frames → 25 // 10 = 2 frames
    assert ejector._get_deposit_lock_amount(25, ref_blockstamp) == Wei(2 * charge_per_frame)

    # All on-chain reads must be pinned to the report block, not the chain head
    ejector.w3.lido_contracts.accounting_oracle.get_consensus_contract.assert_called_with(ref_blockstamp.block_hash)
    mock_consensus.get_frame_config.assert_called_with(ref_blockstamp.block_hash)


@pytest.mark.unit
def test_get_deposit_lock_amount__capped_by_max_wr_when_smaller(
    ejector: Ejector, ref_blockstamp: ReferenceBlockStamp
) -> None:
    deposit_per_frame = Wei(100 * GWEI_TO_WEI)
    max_wr_wei = Wei(30 * GWEI_TO_WEI)
    epochs_per_frame = 10
    ejector.w3.lido_contracts.lido.get_deposits_reserve_target = Mock(return_value=deposit_per_frame)
    ejector.w3.lido_contracts.withdrawal_queue_nft.max_steth_withdrawal_amount = Mock(return_value=max_wr_wei)
    ejector.w3.lido_contracts.accounting_oracle.get_consensus_contract = Mock(return_value="0x" + "0" * 40)
    mock_consensus = Mock()
    mock_consensus.get_frame_config.return_value = Mock(epochs_per_frame=epochs_per_frame)
    ejector.w3.eth.contract = Mock(return_value=mock_consensus)

    # reserve_per_frame = min(100, 30) = 30 → max_wr_wei is the binding constraint
    assert ejector._get_deposit_lock_amount(10, ref_blockstamp) == Wei(max_wr_wei // 2)
    assert ejector._get_deposit_lock_amount(25, ref_blockstamp) == Wei(2 * max_wr_wei // 2)

    # All on-chain reads must be pinned to the report block, not the chain head
    ejector.w3.lido_contracts.accounting_oracle.get_consensus_contract.assert_called_with(ref_blockstamp.block_hash)
    mock_consensus.get_frame_config.assert_called_with(ref_blockstamp.block_hash)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("reserve_per_frame", "expected"),
    [
        # Half of the reserve is what we expect deposits to consume in the average case.
        (Wei(400), Wei(200)),
        # An odd reserve must floor to a whole number of wei.
        (Wei(401), Wei(200)),
    ],
)
def test_get_deposit_lock_amount__reserve_locked__charges_half(
    ejector: Ejector, ref_blockstamp: ReferenceBlockStamp, reserve_per_frame: Wei, expected: Wei
) -> None:
    epochs_per_frame = 10
    ejector.w3.lido_contracts.lido.get_deposits_reserve_target = Mock(return_value=reserve_per_frame)
    ejector.w3.lido_contracts.withdrawal_queue_nft.max_steth_withdrawal_amount = Mock(
        return_value=Wei(1000 * GWEI_TO_WEI)
    )
    ejector.w3.lido_contracts.accounting_oracle.get_consensus_contract = Mock(return_value="0x" + "0" * 40)
    mock_consensus = Mock()
    mock_consensus.get_frame_config.return_value = Mock(epochs_per_frame=epochs_per_frame)
    ejector.w3.eth.contract = Mock(return_value=mock_consensus)

    result = ejector._get_deposit_lock_amount(epochs_per_frame, ref_blockstamp)

    assert result == expected
    assert isinstance(result, int)


def forced_iterator(forced_vals) -> SimpleIterator:
    """Iterator that yields no regular validators but returns forced validators on demand."""
    return iter(SimpleIterator([], forced=forced_vals))


@pytest.mark.unit
def test_get_withdrawal_requests__forced_validators_present__included_in_result(
    ejector: Ejector,
    ref_blockstamp: ReferenceBlockStamp,
    chain_config: ChainConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ejector.get_chain_config = Mock(return_value=chain_config)
    ejector.w3.lido_contracts.withdrawal_queue_nft.unfinalized_steth = Mock(return_value=Wei(1000))
    ejector.prediction_service.get_rewards_per_epoch = Mock(return_value=RewardsPerEpoch(el=Wei(0), cl=Wei(0)))
    ejector._get_lido_effective_balances = Mock(return_value=(Gwei(0), Gwei(0)))
    ejector._get_total_el_balance = Mock(return_value=Wei(0))
    ejector.validators_state_service.get_in_flight_inbound = Mock(return_value=InFlightInbound())
    ejector._get_predicted_withdrawable_epoch = Mock(return_value=ref_blockstamp.ref_epoch)
    ejector._get_deposit_lock_amount = Mock(return_value=Wei(0))

    forced_gid = (StakingModuleId(1), NodeOperatorId(1))
    forced_validator = build_extended_validator()
    forced_iter = forced_iterator([(forced_gid, forced_validator)])

    with monkeypatch.context() as m:
        m.setattr(
            ejector_module.ValidatorExitIterator,
            "__iter__",
            Mock(return_value=forced_iter),
        )

        result = ejector.get_withdrawal_requests(ref_blockstamp)

    assert len(result) == 1, "Forced validator should be included even when no regular ejections are needed"
    assert result[0] == fwr_request(forced_gid, forced_validator)


@pytest.mark.unit
def test_get_withdrawal_requests__forced_validators_present__included_without_wr_pressure(
    ejector: Ejector,
    ref_blockstamp: ReferenceBlockStamp,
    chain_config: ChainConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ejector.get_chain_config = Mock(return_value=chain_config)
    ejector.w3.lido_contracts.withdrawal_queue_nft.unfinalized_steth = Mock(return_value=Wei(0))
    ejector.prediction_service.get_rewards_per_epoch = Mock(return_value=RewardsPerEpoch(el=Wei(0), cl=Wei(0)))
    ejector._get_lido_effective_balances = Mock(return_value=(Gwei(0), Gwei(0)))
    ejector._get_total_el_balance = Mock(return_value=Wei(0))
    ejector.validators_state_service.get_in_flight_inbound = Mock(return_value=InFlightInbound())
    ejector._get_predicted_withdrawable_epoch = Mock(return_value=ref_blockstamp.ref_epoch)
    ejector._get_deposit_lock_amount = Mock(return_value=Wei(0))

    forced_gid = (StakingModuleId(1), NodeOperatorId(1))
    forced_validator = build_extended_validator()
    forced_iter = forced_iterator([(forced_gid, forced_validator)])

    with monkeypatch.context() as m:
        m.setattr(
            ejector_module.ValidatorExitIterator,
            "__iter__",
            Mock(return_value=forced_iter),
        )

        result = ejector.get_withdrawal_requests(ref_blockstamp)

    assert len(result) == 1, "Forced validator should be included when withdrawal queue pressure is absent"
    assert result[0] == fwr_request(forced_gid, forced_validator)


@pytest.mark.unit
def test_get_withdrawal_requests__no_wq_pressure__no_validator_ejections(
    ejector: Ejector,
    ref_blockstamp: ReferenceBlockStamp,
    chain_config: ChainConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ejector.get_chain_config = Mock(return_value=chain_config)
    ejector.w3.lido_contracts.withdrawal_queue_nft.unfinalized_steth = Mock(return_value=Wei(0))
    ejector.prediction_service.get_rewards_per_epoch = Mock(return_value=RewardsPerEpoch(el=Wei(0), cl=Wei(0)))
    ejector._get_lido_effective_balances = Mock(return_value=(Gwei(0), Gwei(0)))
    ejector._get_total_el_balance = Mock(return_value=Wei(0))
    ejector.validators_state_service.get_in_flight_inbound = Mock(return_value=InFlightInbound())
    ejector._get_predicted_withdrawable_epoch = Mock(return_value=ref_blockstamp.ref_epoch)
    ejector._get_deposit_lock_amount = Mock(return_value=Wei(1000 * 10**18))

    v_gid = (StakingModuleId(1), NodeOperatorId(1))
    v = build_extended_validator()
    simple_it = iter(SimpleIterator([(v_gid, v)]))

    with monkeypatch.context() as m:
        m.setattr(
            ejector_module.ValidatorExitIterator,
            "__iter__",
            Mock(return_value=simple_it),
        )

        result = ejector.get_withdrawal_requests(ref_blockstamp)

    assert len(result) == 0, "No WQ pressure we need to exit only forced validators"
