from typing import cast
from unittest.mock import Mock

import pytest
from web3.exceptions import ContractCustomError

from src.providers.execution.contracts.exit_bus_oracle import ExitBusOracleContract
from src.constants import (
    EFFECTIVE_BALANCE_INCREMENT,
    GWEI_TO_WEI,
    MAX_EFFECTIVE_BALANCE,
    MAX_EFFECTIVE_BALANCE_ELECTRA,
    MAX_SEED_LOOKAHEAD,
    MIN_ACTIVATION_BALANCE,
    MIN_VALIDATOR_WITHDRAWABILITY_DELAY,
)
from src.modules.ejector import ejector as ejector_module
from src.modules.ejector.ejector import Ejector, logger as ejector_logger
from src.modules.ejector.types import EjectorProcessingState
from src.modules.submodules.oracle_module import ModuleExecuteDelay
from src.modules.submodules.types import ChainConfig, CurrentFrame
from src.providers.consensus.types import (
    BeaconStateView,
)
from src.types import BlockStamp, Gwei, ReferenceBlockStamp, SlotNumber
from src.web3py.extensions.lido_validators import NodeOperatorId, StakingModuleId
from src.web3py.types import Web3
from tests.factory.base_oracle import EjectorProcessingStateFactory
from tests.factory.blockstamp import BlockStampFactory, ReferenceBlockStampFactory
from tests.factory.configs import ChainConfigFactory
from tests.factory.no_registry import LidoValidatorFactory


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
    assert (
        ejector.execute_module(last_finalized_blockstamp=blockstamp) is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH
    ), "execute_module should wait for the next finalized epoch"
    ejector.get_blockstamp_for_report.assert_called_once_with(blockstamp)

    ejector.get_blockstamp_for_report = Mock(return_value=blockstamp)
    ejector.process_report = Mock(return_value=None)
    ejector._check_compatability = Mock(return_value=True)
    assert (
        ejector.execute_module(last_finalized_blockstamp=blockstamp) is ModuleExecuteDelay.NEXT_SLOT
    ), "execute_module should wait for the next slot"
    ejector.get_blockstamp_for_report.assert_called_once_with(blockstamp)
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
    ejector.build_report = Mock(return_value=(1, 294271, 0, 1, b''))
    ejector.w3.lido_contracts.validators_exit_bus_oracle.is_paused = Mock(return_value=True)

    result = ejector.execute_module(last_finalized_blockstamp=blockstamp)

    assert result is ModuleExecuteDelay.NEXT_SLOT, "execute_module should wait for the next slot"


@pytest.mark.unit
def test_ejector_build_report(ejector: Ejector, ref_blockstamp: ReferenceBlockStamp) -> None:
    ejector.get_validators_to_eject = Mock(return_value=[])
    ejector.w3.lido_contracts.validators_exit_bus_oracle.get_last_processing_ref_slot.return_value = SlotNumber(0)

    _, ref_slot, _, _, data = ejector.build_report(ref_blockstamp)
    ejector.build_report(ref_blockstamp)

    assert ref_slot == ref_blockstamp.ref_slot, "Unexpected blockstamp.ref_slot"
    assert data == b"", "Unexpected encoded data"
    ejector.get_validators_to_eject.assert_called_once_with(ref_blockstamp)


class SimpleIterator:
    def __init__(self, lst):
        self.lst = lst

    def __iter__(self):
        self.iter = iter(self.lst)
        return self

    def __next__(self):
        return next(self.iter)

    def get_remaining_forced_validators(self):
        pass


class TestGetValidatorsToEject:
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

        ejector.prediction_service.get_rewards_per_epoch = Mock(return_value=1)
        ejector._get_sweep_delay_in_epochs = Mock(return_value=1)
        ejector._get_total_el_balance = Mock(return_value=50)
        ejector.validators_state_service.get_recently_requested_but_not_exited_validators = Mock(return_value=[])
        ejector._get_predicted_withdrawable_epoch = Mock(return_value=ref_blockstamp.ref_epoch + 1)
        ejector._get_withdrawable_lido_validators_balance = Mock(return_value=10)

        with monkeypatch.context() as m:
            ejector.get_consensus_version = Mock(return_value=3)
            val_iter = iter(SimpleIterator([]))
            val_iter.get_remaining_forced_validators = Mock(return_value=[])
            m.setattr(
                ejector_module.ValidatorExitIterator,
                "__iter__",
                Mock(return_value=val_iter),
            )
            result = ejector.get_validators_to_eject(ref_blockstamp)
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
        ejector.prediction_service.get_rewards_per_epoch = Mock(return_value=1)
        ejector._get_sweep_delay_in_epochs = Mock(return_value=0)
        ejector._get_total_el_balance = Mock(return_value=100)
        ejector.validators_state_service.get_recently_requested_but_not_exited_validators = Mock(return_value=[])

        ejector._get_withdrawable_lido_validators_balance = Mock(return_value=0)
        ejector._get_predicted_withdrawable_epoch = Mock(return_value=ref_blockstamp.ref_epoch + 50)
        ejector._get_predicted_withdrawable_balance = Mock(return_value=50)

        validators = [
            ((StakingModuleId(0), NodeOperatorId(1)), LidoValidatorFactory.build()),
            ((StakingModuleId(0), NodeOperatorId(3)), LidoValidatorFactory.build()),
            ((StakingModuleId(0), NodeOperatorId(5)), LidoValidatorFactory.build()),
        ]

        with monkeypatch.context() as m:
            ejector.get_consensus_version = Mock(return_value=3)
            val_iter = iter(SimpleIterator(validators[:2]))
            val_iter.get_remaining_forced_validators = Mock(return_value=validators[2:])
            m.setattr(
                ejector_module.ValidatorExitIterator,
                "__iter__",
                Mock(return_value=val_iter),
            )
            result = ejector.get_validators_to_eject(ref_blockstamp)
            assert result == [validators[0], *validators[2:]], "Unexpected validators to eject"


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


