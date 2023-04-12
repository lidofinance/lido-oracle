from collections import namedtuple

import pytest
from unittest.mock import MagicMock
from eth_typing import HexStr
from hexbytes import HexBytes
from dataclasses import asdict

from src.modules.accounting.typings import OracleReportLimits
from src.constants import FAR_FUTURE_EPOCH
from src.providers.consensus.typings import Validator, ValidatorState
from src.providers.keys.typings import LidoKey
from src.modules.accounting.extra_data import ExtraData, FormatList
from src.modules.submodules.typings import ChainConfig
from src.services.validator_state import LidoValidatorStateService
from src.utils import events
from src.web3py.extensions.lido_validators import LidoValidator, StakingModuleId, NodeOperatorId, \
    ValidatorsByNodeOperator
from tests.factory.blockstamp import ReferenceBlockStampFactory
from src.web3py.typings import Web3


@pytest.fixture
def chain_config():
    return ChainConfig(slots_per_epoch=32, seconds_per_slot=12, genesis_time=0)


@pytest.fixture
def blockstamp():
    TESTING_REF_EPOCH = 100

    return ReferenceBlockStampFactory.build(
        ref_slot=9024,
        ref_epoch=TESTING_REF_EPOCH)


@pytest.mark.unit
def test_get_extra_data(blockstamp, chain_config):
    web3 = MagicMock()

    expected = ExtraData(
        extra_data=b'\x00\x00\x00\x00\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x01\x00\x02\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02',
        data_hash=HexBytes(
            b"\x1a\xa3\x94\x9dqI\xcb\xd9y\xbf\xabG\x8d\xeb\xb1j\x91\x8b\xce\xd9\xda;!x*aPk\xf5^\x19\xd1"),
        format=FormatList.EXTRA_DATA_FORMAT_LIST_NON_EMPTY.value,
        items_count=1,
    )

    LidoValidatorStateService.get_lido_newly_stuck_validators = MagicMock()
    LidoValidatorStateService.get_lido_newly_exited_validators = MagicMock()
    LidoValidatorStateService.get_oracle_report_limits = MagicMock()

    lvss = LidoValidatorStateService(web3)

    extra_data_service = MagicMock()
    extra_data_service.collect.return_value = expected
    lvss.extra_data_service = extra_data_service

    actual = lvss.get_extra_data(blockstamp, chain_config)
    assert actual == expected


@pytest.mark.unit
def test_get_last_requested_to_exit_pubkeys(monkeypatch):
    def mock_get_events_in_past(*args, **kwargs):
        return [
            {
                'args': {'validatorPubkey': HexBytes('0x123')},
            },
            {
                'args': {'validatorPubkey': HexBytes('0x111')},
            },
            {
                'args': {'validatorPubkey': HexBytes('0x222')},
            },
            {
                'args': {'validatorPubkey': HexBytes('0x333')},
            },
            {
                'args': {'validatorPubkey': HexBytes('0x444')},
            }
        ]

    web3 = MagicMock()
    web3.lido_contracts.validators_exit_bus_oracle = MagicMock()
    monkeypatch.setattr(events, 'get_events_in_past', mock_get_events_in_past)

    lvss = LidoValidatorStateService(web3)
    extra_data_service = MagicMock()
    lvss.extra_data_service = extra_data_service
    lvss.get_validator_delinquent_timeout_in_slot = MagicMock()

    expected = {'0x0x0222', '0x0x0111', '0x0x0444', '0x0x0123', '0x0x0333'}
    actual = lvss.get_last_requested_to_exit_pubkeys(MagicMock(), MagicMock())

    assert actual == expected


