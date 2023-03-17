from unittest.mock import Mock

import pytest

from src.modules.accounting import accounting
from src.modules.accounting.accounting import Accounting
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.configs import ChainConfigFactory, FrameConfigFactory
from tests.factory.contract_responses import LidoReportRebaseFactory
from tests.factory.no_registry import StakingModuleFactory, LidoValidatorFactory


@pytest.fixture
def accounting_module(web3, contracts):
    yield Accounting(web3)


@pytest.mark.unit
def test_get_updated_modules_stats(accounting_module):
    staking_modules = [
        StakingModuleFactory.build(exited_validators_count=10),
        StakingModuleFactory.build(exited_validators_count=20),
        StakingModuleFactory.build(exited_validators_count=30),
    ]

    node_operators_stats = {
        (staking_modules[0].id, 0): 10,
        (staking_modules[1].id, 0): 25,
        (staking_modules[2].id, 0): 30,
    }

    module_ids, exited_validators_count_list = accounting_module.get_updated_modules_stats(
        staking_modules,
        node_operators_stats,
    )

    assert len(module_ids) == 1
    assert module_ids[0] == staking_modules[1].id
    assert exited_validators_count_list[0] == 25


@pytest.mark.unit
def test_get_consensus_lido_state(accounting_module, lido_validators):
    bs = ReferenceBlockStampFactory.build()
    validators = LidoValidatorFactory.batch(10)
    accounting_module.w3.lido_validators.get_lido_validators = Mock(return_value=validators)

    count, balance = accounting_module._get_consensus_lido_state(bs)

    assert count == 10
    assert balance == sum((int(val.balance) for val in validators))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("post_total_pooled_ether", "post_total_shares", "expected_share_rate"),
    [
        (15 * 10 ** 18, 15 * 10 ** 18, 1 * 10 ** 27),
        (12 * 10 ** 18, 15 * 10 ** 18, 8 * 10 ** 26),
        (18 * 10 ** 18, 14 * 10 ** 18, 1285714285714285714285714285),
    ]
)
def test_get_finalization_shares_rate(accounting_module, post_total_pooled_ether, post_total_shares, expected_share_rate):
    lido_rebase = LidoReportRebaseFactory.build(
        post_total_pooled_ether=post_total_pooled_ether,
        post_total_shares=post_total_shares,
    )
    accounting_module.simulate_full_rebase = Mock(return_value=lido_rebase)

    bs = ReferenceBlockStampFactory.build()
    share_rate = accounting_module._get_finalization_shares_rate(bs)

    assert share_rate == expected_share_rate

    if post_total_pooled_ether > post_total_shares:
        assert share_rate > 10 ** 27
    else:
        assert share_rate <= 10 ** 27


@pytest.mark.unit
def test_get_slots_elapsed_from_initialize(accounting_module, contracts):
    accounting_module.get_chain_config = Mock(return_value=ChainConfigFactory.build())
    accounting_module.get_frame_config = Mock(return_value=FrameConfigFactory.build(initial_epoch=2, epochs_per_frame=1))

    accounting_module.w3.lido_contracts.get_accounting_last_processing_ref_slot = Mock(return_value=None)

    bs = ReferenceBlockStampFactory.build(ref_slot=100)
    slots_elapsed = accounting_module._get_slots_elapsed_from_last_report(bs)

    assert slots_elapsed == 100 - 32 * 2


@pytest.mark.unit
def test_get_slots_elapsed_from_last_report(accounting_module, contracts):
    accounting_module.get_chain_config = Mock(return_value=ChainConfigFactory.build())
    accounting_module.get_frame_config = Mock(return_value=FrameConfigFactory.build(initial_epoch=2, epochs_per_frame=1))

    accounting_module.w3.lido_contracts.get_accounting_last_processing_ref_slot = Mock(return_value=70)

    bs = ReferenceBlockStampFactory.build(ref_slot=100)
    slots_elapsed = accounting_module._get_slots_elapsed_from_last_report(bs)

    assert slots_elapsed == 100 - 70


class TestAccountingSanityCheck:

    @pytest.fixture
    def bs(self):
        yield ReferenceBlockStampFactory.build()

    def test_env_toggle(self, accounting_module, monkeypatch, bs, caplog):
        accounting_module.bunker_service._get_total_supply = Mock(return_value=100)
        accounting_module.simulate_cl_rebase = Mock(return_value=LidoReportRebaseFactory.build(post_total_pooled_ether=90))
        with monkeypatch.context() as ctx:
            ctx.setattr(accounting, 'ALLOW_NEGATIVE_REBASE_REPORTING', True)
            assert accounting_module.is_reporting_allowed(bs)
        assert "CL rebase is negative" in caplog.text

    def test_no_negative_rebase(self, accounting_module, bs):
        accounting_module.bunker_service._get_total_supply = Mock(return_value=90)
        accounting_module.simulate_cl_rebase = Mock(return_value=LidoReportRebaseFactory.build(post_total_pooled_ether=100))
        assert accounting_module.is_reporting_allowed(bs)

    def test_negative_rebase(self, accounting_module, bs):
        accounting_module.bunker_service._get_total_supply = Mock(return_value=100)
        accounting_module.simulate_cl_rebase = Mock(return_value=LidoReportRebaseFactory.build(post_total_pooled_ether=90))
        assert accounting_module.is_reporting_allowed(bs) is False