class TestPredictedWithdrawableEpoch:
    @pytest.fixture
    def ref_blockstamp(self) -> ReferenceBlockStamp:
        return ReferenceBlockStampFactory.build(
            ref_slot=10_000_000,
            ref_epoch=10_000_000 // 32,
        )

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
            ref_blockstamp,
            [LidoValidatorFactory.build_with_balance(MIN_ACTIVATION_BALANCE)] * 1,
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
            ref_blockstamp,
            [LidoValidatorFactory.build_with_balance(129e9, meb=MAX_EFFECTIVE_BALANCE_ELECTRA)] * 1,
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
            ref_blockstamp,
            [LidoValidatorFactory.build_with_balance(512e9, meb=MAX_EFFECTIVE_BALANCE_ELECTRA)] * 1,
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
            ref_blockstamp,
            [LidoValidatorFactory.build_with_balance(512e9, meb=MAX_EFFECTIVE_BALANCE_ELECTRA)] * 1,
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
def test_get_withdrawable_lido_validators_balance(
    ejector: Ejector,
    ref_blockstamp: ReferenceBlockStamp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ejector.w3.lido_validators.get_lido_validators = Mock(
        return_value=[
            LidoValidatorFactory.build(balance="0"),
            LidoValidatorFactory.build(balance="0"),
            LidoValidatorFactory.build(balance="31"),
            LidoValidatorFactory.build(balance="42"),
        ]
    )

    with monkeypatch.context() as m:
        m.setattr(
            ejector_module,
            "is_fully_withdrawable_validator",
            Mock(side_effect=lambda _1, b, _2: b > 32),
        )

        result = ejector._get_withdrawable_lido_validators_balance(42, ref_blockstamp)
        assert result == 42 * GWEI_TO_WEI, "Unexpected withdrawable amount"

        ejector._get_withdrawable_lido_validators_balance(42, ref_blockstamp)
        ejector.w3.lido_validators.get_lido_validators.assert_called_once()


@pytest.mark.unit
def test_get_predicted_withdrawable_balance(ejector: Ejector) -> None:
    validator = LidoValidatorFactory.build_with_balance(Gwei(0))
    result = ejector._get_predicted_withdrawable_balance(validator)
    assert result == 0, "Expected zero"

    validator = LidoValidatorFactory.build_with_balance(Gwei(42))
    result = ejector._get_predicted_withdrawable_balance(validator)
    assert result == 42 * GWEI_TO_WEI, "Expected validator's balance in gwei"

    validator = LidoValidatorFactory.build_with_balance(Gwei(MAX_EFFECTIVE_BALANCE + 1))
    result = ejector._get_predicted_withdrawable_balance(validator)
    assert result == MAX_EFFECTIVE_BALANCE * GWEI_TO_WEI, "Expect MAX_EFFECTIVE_BALANCE"

    validator = LidoValidatorFactory.build_with_balance(
        Gwei(MAX_EFFECTIVE_BALANCE + 1),
        meb=MAX_EFFECTIVE_BALANCE_ELECTRA,
    )
    result = ejector._get_predicted_withdrawable_balance(validator)
    assert result == (MAX_EFFECTIVE_BALANCE + 1) * GWEI_TO_WEI, "Expect MAX_EFFECTIVE_BALANCE + 1"


@pytest.mark.unit
def test_get_total_balance(ejector: Ejector, blockstamp: BlockStamp) -> None:
    ejector.w3.lido_contracts.get_withdrawal_balance = Mock(return_value=3)
    ejector.w3.lido_contracts.get_el_vault_balance = Mock(return_value=17)
    ejector.w3.lido_contracts.lido.get_buffered_ether = Mock(return_value=1)

    result = ejector._get_total_el_balance(blockstamp)
    assert result == 21, "Unexpected total balance"

    ejector.w3.lido_contracts.get_withdrawal_balance.assert_called_once_with(blockstamp)
    ejector.w3.lido_contracts.get_el_vault_balance.assert_called_once_with(blockstamp)
    ejector.w3.lido_contracts.lido.get_buffered_ether.assert_called_once_with(blockstamp.block_hash)


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


@pytest.mark.unit
def test_ejector_get_processing_state(ejector: Ejector):
    bs = ReferenceBlockStampFactory.build()
    accounting_processing_state = EjectorProcessingStateFactory.build()
    ejector.report_contract.get_processing_state = Mock(return_value=accounting_processing_state)
    result = ejector._get_processing_state(bs)

    assert accounting_processing_state == result