@pytest.fixture()
def get_lido_validators_by_node_operators() -> ValidatorsByNodeOperator:
    def validator(index: int, exit_epoch: int, pubkey: HexStr, activation_epoch: int = 0):
        return LidoValidator(
            lido_id=LidoKey(
                key=pubkey,
                depositSignature="",
                operatorIndex=-1,
                used=True,
                moduleAddress="",
            ),
            **asdict(Validator(
                index=str(index),
                balance="0",
                status="",
                validator=ValidatorState(
                    pubkey=pubkey,
                    withdrawal_credentials="0x1",
                    effective_balance="0",
                    slashed=False,
                    activation_eligibility_epoch="0",
                    activation_epoch=str(activation_epoch),
                    exit_epoch=str(exit_epoch),
                    withdrawable_epoch="0",
                ),
            )),
        )

    return {
        (StakingModuleId(1), NodeOperatorId(0)): [
            validator(index=100, exit_epoch=FAR_FUTURE_EPOCH, pubkey='0x100'),
            validator(index=102, exit_epoch=FAR_FUTURE_EPOCH, pubkey='0x102'),
            validator(index=103, exit_epoch=FAR_FUTURE_EPOCH, pubkey='0x103'),
            validator(index=104, exit_epoch=FAR_FUTURE_EPOCH, pubkey='0x104'),
        ],

        (StakingModuleId(2), NodeOperatorId(2)): [
            validator(index=21, exit_epoch=321, pubkey='0x201', activation_epoch=290),
            validator(index=22, exit_epoch=FAR_FUTURE_EPOCH, pubkey='0x202', activation_epoch=282),
            validator(index=23, exit_epoch=FAR_FUTURE_EPOCH, pubkey='0x203'),
            validator(index=24, exit_epoch=FAR_FUTURE_EPOCH, pubkey='0x204'),
        ],

        (StakingModuleId(3), NodeOperatorId(3)): [
            validator(index=330, exit_epoch=20, pubkey='0x330'),
            validator(index=331, exit_epoch=FAR_FUTURE_EPOCH, pubkey='0x331'),
        ],

        (StakingModuleId(4), NodeOperatorId(4)): [
            validator(index=401, exit_epoch=FAR_FUTURE_EPOCH, activation_epoch=700, pubkey='0x401'),
            validator(index=402, exit_epoch=FAR_FUTURE_EPOCH, activation_epoch=200, pubkey='0x402'),
        ]
    }


@pytest.mark.unit
@pytest.mark.parametrize("ejected_indexes, recent_indexes, delayed_timeout_in_epoch", [
    ({
         (StakingModuleId(1), NodeOperatorId(0)): 105,
         (StakingModuleId(2), NodeOperatorId(2)): 21,
         (StakingModuleId(3), NodeOperatorId(3)): -1,
         (StakingModuleId(4), NodeOperatorId(4)): 402
     }, {
         (StakingModuleId(1), NodeOperatorId(0)): {100, 102},
         (StakingModuleId(2), NodeOperatorId(2)): {},
         (StakingModuleId(3), NodeOperatorId(3)): {330, 331},
         (StakingModuleId(4), NodeOperatorId(4)): {},
     }, 1280,
    )
])
def test_get_recently_requested_but_not_exited_validators(chain_config,
                                                          get_lido_validators_by_node_operators,
                                                          ejected_indexes,
                                                          recent_indexes,
                                                          delayed_timeout_in_epoch):
    web3 = MagicMock()

    web3.lido_validators.get_lido_validators_by_node_operators = MagicMock(
        return_value=get_lido_validators_by_node_operators)

    lvss = LidoValidatorStateService(web3)
    extra_data_service = MagicMock()
    lvss.extra_data_service = extra_data_service

    lvss.get_operators_with_last_exited_validator_indexes = MagicMock(return_value=ejected_indexes)
    lvss.get_recently_requests_to_exit_indexes_by_operators = MagicMock(return_value=recent_indexes)
    lvss.get_validator_delayed_timeout_in_slot = MagicMock(return_value=delayed_timeout_in_epoch)

    blockstamp = ReferenceBlockStampFactory.build(ref_epoch=912, ref_slot=50)

    actual = lvss.get_recently_requested_but_not_exited_validators(blockstamp, chain_config)

    expected = [LidoValidator(index='100',
                              balance='0',
                              status='',
                              validator=ValidatorState(pubkey='0x100',
                                                       withdrawal_credentials='0x1',
                                                       effective_balance='0',
                                                       slashed=False,
                                                       activation_eligibility_epoch='0',
                                                       activation_epoch='0',
                                                       exit_epoch='18446744073709551615',
                                                       withdrawable_epoch='0'),
                              lido_id=LidoKey(key='0x100',
                                              depositSignature='',
                                              operatorIndex=-1,
                                              used=True,
                                              moduleAddress='')),
                LidoValidator(index='102',
                              balance='0',
                              status='',
                              validator=ValidatorState(pubkey='0x102',
                                                       withdrawal_credentials='0x1',
                                                       effective_balance='0',
                                                       slashed=False,
                                                       activation_eligibility_epoch='0',
                                                       activation_epoch='0',
                                                       exit_epoch='18446744073709551615',
                                                       withdrawable_epoch='0'),
                              lido_id=LidoKey(key='0x102',
                                              depositSignature='',
                                              operatorIndex=-1,
                                              used=True,
                                              moduleAddress='')),
                LidoValidator(index='401',
                              balance='0',
                              status='',
                              validator=ValidatorState(pubkey='0x401',
                                                       withdrawal_credentials='0x1',
                                                       effective_balance='0',
                                                       slashed=False,
                                                       activation_eligibility_epoch='0',
                                                       activation_epoch='700',
                                                       exit_epoch='18446744073709551615',
                                                       withdrawable_epoch='0'),
                              lido_id=LidoKey(key='0x401',
                                              depositSignature='',
                                              operatorIndex=-1,
                                              used=True,
                                              moduleAddress=''))
                ]

    assert expected == actual


