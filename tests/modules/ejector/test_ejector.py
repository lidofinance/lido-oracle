from typing import Iterable, cast
from unittest.mock import Mock

import pytest

from src.constants import MAX_EFFECTIVE_BALANCE
from src.modules.ejector import ejector as ejector_module
from src.modules.ejector.ejector import Ejector
from src.modules.ejector.ejector import logger as ejector_logger
from src.modules.ejector.types import EjectorProcessingState
from src.modules.submodules.oracle_module import ModuleExecuteDelay
from src.modules.submodules.types import ChainConfig
from src.types import BlockStamp, ReferenceBlockStamp
from src.web3py.extensions.contracts import LidoContracts
from src.web3py.extensions.lido_validators import NodeOperatorId, StakingModuleId
from src.web3py.types import Web3
from tests.factory.blockstamp import BlockStampFactory, ReferenceBlockStampFactory
from tests.factory.configs import ChainConfigFactory
from tests.factory.no_registry import LidoValidatorFactory
from tests.modules.accounting.test_safe_border_unit import FAR_FUTURE_EPOCH


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
def ejector(web3: Web3, contracts: LidoContracts) -> Ejector:
    return Ejector(web3)


@pytest.mark.unit
def test_ejector_execute_module(ejector: Ejector, blockstamp: BlockStamp) -> None:
    ejector.get_blockstamp_for_report = Mock(return_value=None)
    assert (
        ejector.execute_module(last_finalized_blockstamp=blockstamp) is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH
    ), "execute_module should wait for the next finalized epoch"
    ejector.get_blockstamp_for_report.assert_called_once_with(blockstamp)

    ejector.get_blockstamp_for_report = Mock(return_value=blockstamp)
    ejector.process_report = Mock(return_value=None)
    assert (
        ejector.execute_module(last_finalized_blockstamp=blockstamp) is ModuleExecuteDelay.NEXT_SLOT
    ), "execute_module should wait for the next slot"
    ejector.get_blockstamp_for_report.assert_called_once_with(blockstamp)
    ejector.process_report.assert_called_once_with(blockstamp)


@pytest.mark.unit
def test_ejector_execute_module_on_pause(ejector: Ejector, blockstamp: BlockStamp) -> None:
    ejector.get_blockstamp_for_report = Mock(return_value=blockstamp)
    ejector.build_report = Mock(return_value=(1, 294271, 0, 1, b''))
    ejector.w3.lido_contracts.validators_exit_bus_oracle.is_paused = Mock(return_value=True)
    assert (
        ejector.execute_module(last_finalized_blockstamp=blockstamp) is ModuleExecuteDelay.NEXT_SLOT
    ), "execute_module should wait for the next slot"


@pytest.mark.unit
def test_ejector_build_report(ejector: Ejector, ref_blockstamp: ReferenceBlockStamp) -> None:
    ejector.get_validators_to_eject = Mock(return_value=[])
    result = ejector.build_report(ref_blockstamp)
    _, ref_slot, _, _, data = result
    assert ref_slot == ref_blockstamp.ref_slot, "Unexpected blockstamp.ref_slot"
    assert data == b"", "Unexpected encoded data"

    ejector.build_report(ref_blockstamp)
    ejector.get_validators_to_eject.assert_called_once_with(ref_blockstamp)


class TestGetValidatorsToEject:
    @pytest.mark.unit
    def test_should_not_report_on_no_withdraw_requests(
        self,
        ejector: Ejector,
        ref_blockstamp: ReferenceBlockStamp,
    ) -> None:
        ejector.w3.lido_contracts.withdrawal_queue_nft.unfinalized_steth = Mock(return_value=0)
        result = ejector.get_validators_to_eject(ref_blockstamp)
        assert result == [], "Should not report on no withdraw requests"

    @pytest.mark.unit
    @pytest.mark.usefixtures("consensus_client")
    def test_no_validators_to_eject(
        self,
        ejector: Ejector,
        ref_blockstamp: ReferenceBlockStamp,
        chain_config: ChainConfig,
        monkeypatch: pytest.MonkeyPatch,
    ):
        ejector.get_chain_config = Mock(return_value=chain_config)
        ejector.w3.lido_contracts.withdrawal_queue_nft.unfinalized_steth = Mock(return_value=100)

        ejector.prediction_service.get_rewards_per_epoch = Mock(return_value=1)
        ejector._get_sweep_delay_in_epochs = Mock(return_value=1)
        ejector._get_total_el_balance = Mock(return_value=50)
        ejector.validators_state_service.get_recently_requested_but_not_exited_validators = Mock(return_value=[])

        with monkeypatch.context() as m:
            m.setattr(
                ejector_module.ExitOrderIterator,
                "__iter__",
                Mock(return_value=iter([])),
            )
            result = ejector.get_validators_to_eject(ref_blockstamp)
            assert result == [], "Unexpected validators to eject"

    @pytest.mark.unit
    @pytest.mark.usefixtures("consensus_client")
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
        ejector._get_sweep_delay_in_epochs = Mock(return_value=ref_blockstamp.ref_epoch)
        ejector._get_total_el_balance = Mock(return_value=100)
        ejector.validators_state_service.get_recently_requested_but_not_exited_validators = Mock(return_value=[])

        ejector._get_withdrawable_lido_validators_balance = Mock(return_value=0)
        ejector._get_predicted_withdrawable_epoch = Mock(return_value=50)
        ejector._get_predicted_withdrawable_balance = Mock(return_value=50)

        validators = [
            ((StakingModuleId(0), NodeOperatorId(1)), LidoValidatorFactory.build()),
            ((StakingModuleId(0), NodeOperatorId(3)), LidoValidatorFactory.build()),
            ((StakingModuleId(0), NodeOperatorId(5)), LidoValidatorFactory.build()),
        ]

        with monkeypatch.context() as m:
            m.setattr(
                ejector_module.ExitOrderIterator,
                "__iter__",
                Mock(return_value=iter(validators)),
            )
            result = ejector.get_validators_to_eject(ref_blockstamp)
            assert result == [validators[0]], "Unexpected validators to eject"