@pytest.mark.unit
@pytest.mark.parametrize("exiting_keys_stuck_border_in_slots_bytes, expected", [
    (int(12345).to_bytes(2, 'big'), 12345)
])
def test_get_validator_delinquent_timeout_in_slot(exiting_keys_stuck_border_in_slots_bytes, expected):
    web3 = MagicMock()

    call_mock = MagicMock()
    call_mock.call = MagicMock(return_value=exiting_keys_stuck_border_in_slots_bytes)

    web3.lido_contracts.oracle_daemon_config.functions.get = MagicMock(return_value=call_mock)
    web3.to_int = Web3.to_int

    lvss = LidoValidatorStateService(web3)
    lvss.extra_data_service = MagicMock()

    actual = lvss.get_validator_delinquent_timeout_in_slot(MagicMock())

    assert actual == expected


@pytest.mark.unit
@pytest.mark.parametrize("oracle_report_limits_tuple, expected", [
    (namedtuple("ABIDecodedNamedTuple", [
        "churn_validators_per_day_limit",
        "one_off_cl_balance_decrease_bp_limit",
        "annual_balance_increase_bp_limit",
        "simulated_share_rate_deviation_bp_limit",
        "max_validator_exit_requests_per_report",
        "max_accounting_extra_data_list_items_count",
        "max_node_operators_per_extra_data_item_count",
        "request_timestamp_margin",
        "max_positive_token_rebase"
    ])(1, 2, 3, 4, 5, 6, 7, 8, 9),
     OracleReportLimits(churn_validators_per_day_limit=1,
                        one_off_cl_balance_decrease_bp_limit=2,
                        annual_balance_increase_bp_limit=3,
                        simulated_share_rate_deviation_bp_limit=4,
                        max_validator_exit_requests_per_report=5,
                        max_accounting_extra_data_list_items_count=6,
                        max_node_operators_per_extra_data_item_count=7,
                        request_timestamp_margin=8,
                        max_positive_token_rebase=9)
     )
])
def test_get_oracle_report_limits(oracle_report_limits_tuple, expected):
    web3 = MagicMock()

    web3.lido_contracts.oracle_report_sanity_checker.functions.getOracleReportLimits().call = MagicMock(return_value=oracle_report_limits_tuple)

    lvss = LidoValidatorStateService(web3)
    extra_data_service = MagicMock()
    lvss.extra_data_service = extra_data_service

    actual = lvss.get_oracle_report_limits(MagicMock())

    assert actual.__eq__(expected)