@pytest.mark.unit
@pytest.mark.usefixtures("contracts")
def test_get_unfinalized_steth(ejector: Ejector, blockstamp: BlockStamp) -> None:
    result = ejector.w3.lido_contracts.withdrawal_queue_nft.unfinalized_steth(blockstamp.block_hash)
    assert result == 8362187000000000000, "Unexpected unfinalized stETH"


@pytest.mark.unit
def test_compute_activation_exit_epoch(
    ejector: Ejector,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with monkeypatch.context() as m:
        m.setattr(ejector_module, "MAX_SEED_LOOKAHEAD", 17)
        ref_blockstamp = ReferenceBlockStampFactory.build(ref_epoch=3546)
        result = ejector.compute_activation_exit_epoch(ref_blockstamp)
        assert result == 3546 + 17 + 1, "Unexpected activation exit epoch"


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
def test_get_predicted_withdrawable_epoch(ejector: Ejector) -> None:
    ejector._get_latest_exit_epoch = Mock(return_value=[1, 32])
    ejector._get_churn_limit = Mock(return_value=2)
    ref_blockstamp = ReferenceBlockStampFactory.build(ref_epoch=3546)
    result = ejector._get_predicted_withdrawable_epoch(ref_blockstamp, 2)
    assert result == 3808, "Unexpected predicted withdrawable epoch"

    result = ejector._get_predicted_withdrawable_epoch(ref_blockstamp, 4)
    assert result == 3809, "Unexpected predicted withdrawable epoch"


@pytest.mark.unit
@pytest.mark.usefixtures("consensus_client", "lido_validators")
def test_get_withdrawable_lido_validators(
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
            Mock(side_effect=lambda v, _: int(v.balance) > 32),
        )

        result = ejector._get_withdrawable_lido_validators_balance(ref_blockstamp, 42)
        assert result == 42 * 10**9, "Unexpected withdrawable amount"

        ejector._get_withdrawable_lido_validators_balance(ref_blockstamp, 42)
        ejector.w3.lido_validators.get_lido_validators.assert_called_once()


@pytest.mark.unit
def test_get_predicted_withdrawable_balance(ejector: Ejector) -> None:
    validator = LidoValidatorFactory.build(balance="0")
    result = ejector._get_predicted_withdrawable_balance(validator)
    assert result == 0, "Expected zero"

    validator = LidoValidatorFactory.build(balance="42")
    result = ejector._get_predicted_withdrawable_balance(validator)
    assert result == 42 * 10**9, "Expected validator's balance in gwei"

    validator = LidoValidatorFactory.build(balance=str(MAX_EFFECTIVE_BALANCE + 1))
    result = ejector._get_predicted_withdrawable_balance(validator)
    assert result == MAX_EFFECTIVE_BALANCE * 10**9, "Expect MAX_EFFECTIVE_BALANCE"


@pytest.mark.unit
@pytest.mark.usefixtures("consensus_client")
def test_get_sweep_delay_in_epochs(
    ejector: Ejector,
    ref_blockstamp: ReferenceBlockStamp,
    chain_config: ChainConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ejector.w3.cc.get_validators = Mock(return_value=LidoValidatorFactory.batch(1024))
    ejector.get_chain_config = Mock(return_value=chain_config)

    with monkeypatch.context() as m:
        m.setattr(
            ejector_module,
            "is_partially_withdrawable_validator",
            Mock(return_value=False),
        )
        m.setattr(
            ejector_module,
            "is_fully_withdrawable_validator",
            Mock(return_value=False),
        )

        # no validators at all
        result = ejector._get_sweep_delay_in_epochs(ref_blockstamp)
        assert result == 0, "Unexpected sweep delay in epochs"

    with monkeypatch.context() as m:
        m.setattr(
            ejector_module,
            "is_partially_withdrawable_validator",
            Mock(return_value=False),
        )
        m.setattr(
            ejector_module,
            "is_fully_withdrawable_validator",
            Mock(return_value=True),
        )

        # all 1024 validators
        result = ejector._get_sweep_delay_in_epochs(ref_blockstamp)
        assert result == 1, "Unexpected sweep delay in epochs"


@pytest.mark.usefixtures("contracts")
def test_get_total_balance(ejector: Ejector, blockstamp: BlockStamp) -> None:
    ejector.w3.lido_contracts.get_withdrawal_balance = Mock(return_value=3)
    ejector.w3.lido_contracts.get_el_vault_balance = Mock(return_value=17)
    ejector.w3.lido_contracts.lido.get_buffered_ether = Mock(return_value=1)

    result = ejector._get_total_el_balance(blockstamp)
    assert result == 21, "Unexpected total balance"

    ejector.w3.lido_contracts.get_withdrawal_balance.assert_called_once_with(blockstamp)
    ejector.w3.lido_contracts.get_el_vault_balance.assert_called_once_with(blockstamp)
    ejector.w3.lido_contracts.lido.get_buffered_ether.assert_called_once_with(blockstamp.block_hash)


class TestChurnLimit:
    """_get_churn_limit tests"""

    @pytest.fixture(autouse=True)
    def mock_is_active_validator(self, monkeypatch: pytest.MonkeyPatch) -> Iterable:
        with monkeypatch.context() as m:
            m.setattr(
                ejector_module,
                "is_active_validator",
                Mock(side_effect=lambda v, _: bool(v)),
            )
            yield

    @pytest.mark.unit
    @pytest.mark.usefixtures("consensus_client")
    def test_get_churn_limit_no_validators(self, ejector: Ejector, ref_blockstamp: ReferenceBlockStamp) -> None:
        ejector.w3.cc.get_validators = Mock(return_value=[])
        result = ejector._get_churn_limit(ref_blockstamp)
        assert result == ejector_module.MIN_PER_EPOCH_CHURN_LIMIT, "Unexpected churn limit"
        ejector.w3.cc.get_validators.assert_called_once_with(ref_blockstamp)

    @pytest.mark.unit
    @pytest.mark.usefixtures("consensus_client")
    def test_get_churn_limit_validators_less_than_min_churn(
        self,
        ejector: Ejector,
        ref_blockstamp: ReferenceBlockStamp,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with monkeypatch.context() as m:
            ejector.w3.cc.get_validators = Mock(return_value=[1, 1, 0])
            m.setattr(ejector_module, "MIN_PER_EPOCH_CHURN_LIMIT", 4)
            m.setattr(ejector_module, "CHURN_LIMIT_QUOTIENT", 1)
            result = ejector._get_churn_limit(ref_blockstamp)
            assert result == 4, "Unexpected churn limit"
            ejector.w3.cc.get_validators.assert_called_once_with(ref_blockstamp)

    @pytest.mark.unit
    @pytest.mark.usefixtures("consensus_client")
    def test_get_churn_limit_basic(
        self,
        ejector: Ejector,
        ref_blockstamp: ReferenceBlockStamp,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with monkeypatch.context() as m:
            ejector.w3.cc.get_validators = Mock(return_value=[1] * 99)
            m.setattr(ejector_module, "MIN_PER_EPOCH_CHURN_LIMIT", 0)
            m.setattr(ejector_module, "CHURN_LIMIT_QUOTIENT", 2)
            result = ejector._get_churn_limit(ref_blockstamp)
            assert result == 49, "Unexpected churn limit"
            ejector._get_churn_limit(ref_blockstamp)
            ejector.w3.cc.get_validators.assert_called_once_with(ref_blockstamp)


@pytest.mark.unit
def test_get_processing_state(ejector: Ejector, blockstamp: BlockStamp) -> None:
    result = ejector.w3.lido_contracts.validators_exit_bus_oracle.get_processing_state(blockstamp.block_hash)
    assert isinstance(result, EjectorProcessingState), "Unexpected processing state response"


@pytest.mark.unit
@pytest.mark.usefixtures("consensus_client")
def test_get_latest_exit_epoch(ejector: Ejector, blockstamp: BlockStamp) -> None:
    ejector.w3.cc.get_validators = Mock(
        return_value=[
            Mock(validator=Mock(exit_epoch=FAR_FUTURE_EPOCH)),
            Mock(validator=Mock(exit_epoch=42)),
            Mock(validator=Mock(exit_epoch=42)),
            Mock(validator=Mock(exit_epoch=1)),
        ]
    )

    (max_epoch, count) = ejector._get_latest_exit_epoch(blockstamp)
    assert count == 2, "Unexpected count of exiting validators"
    assert max_epoch == 42, "Unexpected max epoch"

    ejector._get_latest_exit_epoch(blockstamp)
    ejector.w3.cc.get_validators.assert_called_once_with(blockstamp)
