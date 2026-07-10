"""
Unit tests for contract wrappers — both non-trivial transformation logic and
pass-through methods (to maintain coverage without integration tests).
"""

from collections import namedtuple
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from eth_typing import BlockNumber, ChecksumAddress, Hash32
from hexbytes import HexBytes
from web3.types import EventData, Wei

from src.modules.common.types import ChainConfig, CurrentFrame, FrameConfig
from src.modules.oracles.accounting.events import (
    BadDebtSocializedEvent,
    BadDebtWrittenOffToBeInternalizedEvent,
    BurnedSharesOnVaultEvent,
    MintedSharesOnVaultEvent,
    VaultConnectedEvent,
    VaultFeesUpdatedEvent,
    VaultRebalancedEvent,
)
from src.modules.oracles.accounting.types import (
    AccountingProcessingState,
    BalanceStats,
    BatchState,
    BeaconStat,
    OracleReportLimits,
    ReportSimulationPayload,
    ReportSimulationResults,
    Shares,
    SharesRequestedToBurn,
    ValidatorStage,
    VaultInfo,
    WithdrawalRequestStatus,
)
from src.modules.oracles.staking_modules.common.state import DutyAccumulator, ValidatorDuties
from src.providers.execution.contracts.accounting import AccountingContract
from src.providers.execution.contracts.accounting_oracle import AccountingOracleContract
from src.providers.execution.contracts.base_oracle import BaseOracleContract
from src.providers.execution.contracts.burner import BurnerContract
from src.providers.execution.contracts.cs_accounting import CSAccountingContract
from src.providers.execution.contracts.cs_fee_distributor import CSFeeDistributorContract
from src.providers.execution.contracts.cs_fee_oracle import CSFeeOracleContract
from src.providers.execution.contracts.cs_module import CSModuleContract
from src.providers.execution.contracts.cs_parameters_registry import (
    KeyNumberValueInterval,
    KeyNumberValueIntervalList,
    PerformanceCoefficients,
)
from src.providers.execution.contracts.cs_strikes import CSStrikesContract
from src.providers.execution.contracts.curated_staking_module import CuratedStakingModuleContract
from src.providers.execution.contracts.data_bus import DataBusContract
from src.providers.execution.contracts.delegation_contract import DelegationContract
from src.providers.execution.contracts.deposit_contract import DepositContract
from src.providers.execution.contracts.hash_consensus import HashConsensusContract
from src.providers.execution.contracts.lazy_oracle import LazyOracleContract
from src.providers.execution.contracts.lido import LidoContract
from src.providers.execution.contracts.lido_locator import LidoLocatorContract
from src.providers.execution.contracts.meta_registry import ExternalOperator, MetaRegistryContract
from src.providers.execution.contracts.oracle_report_sanity_checker import OracleReportSanityCheckerContract
from src.providers.execution.contracts.staking_router import StakingRouterContract
from src.providers.execution.contracts.vault_hub import VaultHubContract
from src.providers.execution.contracts.withdrawal_queue_nft import WithdrawalQueueNftContract
from src.types import NodeOperatorId


DUMMY_ADDRESS = cast(ChecksumAddress, "0x0000000000000000000000000000000000000000")


def _mock_contract():
    m = MagicMock()
    m.address = DUMMY_ADDRESS
    return m


# ---------------------------------------------------------------------------
# DepositContract.get_deposit_count — little-endian bytes → int
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDepositContractGetDepositCount:
    def test_converts_little_endian_bytes_to_int(self):
        contract = _mock_contract()
        contract.functions.get_deposit_count.return_value.call.return_value = (42).to_bytes(8, "little")

        result = DepositContract.get_deposit_count(contract, block_identifier=1000)

        assert result == 42

    def test_zero(self):
        contract = _mock_contract()
        contract.functions.get_deposit_count.return_value.call.return_value = (0).to_bytes(8, "little")

        result = DepositContract.get_deposit_count(contract, block_identifier=1000)

        assert result == 0

    def test_large_value(self):
        contract = _mock_contract()
        expected = 1_000_000
        contract.functions.get_deposit_count.return_value.call.return_value = expected.to_bytes(8, "little")

        result = DepositContract.get_deposit_count(contract, block_identifier=1000)

        assert result == expected


# ---------------------------------------------------------------------------
# ExternalOperator.get_gid — 10-byte data parsing across input types
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExternalOperatorGetGid:
    # data layout: byte[0]=type, byte[1]=staking_module_id, byte[2:10]=node_operator_id

    def _make_data(self, sm_id: int, no_id: int) -> bytes:
        return bytes([0x01, sm_id]) + no_id.to_bytes(8, "big")

    def test_bytes_input(self):
        data = self._make_data(sm_id=2, no_id=3)
        sm_id, no_id = ExternalOperator(data=data).get_gid()
        assert sm_id == 2
        assert no_id == 3

    def test_invalid_length_raises(self):
        with pytest.raises(ValueError, match="Expected 10 bytes"):
            ExternalOperator(data=b"\x01\x02").get_gid()

    def test_zero_ids(self):
        data = self._make_data(sm_id=0, no_id=0)
        sm_id, no_id = ExternalOperator(data=data).get_gid()
        assert sm_id == 0
        assert no_id == 0


# ---------------------------------------------------------------------------
# KeyNumberValueIntervalList.get_for — sorted interval lookup
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestKeyNumberValueIntervalListGetFor:
    def _make_list(self, intervals: list[tuple[int, int]]) -> KeyNumberValueIntervalList:
        return KeyNumberValueIntervalList([KeyNumberValueInterval(min_k, v) for min_k, v in intervals])

    def test_returns_value_for_exact_match(self):
        lst = self._make_list([(1, 5000), (10, 7000)])
        assert lst.get_for(10) == pytest.approx(7000 / 10000)

    def test_returns_value_for_higher_key(self):
        lst = self._make_list([(1, 5000), (10, 7000)])
        # key_number=15 >= 10, so uses second interval
        assert lst.get_for(15) == pytest.approx(7000 / 10000)

    def test_falls_back_to_lower_interval(self):
        lst = self._make_list([(1, 5000), (10, 7000)])
        # key_number=5 < 10, falls back to interval with minKeyNumber=1
        assert lst.get_for(5) == pytest.approx(5000 / 10000)

    def test_minimum_key_number_1(self):
        lst = self._make_list([(1, 10000)])
        assert lst.get_for(1) == pytest.approx(1.0)

    def test_key_number_zero_raises(self):
        lst = self._make_list([(1, 5000)])
        with pytest.raises(ValueError, match="greater than 1 or equal"):
            lst.get_for(0)

    def test_no_matching_interval_raises(self):
        lst = self._make_list([(5, 5000)])
        # key_number=3 < 5, no interval matches
        with pytest.raises(ValueError, match="No value found"):
            lst.get_for(3)

    def test_picks_highest_applicable_interval(self):
        lst = self._make_list([(1, 1000), (5, 2000), (10, 9000)])
        # key_number=7 → highest applicable is minKeyNumber=5
        assert lst.get_for(7) == pytest.approx(2000 / 10000)


# ---------------------------------------------------------------------------
# PerformanceCoefficients.calc_performance — weighted duty calculation
# ---------------------------------------------------------------------------


def _duty(assigned: int, included: int) -> DutyAccumulator:
    d = DutyAccumulator()
    d.assigned = assigned
    d.included = included
    return d


@pytest.mark.unit
class TestPerformanceCoefficientsCalcPerformance:
    def test_attestation_only_perfect(self):
        duties = ValidatorDuties(attestation=_duty(10, 10), proposal=None, sync=None)
        result = PerformanceCoefficients().calc_performance(duties)
        assert result == pytest.approx(1.0)

    def test_attestation_only_half(self):
        duties = ValidatorDuties(attestation=_duty(10, 5), proposal=None, sync=None)
        result = PerformanceCoefficients().calc_performance(duties)
        assert result == pytest.approx(0.5)

    def test_proposal_only_perfect(self):
        duties = ValidatorDuties(attestation=None, proposal=_duty(1, 1), sync=None)
        result = PerformanceCoefficients().calc_performance(duties)
        assert result == pytest.approx(1.0)

    def test_sync_only_perfect(self):
        duties = ValidatorDuties(attestation=None, proposal=None, sync=_duty(100, 100))
        result = PerformanceCoefficients().calc_performance(duties)
        assert result == pytest.approx(1.0)

    def test_all_duties_perfect(self):
        duties = ValidatorDuties(
            attestation=_duty(10, 10),
            proposal=_duty(1, 1),
            sync=_duty(100, 100),
        )
        result = PerformanceCoefficients().calc_performance(duties)
        assert result == pytest.approx(1.0)

    def test_mixed_performance(self):
        # attestations_weight=54, blocks_weight=8, sync_weight=2
        coeffs = PerformanceCoefficients(attestations_weight=54, blocks_weight=8, sync_weight=2)
        duties = ValidatorDuties(
            attestation=_duty(10, 10),  # perf=1.0
            proposal=_duty(1, 0),  # perf=0.0
            sync=_duty(10, 10),  # perf=1.0
        )
        expected = (1.0 * 54 + 0.0 * 8 + 1.0 * 2) / (54 + 8 + 2)
        result = coeffs.calc_performance(duties)
        assert result == pytest.approx(expected)

    def test_invalid_performance_raises(self):
        # DutyAccumulator.perf > 1 is impossible via normal means, but
        # if weights produce > 1.0 due to custom coeffs it should raise
        coeffs = PerformanceCoefficients(attestations_weight=1, blocks_weight=0, sync_weight=0)
        # Simulate perf > 1 by patching
        duty = MagicMock()
        duty.perf = 1.5
        duties = ValidatorDuties(attestation=duty, proposal=None, sync=None)
        with pytest.raises(ValueError, match="Invalid performance"):
            coeffs.calc_performance(duties)


# ---------------------------------------------------------------------------
# LazyOracleContract.get_vaults — struct attribute → VaultInfo field mapping
# ---------------------------------------------------------------------------


def _make_raw_vault(
    vault=DUMMY_ADDRESS,
    aggregated_balance=1000,
    in_out_delta=50,
    withdrawal_credentials=b"\x01" * 32,
    liability_shares=100,
    max_liability_shares=200,
    mintable_st_eth=50,
    share_limit=500,
    reserve_ratio_bp=1000,
    forced_rebalance_threshold_bp=2000,
    infra_fee_bp=100,
    liquidity_fee_bp=200,
    reservation_fee_bp=50,
    pending_disconnect=False,
):
    v = MagicMock()
    v.vault = vault
    v.aggregatedBalance = aggregated_balance
    v.inOutDelta = in_out_delta
    v.withdrawalCredentials = withdrawal_credentials
    v.liabilityShares = liability_shares
    v.maxLiabilityShares = max_liability_shares
    v.mintableStETH = mintable_st_eth
    v.shareLimit = share_limit
    v.reserveRatioBP = reserve_ratio_bp
    v.forcedRebalanceThresholdBP = forced_rebalance_threshold_bp
    v.infraFeeBP = infra_fee_bp
    v.liquidityFeeBP = liquidity_fee_bp
    v.reservationFeeBP = reservation_fee_bp
    v.pendingDisconnect = pending_disconnect
    return v


@pytest.mark.unit
class TestLazyOracleGetVaults:
    def test_maps_all_fields_correctly(self):
        contract = _mock_contract()
        raw = _make_raw_vault()
        contract.functions.batchVaultsInfo.return_value.call.return_value = [raw]

        result = LazyOracleContract.get_vaults(contract, offset=0, limit=10, block_identifier="latest")

        assert len(result) == 1
        v = result[0]
        assert isinstance(v, VaultInfo)
        assert v.aggregated_balance == 1000
        assert v.in_out_delta == 50
        assert v.liability_shares == 100
        assert v.max_liability_shares == 200
        assert v.reserve_ratio_bp == 1000
        assert v.pending_disconnect is False

    def test_withdrawal_credentials_converted_to_hex(self):
        contract = _mock_contract()
        raw = _make_raw_vault(withdrawal_credentials=b"\xab" * 32)
        contract.functions.batchVaultsInfo.return_value.call.return_value = [raw]

        result = LazyOracleContract.get_vaults(contract, offset=0, limit=10, block_identifier="latest")

        assert result[0].withdrawal_credentials.startswith("0x")
        assert "ab" in result[0].withdrawal_credentials.lower()

    def test_empty_response(self):
        contract = _mock_contract()
        contract.functions.batchVaultsInfo.return_value.call.return_value = []

        result = LazyOracleContract.get_vaults(contract, offset=0, limit=10, block_identifier="latest")

        assert result == []

    def test_passes_offset_and_limit(self):
        contract = _mock_contract()
        contract.functions.batchVaultsInfo.return_value.call.return_value = []

        LazyOracleContract.get_vaults(contract, offset=50, limit=25, block_identifier="latest")

        contract.functions.batchVaultsInfo.assert_called_once_with(50, 25)


# ---------------------------------------------------------------------------
# LazyOracleContract.get_all_vaults — pagination logic
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLazyOracleGetAllVaults:
    # get_all_vaults calls self.get_vaults_count() and self.get_vaults() —
    # mock those directly on the contract instance, not via functions.*

    def test_returns_empty_when_count_is_zero(self):
        contract = _mock_contract()
        contract.get_vaults_count.return_value = 0

        result = LazyOracleContract.get_all_vaults(contract, block_identifier="latest")

        assert result == []
        contract.get_vaults.assert_not_called()

    def test_single_page(self, monkeypatch):
        monkeypatch.setattr("src.providers.execution.contracts.lazy_oracle.variables.VAULT_PAGINATION_LIMIT", 100)
        contract = _mock_contract()
        contract.get_vaults_count.return_value = 2
        fake_vaults = [MagicMock(spec=VaultInfo), MagicMock(spec=VaultInfo)]
        contract.get_vaults.return_value = fake_vaults

        result = LazyOracleContract.get_all_vaults(contract, block_identifier="latest")

        assert len(result) == 2
        contract.get_vaults.assert_called_once_with(block_identifier="latest", offset=0, limit=100)

    def test_multiple_pages(self, monkeypatch):
        monkeypatch.setattr("src.providers.execution.contracts.lazy_oracle.variables.VAULT_PAGINATION_LIMIT", 2)
        contract = _mock_contract()
        contract.get_vaults_count.return_value = 3

        page1 = [MagicMock(spec=VaultInfo), MagicMock(spec=VaultInfo)]
        page2 = [MagicMock(spec=VaultInfo)]
        contract.get_vaults.side_effect = [page1, page2]

        result = LazyOracleContract.get_all_vaults(contract, block_identifier="latest")

        assert len(result) == 3
        assert contract.get_vaults.call_count == 2
        contract.get_vaults.assert_any_call(block_identifier="latest", offset=0, limit=2)
        contract.get_vaults.assert_any_call(block_identifier="latest", offset=2, limit=2)

    def test_stops_on_empty_batch(self, monkeypatch):
        monkeypatch.setattr("src.providers.execution.contracts.lazy_oracle.variables.VAULT_PAGINATION_LIMIT", 100)
        contract = _mock_contract()
        contract.get_vaults_count.return_value = 5
        contract.get_vaults.return_value = []

        result = LazyOracleContract.get_all_vaults(contract, block_identifier="latest")

        assert result == []


# ---------------------------------------------------------------------------
# LazyOracleContract.get_validator_statuses — batching by batch_size
# ---------------------------------------------------------------------------


def _make_status(stage=3):
    s = MagicMock()
    s.stage = stage
    s.stakingVault = DUMMY_ADDRESS
    s.nodeOperator = DUMMY_ADDRESS
    return s


@pytest.mark.unit
class TestLazyOracleGetValidatorStatuses:
    def _pubkey(self, n: int) -> str:
        return "0x" + hex(n)[2:].zfill(96)

    def test_empty_pubkeys(self):
        contract = _mock_contract()
        result = LazyOracleContract.get_validator_statuses(
            contract, pubkeys=[], batch_size=10, block_identifier="latest"
        )
        assert result == {}

    def test_single_batch(self):
        contract = _mock_contract()
        pk = self._pubkey(1)
        contract.functions.batchValidatorStatuses.return_value.call.return_value = [_make_status(3)]

        result = LazyOracleContract.get_validator_statuses(
            contract, pubkeys=[pk], batch_size=10, block_identifier="latest"
        )

        assert pk in result
        assert result[pk].stage == ValidatorStage.ACTIVATED

    def test_multiple_batches(self):
        contract = _mock_contract()
        pubkeys = [self._pubkey(i) for i in range(3)]
        batch1_statuses = [_make_status(3), _make_status(3)]
        batch2_statuses = [_make_status(0)]
        contract.functions.batchValidatorStatuses.return_value.call.side_effect = [batch1_statuses, batch2_statuses]

        result = LazyOracleContract.get_validator_statuses(
            contract, pubkeys=pubkeys, batch_size=2, block_identifier="latest"
        )

        assert len(result) == 3
        assert contract.functions.batchValidatorStatuses.call_count == 2

    def test_result_keyed_by_0x_pubkey(self):
        contract = _mock_contract()
        pk = self._pubkey(42)
        contract.functions.batchValidatorStatuses.return_value.call.return_value = [_make_status(1)]

        result = LazyOracleContract.get_validator_statuses(
            contract, pubkeys=[pk], batch_size=10, block_identifier="latest"
        )

        key = next(iter(result))
        assert key.startswith("0x")


# ---------------------------------------------------------------------------
# StakingRouterContract.get_all_node_operator_digests — pagination while loop
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStakingRouterGetAllNodeOperatorDigests:
    def _make_module(self, module_id=1):
        m = MagicMock()
        m.id = module_id
        return m

    @patch("src.providers.execution.contracts.staking_router.NodeOperator.from_response")
    def test_single_batch_shorter_than_batch_size(self, mock_from_response, monkeypatch):
        monkeypatch.setattr("src.providers.execution.contracts.staking_router.EL_REQUESTS_BATCH_SIZE", 500)
        contract = _mock_contract()
        fake_no = MagicMock()
        contract.functions.getNodeOperatorDigests.return_value.call.return_value = [fake_no, fake_no]
        mock_from_response.return_value = MagicMock()

        result = StakingRouterContract.get_all_node_operator_digests(
            contract, self._make_module(), block_identifier="latest"
        )

        assert len(result) == 2
        assert contract.functions.getNodeOperatorDigests.call_count == 1

    @patch("src.providers.execution.contracts.staking_router.NodeOperator.from_response")
    def test_multiple_pages(self, mock_from_response, monkeypatch):
        monkeypatch.setattr("src.providers.execution.contracts.staking_router.EL_REQUESTS_BATCH_SIZE", 2)
        contract = _mock_contract()
        fake_no = MagicMock()
        # First call returns full batch (2), second returns partial (1) → stops
        contract.functions.getNodeOperatorDigests.return_value.call.side_effect = [
            [fake_no, fake_no],
            [fake_no],
        ]
        mock_from_response.return_value = MagicMock()

        result = StakingRouterContract.get_all_node_operator_digests(
            contract, self._make_module(), block_identifier="latest"
        )

        assert len(result) == 3
        assert contract.functions.getNodeOperatorDigests.call_count == 2

    @patch("src.providers.execution.contracts.staking_router.NodeOperator.from_response")
    def test_empty_first_response(self, mock_from_response, monkeypatch):
        monkeypatch.setattr("src.providers.execution.contracts.staking_router.EL_REQUESTS_BATCH_SIZE", 500)
        contract = _mock_contract()
        contract.functions.getNodeOperatorDigests.return_value.call.return_value = []

        result = StakingRouterContract.get_all_node_operator_digests(
            contract, self._make_module(), block_identifier="latest"
        )

        assert result == []

    @patch("src.providers.execution.contracts.staking_router.NodeOperator.from_response")
    def test_uses_correct_offsets(self, mock_from_response, monkeypatch):
        monkeypatch.setattr("src.providers.execution.contracts.staking_router.EL_REQUESTS_BATCH_SIZE", 2)
        contract = _mock_contract()
        fake_no = MagicMock()
        contract.functions.getNodeOperatorDigests.return_value.call.side_effect = [[fake_no, fake_no], []]
        mock_from_response.return_value = MagicMock()
        module = self._make_module(module_id=3)

        StakingRouterContract.get_all_node_operator_digests(contract, module, block_identifier="latest")

        contract.functions.getNodeOperatorDigests.assert_any_call(3, 0, 2)
        contract.functions.getNodeOperatorDigests.assert_any_call(3, 2, 2)


# ---------------------------------------------------------------------------
# StakingRouterContract.get_staking_module — named_tuple_to_dataclass mapping
# ---------------------------------------------------------------------------

_StakingModuleTuple = namedtuple(
    "StakingModule",
    [
        "id",
        "stakingModuleAddress",
        "stakingModuleFee",
        "treasuryFee",
        "stakeShareLimit",
        "status",
        "name",
        "lastDepositAt",
        "lastDepositBlock",
        "exitedValidatorsCount",
        "priorityExitShareThreshold",
        "maxDepositsPerBlock",
        "minDepositBlockDistance",
        "withdrawalCredentialsType",
        "validatorsBalanceGwei",
    ],
)


# ---------------------------------------------------------------------------
# StakingRouterContract.get_staking_modules_by_address — dict keyed by address
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStakingRouterGetStakingModulesByAddress:
    # get_staking_modules_by_address calls self.get_staking_modules() —
    # mock it directly on the contract instance.

    def test_builds_dict_keyed_by_address(self):
        contract = _mock_contract()
        addr1 = "0x" + "aa" * 20
        addr2 = "0x" + "bb" * 20
        m1, m2 = MagicMock(), MagicMock()
        m1.staking_module_address = addr1
        m2.staking_module_address = addr2
        contract.get_staking_modules.return_value = [m1, m2]

        result = StakingRouterContract.get_staking_modules_by_address(contract, block_identifier="latest")

        assert result == {addr1: m1, addr2: m2}

    def test_empty(self):
        contract = _mock_contract()
        contract.get_staking_modules.return_value = []

        result = StakingRouterContract.get_staking_modules_by_address(contract, block_identifier="latest")

        assert result == {}


# ---------------------------------------------------------------------------
# CuratedStakingModuleContract.get_operator_weights — islice batching
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCuratedStakingModuleGetOperatorWeights:
    def test_empty_returns_empty(self):
        contract = _mock_contract()
        result = CuratedStakingModuleContract.get_operator_weights(contract, operator_ids=[], block_identifier=1000)
        assert result == []
        contract.functions.getOperatorWeights.assert_not_called()

    def test_single_batch(self, monkeypatch):
        monkeypatch.setattr("src.providers.execution.contracts.curated_staking_module.EL_REQUESTS_BATCH_SIZE", 500)
        contract = _mock_contract()
        contract.functions.getOperatorWeights.return_value.call.return_value = [10, 20]

        result = CuratedStakingModuleContract.get_operator_weights(
            contract, operator_ids=[NodeOperatorId(1), NodeOperatorId(2)], block_identifier=1000
        )

        assert result == [10, 20]

    def test_multiple_batches(self, monkeypatch):
        monkeypatch.setattr("src.providers.execution.contracts.curated_staking_module.EL_REQUESTS_BATCH_SIZE", 2)
        contract = _mock_contract()
        contract.functions.getOperatorWeights.return_value.call.side_effect = [[10, 20], [30]]

        result = CuratedStakingModuleContract.get_operator_weights(
            contract, operator_ids=[NodeOperatorId(1), NodeOperatorId(2), NodeOperatorId(3)], block_identifier=1000
        )

        assert result == [10, 20, 30]


# ---------------------------------------------------------------------------
# DelegationContract.execute — eth_abi encoding before calling execute()
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDelegationContractExecute:
    def test_encodes_address_and_calldata(self):
        from eth_abi.abi import decode

        contract = _mock_contract()
        tx = MagicMock()
        contract.functions.execute.return_value = tx
        target = "0x" + "cc" * 20
        calldata = b"\xab\xcd\xef"

        DelegationContract.execute(contract, target_address=target, calldata=calldata)

        encoded = contract.functions.execute.call_args[0][0]
        decoded_target, decoded_calldata = decode(["address", "bytes"], encoded)
        assert decoded_target.lower() == target.lower()
        assert decoded_calldata == calldata

    def test_returns_contract_function(self):
        contract = _mock_contract()
        tx = MagicMock()
        contract.functions.execute.return_value = tx

        result = DelegationContract.execute(contract, target_address=DUMMY_ADDRESS, calldata=b"")

        assert result == tx

    def test_logs_target_and_calldata_length(self, caplog):
        import logging

        contract = _mock_contract()
        contract.functions.execute.return_value = MagicMock()
        calldata = b"\x01" * 10

        with caplog.at_level(logging.INFO, logger="src.providers.execution.contracts.delegation_contract"):
            DelegationContract.execute(contract, target_address=DUMMY_ADDRESS, calldata=calldata)

        assert any("10" in m for m in caplog.messages)


# ---------------------------------------------------------------------------
# Helpers for event log tests
# ---------------------------------------------------------------------------

_DUMMY_TX_HASH = HexBytes(b"\xab" * 32)
_DUMMY_BLOCK_HASH = HexBytes(b"\xcd" * 32)
_DUMMY_VAULT = "0x" + "aa" * 20
_FROM_BLOCK = BlockNumber(100)
_TO_BLOCK = BlockNumber(200)


def _make_log(args: dict, event_name: str = "TestEvent") -> EventData:
    return cast(
        EventData,
        {
            "event": event_name,
            "logIndex": 1,
            "transactionIndex": 2,
            "transactionHash": _DUMMY_TX_HASH,
            "address": DUMMY_ADDRESS,
            "blockHash": _DUMMY_BLOCK_HASH,
            "blockNumber": 999,
            "args": args,
        },
    )


# ---------------------------------------------------------------------------
# Event from_log — field mapping for each event type
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMintedSharesOnVaultEventFromLog:
    def test_maps_all_fields(self):
        log = _make_log({"vault": _DUMMY_VAULT, "amountOfShares": 100, "lockedAmount": 50})
        event = MintedSharesOnVaultEvent.from_log(log)
        assert event.vault == _DUMMY_VAULT
        assert event.amount_of_shares == 100
        assert event.locked_amount == 50
        assert event.block_number == 999


@pytest.mark.unit
class TestBurnedSharesOnVaultEventFromLog:
    def test_maps_all_fields(self):
        log = _make_log({"vault": _DUMMY_VAULT, "amountOfShares": 42})
        event = BurnedSharesOnVaultEvent.from_log(log)
        assert event.vault == _DUMMY_VAULT
        assert event.amount_of_shares == 42


@pytest.mark.unit
class TestVaultFeesUpdatedEventFromLog:
    def test_maps_all_fields(self):
        log = _make_log(
            {
                "vault": _DUMMY_VAULT,
                "preInfraFeeBP": 100,
                "infraFeeBP": 110,
                "preLiquidityFeeBP": 200,
                "liquidityFeeBP": 210,
                "preReservationFeeBP": 50,
                "reservationFeeBP": 55,
            }
        )
        event = VaultFeesUpdatedEvent.from_log(log)
        assert event.pre_infra_fee_bp == 100
        assert event.infra_fee_bp == 110
        assert event.pre_liquidity_fee_bp == 200
        assert event.liquidity_fee_bp == 210
        assert event.pre_reservation_fee_bp == 50
        assert event.reservation_fee_bp == 55


@pytest.mark.unit
class TestVaultRebalancedEventFromLog:
    def test_maps_all_fields(self):
        log = _make_log({"vault": _DUMMY_VAULT, "sharesBurned": 10, "etherWithdrawn": 20})
        event = VaultRebalancedEvent.from_log(log)
        assert event.vault == _DUMMY_VAULT
        assert event.shares_burned == 10
        assert event.ether_withdrawn == 20


@pytest.mark.unit
class TestBadDebtSocializedEventFromLog:
    def test_maps_all_fields(self):
        vault_b = "0x" + "bb" * 20
        log = _make_log({"vaultDonor": _DUMMY_VAULT, "vaultAcceptor": vault_b, "badDebtShares": 7})
        event = BadDebtSocializedEvent.from_log(log)
        assert event.vault_donor == _DUMMY_VAULT
        assert event.vault_acceptor == vault_b
        assert event.bad_debt_shares == 7


@pytest.mark.unit
class TestVaultConnectedEventFromLog:
    def test_maps_all_fields(self):
        log = _make_log(
            {
                "vault": _DUMMY_VAULT,
                "shareLimit": 500,
                "reserveRatioBP": 1000,
                "forcedRebalanceThresholdBP": 2000,
                "infraFeeBP": 100,
                "liquidityFeeBP": 200,
                "reservationFeeBP": 50,
            }
        )
        event = VaultConnectedEvent.from_log(log)
        assert event.share_limit == 500
        assert event.reserve_ratio_bp == 1000
        assert event.forced_rebalance_threshold_bp == 2000


@pytest.mark.unit
class TestBadDebtWrittenOffToBeInternalizedEventFromLog:
    def test_maps_all_fields(self):
        log = _make_log({"vault": _DUMMY_VAULT, "badDebtShares": 3})
        event = BadDebtWrittenOffToBeInternalizedEvent.from_log(log)
        assert event.vault == _DUMMY_VAULT
        assert event.bad_debt_shares == 3


# ---------------------------------------------------------------------------
# VaultHubContract — event methods delegate to get_events_in_range + from_log
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVaultHubContractEventMethods:
    def _make_contract(self):
        c = _mock_contract()
        return c

    @patch("src.providers.execution.contracts.vault_hub.get_events_in_range")
    def test_get_minted_events_maps_logs(self, mock_get_events):
        log = _make_log({"vault": _DUMMY_VAULT, "amountOfShares": 5, "lockedAmount": 1})
        mock_get_events.return_value = [log]
        contract = self._make_contract()

        result = VaultHubContract.get_minted_events(contract, _FROM_BLOCK, _TO_BLOCK)

        assert len(result) == 1
        assert isinstance(result[0], MintedSharesOnVaultEvent)
        assert result[0].amount_of_shares == 5

    @patch("src.providers.execution.contracts.vault_hub.get_events_in_range")
    def test_get_burned_events_maps_logs(self, mock_get_events):
        log = _make_log({"vault": _DUMMY_VAULT, "amountOfShares": 8})
        mock_get_events.return_value = [log]
        contract = self._make_contract()

        result = VaultHubContract.get_burned_events(contract, _FROM_BLOCK, _TO_BLOCK)

        assert len(result) == 1
        assert isinstance(result[0], BurnedSharesOnVaultEvent)

    @patch("src.providers.execution.contracts.vault_hub.get_events_in_range")
    def test_returns_empty_list_when_no_events(self, mock_get_events):
        mock_get_events.return_value = []
        contract = self._make_contract()

        result = VaultHubContract.get_minted_events(contract, _FROM_BLOCK, _TO_BLOCK)

        assert result == []


# ---------------------------------------------------------------------------
# MetaRegistryContract.get_all_groups — pagination over group count
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetaRegistryGetAllGroups:
    def test_empty(self):
        contract = _mock_contract()
        contract.get_operator_groups_count.return_value = 0

        result = MetaRegistryContract.get_all_groups(contract, block_identifier="latest")

        assert result == []
        contract.get_operator_group.assert_not_called()

    def test_fetches_each_group_by_index(self):
        contract = _mock_contract()
        contract.get_operator_groups_count.return_value = 3
        groups = [MagicMock(), MagicMock(), MagicMock()]
        contract.get_operator_group.side_effect = groups

        result = MetaRegistryContract.get_all_groups(contract, block_identifier="latest")

        assert result == groups
        contract.get_operator_group.assert_any_call(1, "latest")
        contract.get_operator_group.assert_any_call(2, "latest")
        contract.get_operator_group.assert_any_call(3, "latest")

    def test_single_group(self):
        contract = _mock_contract()
        contract.get_operator_groups_count.return_value = 1
        group = MagicMock()
        contract.get_operator_group.return_value = group

        result = MetaRegistryContract.get_all_groups(contract, block_identifier=100)

        assert result == [group]
        contract.get_operator_group.assert_called_once_with(1, 100)


@pytest.mark.unit
class TestMetaRegistryContractPassThroughs:
    def test_get_operator_groups_count(self):
        contract = _mock_contract()
        contract.functions.getOperatorGroupsCount.return_value.call.return_value = 5

        result = MetaRegistryContract.get_operator_groups_count(contract, block_identifier="latest")

        assert result == 5
        contract.functions.getOperatorGroupsCount.return_value.call.assert_called_once_with(block_identifier="latest")

    def test_get_operator_group(self):
        from collections import namedtuple

        from src.providers.execution.contracts.meta_registry import OperatorGroup

        contract = _mock_contract()
        SubOpTuple = namedtuple("SubNodeOperator", ["node_operator_id", "share"])
        ExtOpTuple = namedtuple("ExternalOperator", ["data"])
        GroupTuple = namedtuple("OperatorGroup", ["name", "sub_node_operators", "external_operators"])
        raw = GroupTuple(
            name='test',
            sub_node_operators=[SubOpTuple(node_operator_id=1, share=100)],
            external_operators=[ExtOpTuple(data=bytes(10))],
        )
        contract.functions.getOperatorGroup.return_value.call.return_value = raw

        result = MetaRegistryContract.get_operator_group(contract, group_id=0, block_identifier="latest")

        assert isinstance(result, OperatorGroup)
        assert len(result.sub_node_operators) == 1
        assert len(result.external_operators) == 1
        contract.functions.getOperatorGroup.assert_called_once_with(0)


# ---------------------------------------------------------------------------
# AccountingContract.simulate_oracle_report — payload tuple + result unpacking
# ---------------------------------------------------------------------------

_DUMMY_FEE_DIST = MagicMock()


def _make_simulation_response():
    """15-element tuple matching ReportSimulationResults field order."""
    return (1, 2, 3, 4, 5, 6, 7, _DUMMY_FEE_DIST, 8, 9, 10, 11, 12, 13, 14)


@pytest.mark.unit
class TestAccountingSimulateOracleReport:
    def _make_payload(self):
        return ReportSimulationPayload(
            timestamp=1000,
            time_elapsed=86400,
            cl_validators_balance=Wei(32_000_000_000_000_000_000),
            cl_pending_balance=Wei(0),
            withdrawal_vault_balance=Wei(0),
            el_rewards_vault_balance=Wei(0),
            shares_requested_to_burn=Shares(0),
            withdrawal_finalization_batches=[],
            simulated_share_rate=0,
        )

    def test_passes_payload_as_tuple(self):
        contract = _mock_contract()
        contract.functions.simulateOracleReport.return_value.call.return_value = _make_simulation_response()
        payload = self._make_payload()

        AccountingContract.simulate_oracle_report(contract, payload, block_identifier="latest")

        contract.functions.simulateOracleReport.assert_called_once_with(payload.as_tuple())

    def test_returns_report_simulation_results(self):
        contract = _mock_contract()
        contract.functions.simulateOracleReport.return_value.call.return_value = _make_simulation_response()
        payload = self._make_payload()

        result = AccountingContract.simulate_oracle_report(contract, payload, block_identifier="latest")

        assert isinstance(result, ReportSimulationResults)
        assert result.withdrawals_vault_transfer == 1
        assert result.el_rewards_vault_transfer == 2
        assert result.post_total_pooled_ether == 14


# ---------------------------------------------------------------------------
# WithdrawalQueueNftContract.calculate_finalization_batches — named_tuple_to_dataclass
# ---------------------------------------------------------------------------

_BatchStateTuple = namedtuple("BatchState", ["remainingEthBudget", "finished", "batches", "batchesLength"])


@pytest.mark.unit
class TestWithdrawalQueueCalculateFinalizationBatches:
    def test_maps_response_to_batch_state(self):
        contract = _mock_contract()
        raw = _BatchStateTuple(remainingEthBudget=5000, finished=False, batches=[10, 20], batchesLength=2)
        contract.functions.calculateFinalizationBatches.return_value.call.return_value = raw

        result = WithdrawalQueueNftContract.calculate_finalization_batches(
            contract,
            share_rate=10**27,
            timestamp=1000,
            max_batch_request_count=100,
            batch_state=(5000, False, [], 0),
        )

        assert isinstance(result, BatchState)
        assert result.remaining_eth_budget == 5000
        assert result.finished is False
        assert result.batches == [10, 20]
        assert result.batches_length == 2

    def test_passes_all_args_to_contract(self):
        contract = _mock_contract()
        raw = _BatchStateTuple(remainingEthBudget=0, finished=True, batches=[], batchesLength=0)
        contract.functions.calculateFinalizationBatches.return_value.call.return_value = raw

        WithdrawalQueueNftContract.calculate_finalization_batches(
            contract,
            share_rate=123,
            timestamp=456,
            max_batch_request_count=50,
            batch_state=(0, True, [], 0),
            block_identifier=999,
        )

        contract.functions.calculateFinalizationBatches.assert_called_once_with(123, 456, 50, (0, True, [], 0))


# ===========================================================================
# Pass-through method tests (coverage for ABI delegation wrappers)
# ===========================================================================

_ADDR = cast(ChecksumAddress, "0x" + "ab" * 20)
_ROLE = cast(Hash32, b"\x01" * 32)

# Named tuples matching ABI-decoded field names (camelCase) used by named_tuple_to_dataclass

_ChainConfigTuple = namedtuple("ChainConfig", ["slotsPerEpoch", "secondsPerSlot", "genesisTime"])
_CurrentFrameTuple = namedtuple("CurrentFrame", ["refSlot", "reportProcessingDeadlineSlot"])
_FrameConfigTuple = namedtuple("FrameConfig", ["initialEpoch", "epochsPerFrame", "fastLaneLengthSlots"])
_BeaconStatTuple = namedtuple("BeaconStat", ["depositedValidators", "beaconValidators", "beaconBalance"])
_BalanceStatsTuple = namedtuple(
    "BalanceStats",
    [
        "clValidatorsBalanceAtLastReport",
        "clPendingBalanceAtLastReport",
        "depositedSinceLastReport",
        "depositedForCurrentReport",
    ],
)
_SharesRequestedToBurnTuple = namedtuple("SharesRequestedToBurn", ["coverShares", "nonCoverShares"])
_WithdrawalRequestStatusTuple = namedtuple(
    "WithdrawalRequestStatus",
    ["amountOfStEth", "amountOfShares", "owner", "timestamp", "isFinalized", "isClaimed"],
)
_AccountingProcessingStateTuple = namedtuple(
    "AccountingProcessingState",
    [
        "currentFrameRefSlot",
        "processingDeadlineTime",
        "mainDataHash",
        "mainDataSubmitted",
        "extraDataHash",
        "extraDataFormat",
        "extraDataSubmitted",
        "extraDataItemsCount",
        "extraDataItemsSubmitted",
    ],
)
_OracleReportLimitsTuple = namedtuple(
    "OracleReportLimits",
    [
        "exitedEthAmountPerDayLimit",
        "appearedEthAmountPerDayLimit",
        "annualBalanceIncreaseBpLimit",
        "simulatedShareRateDeviationBpLimit",
        "maxBalanceExitRequestedPerReportInEth",
        "maxEffectiveBalanceWeightWCType01",
        "maxEffectiveBalanceWeightWCType02",
        "maxItemsPerExtraDataTransaction",
        "maxNodeOperatorsPerExtraDataItem",
        "requestTimestampMargin",
        "maxPositiveTokenRebase",
        "maxClBalanceDecreaseBp",
        "clBalanceOraclesErrorUpperBpLimit",
        "consolidationEthAmountPerDayLimit",
        "exitedValidatorEthAmountLimit",
    ],
)


# ---------------------------------------------------------------------------
# LidoLocatorContract — 13 address pass-throughs
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "method,fn_attr",
    [
        ("lido", "lido"),
        ("accounting", "accounting"),
        ("accounting_oracle", "accountingOracle"),
        ("staking_router", "stakingRouter"),
        ("validator_exit_bus_oracle", "validatorsExitBusOracle"),
        ("withdrawal_queue", "withdrawalQueue"),
        ("oracle_report_sanity_checker", "oracleReportSanityChecker"),
        ("oracle_daemon_config", "oracleDaemonConfig"),
        ("burner", "burner"),
        ("withdrawal_vault", "withdrawalVault"),
        ("el_rewards_vault", "elRewardsVault"),
        ("vault_hub", "vaultHub"),
        ("lazy_oracle", "lazyOracle"),
    ],
)
def test_lido_locator_pass_throughs(method, fn_attr):
    contract = _mock_contract()
    getattr(contract.functions, fn_attr).return_value.call.return_value = _ADDR
    result = getattr(LidoLocatorContract, method)(contract, block_identifier="latest")
    assert result == _ADDR


# ---------------------------------------------------------------------------
# HashConsensusContract — get/submit pass-throughs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHashConsensusContract:
    def test_get_members(self):
        contract = _mock_contract()
        expected = (["0x" + "aa" * 20], [100])
        contract.functions.getMembers.return_value.call.return_value = expected
        result = HashConsensusContract.get_members(contract, block_identifier="latest")
        assert result == expected

    def test_get_chain_config(self):
        contract = _mock_contract()
        contract.functions.getChainConfig.return_value.call.return_value = _ChainConfigTuple(32, 12, 1000)
        result = HashConsensusContract.get_chain_config(contract, block_identifier="latest")
        assert isinstance(result, ChainConfig)
        assert result.slots_per_epoch == 32
        assert result.seconds_per_slot == 12
        assert result.genesis_time == 1000

    def test_get_current_frame(self):
        contract = _mock_contract()
        contract.functions.getCurrentFrame.return_value.call.return_value = _CurrentFrameTuple(500, 600)
        result = HashConsensusContract.get_current_frame(contract, block_identifier="latest")
        assert isinstance(result, CurrentFrame)
        assert result.ref_slot == 500
        assert result.report_processing_deadline_slot == 600

    def test_get_initial_ref_slot(self):
        contract = _mock_contract()
        contract.functions.getInitialRefSlot.return_value.call.return_value = 42
        result = HashConsensusContract.get_initial_ref_slot(contract, block_identifier="latest")
        assert result == 42

    def test_get_frame_config(self):
        contract = _mock_contract()
        contract.functions.getFrameConfig.return_value.call.return_value = _FrameConfigTuple(1, 45, 0)
        result = HashConsensusContract.get_frame_config(contract, block_identifier="latest")
        assert isinstance(result, FrameConfig)
        assert result.initial_epoch == 1
        assert result.epochs_per_frame == 45

    def test_get_consensus_state_for_member(self):
        contract = _mock_contract()
        expected = (True, False, True, 100, 10, 200, 300, b"\x00" * 32, b"\x00" * 32)
        contract.functions.getConsensusStateForMember.return_value.call.return_value = expected
        result = HashConsensusContract.get_consensus_state_for_member(
            contract, address=ChecksumAddress(_ADDR), block_identifier="latest"
        )
        assert result == expected

    def test_submit_report(self):
        contract = _mock_contract()
        tx = MagicMock()
        contract.functions.submitReport.return_value = tx
        result = HashConsensusContract.submit_report(contract, 100, b"\xab" * 32, 1)
        assert result == tx


# ---------------------------------------------------------------------------
# LidoContract — Wei and BeaconStat pass-throughs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLidoContract:
    def test_get_withdrawals_reserve(self):
        contract = _mock_contract()
        contract.functions.getWithdrawalsReserve.return_value.call.return_value = 1000
        result = LidoContract.get_withdrawals_reserve(contract, block_identifier="latest")
        assert result == 1000

    def test_total_supply(self):
        contract = _mock_contract()
        contract.functions.totalSupply.return_value.call.return_value = 5000
        result = LidoContract.total_supply(contract, block_identifier="latest")
        assert result == 5000

    def test_get_beacon_stat(self):
        contract = _mock_contract()
        contract.functions.getBeaconStat.return_value.call.return_value = _BeaconStatTuple(100, 90, 32 * 10**18)
        result = LidoContract.get_beacon_stat(contract, block_identifier="latest")
        assert isinstance(result, BeaconStat)
        assert result.deposited_validators == 100
        assert result.beacon_validators == 90

    def test_get_deposits_reserve_target(self):
        contract = _mock_contract()
        contract.functions.getDepositsReserveTarget.return_value.call.return_value = 42
        result = LidoContract.get_deposits_reserve_target(contract, block_identifier="latest")
        assert result == 42

    def test_get_balance_stats(self):
        contract = _mock_contract()
        contract.functions.getBalanceStats.return_value.call.return_value = _BalanceStatsTuple(100, 90, 32, 10)
        result = LidoContract.get_balance_stats(contract, block_identifier="latest")
        assert isinstance(result, BalanceStats)
        assert result.cl_validators_balance_at_last_report == 100
        assert result.cl_pending_balance_at_last_report == 90
        assert result.deposited_since_last_report == 32
        assert result.deposited_for_current_report == 10


# ---------------------------------------------------------------------------
# BurnerContract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBurnerContract:
    def test_get_shares_requested_to_burn(self):
        contract = _mock_contract()
        contract.functions.getSharesRequestedToBurn.return_value.call.return_value = _SharesRequestedToBurnTuple(
            100, 200
        )
        result = BurnerContract.get_shares_requested_to_burn(contract, block_identifier="latest")
        assert isinstance(result, SharesRequestedToBurn)
        assert result.cover_shares == 100
        assert result.non_cover_shares == 200


# ---------------------------------------------------------------------------
# OracleReportSanityCheckerContract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOracleReportSanityCheckerContract:
    def test_get_oracle_report_limits(self):
        contract = _mock_contract()
        raw = _OracleReportLimitsTuple(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15)
        contract.functions.getOracleReportLimits.return_value.call.return_value = raw
        result = OracleReportSanityCheckerContract.get_oracle_report_limits(contract, block_identifier="latest")
        assert isinstance(result, OracleReportLimits)
        assert result.exited_eth_amount_per_day_limit == 1
        assert result.exited_validator_eth_amount_limit == 15


# ---------------------------------------------------------------------------
# WithdrawalQueueNftContract — remaining pass-through methods
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWithdrawalQueueNftContractPassThroughs:
    def test_unfinalized_steth(self):
        contract = _mock_contract()
        contract.functions.unfinalizedStETH.return_value.call.return_value = 500
        result = WithdrawalQueueNftContract.unfinalized_steth(contract, block_identifier="latest")
        assert result == 500

    def test_bunker_mode_since_timestamp(self):
        contract = _mock_contract()
        contract.functions.bunkerModeSinceTimestamp.return_value.call.return_value = 9999
        result = WithdrawalQueueNftContract.bunker_mode_since_timestamp(contract, block_identifier="latest")
        assert result == 9999

    def test_get_last_finalized_request_id(self):
        contract = _mock_contract()
        contract.functions.getLastFinalizedRequestId.return_value.call.return_value = 7
        result = WithdrawalQueueNftContract.get_last_finalized_request_id(contract, block_identifier="latest")
        assert result == 7

    def test_get_withdrawal_status(self):
        contract = _mock_contract()
        raw = _WithdrawalRequestStatusTuple(100, 50, _ADDR, 1000, False, False)
        contract.functions.getWithdrawalStatus.return_value.call.return_value = [raw]
        result = WithdrawalQueueNftContract.get_withdrawal_status(contract, 1, block_identifier="latest")
        assert isinstance(result, WithdrawalRequestStatus)
        assert result.amount_of_st_eth == 100
        assert result.amount_of_shares == 50

    def test_get_last_request_id(self):
        contract = _mock_contract()
        contract.functions.getLastRequestId.return_value.call.return_value = 42
        result = WithdrawalQueueNftContract.get_last_request_id(contract, block_identifier="latest")
        assert result == 42

    def test_is_paused(self):
        contract = _mock_contract()
        contract.functions.isPaused.return_value.call.return_value = True
        result = WithdrawalQueueNftContract.is_paused(contract, block_identifier="latest")
        assert result is True

    def test_max_batches_length(self):
        contract = _mock_contract()
        contract.functions.MAX_BATCHES_LENGTH.return_value.call.return_value = 36
        result = WithdrawalQueueNftContract.max_batches_length(contract, block_identifier="latest")
        assert result == 36


# ---------------------------------------------------------------------------
# BaseOracleContract — common oracle methods
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBaseOracleContract:
    def test_get_consensus_contract(self):
        contract = _mock_contract()
        contract.functions.getConsensusContract.return_value.call.return_value = _ADDR
        result = BaseOracleContract.get_consensus_contract(contract, block_identifier="latest")
        assert result == _ADDR

    def test_submit_data_role(self):
        contract = _mock_contract()
        contract.functions.SUBMIT_DATA_ROLE.return_value.call.return_value = _ROLE
        result = BaseOracleContract.submit_data_role(contract, block_identifier="latest")
        assert result == _ROLE

    def test_has_role(self):
        contract = _mock_contract()
        contract.functions.hasRole.return_value.call.return_value = True
        result = BaseOracleContract.has_role(contract, _ROLE, _ADDR, block_identifier="latest")
        assert result is True

    def test_get_contract_version(self):
        contract = _mock_contract()
        contract.functions.getContractVersion.return_value.call.return_value = 3
        result = BaseOracleContract.get_contract_version(contract, block_identifier="latest")
        assert result == 3

    def test_get_consensus_version(self):
        contract = _mock_contract()
        contract.functions.getConsensusVersion.return_value.call.return_value = 2
        result = BaseOracleContract.get_consensus_version(contract, block_identifier="latest")
        assert result == 2

    def test_submit_report_data(self):
        contract = _mock_contract()
        tx = MagicMock()
        contract.functions.submitReportData.return_value = tx
        result = BaseOracleContract.submit_report_data(contract, (1, 2, 3), 3)
        assert result == tx

    def test_get_last_processing_ref_slot(self):
        contract = _mock_contract()
        contract.functions.getLastProcessingRefSlot.return_value.call.return_value = 999
        result = BaseOracleContract.get_last_processing_ref_slot(contract, block_identifier="latest")
        assert result == 999


# ---------------------------------------------------------------------------
# AccountingOracleContract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAccountingOracleContract:
    def test_get_processing_state(self):
        contract = _mock_contract()
        raw = _AccountingProcessingStateTuple(1, 2, b"\x00" * 32, False, b"\x00" * 32, 0, False, 0, 0)
        contract.functions.getProcessingState.return_value.call.return_value = raw
        result = AccountingOracleContract.get_processing_state(contract, block_identifier="latest")
        assert isinstance(result, AccountingProcessingState)
        assert result.current_frame_ref_slot == 1

    def test_submit_report_extra_data_empty(self):
        contract = _mock_contract()
        tx = MagicMock()
        contract.functions.submitReportExtraDataEmpty.return_value = tx
        result = AccountingOracleContract.submit_report_extra_data_empty(contract)
        assert result == tx

    def test_submit_report_extra_data_list(self):
        contract = _mock_contract()
        tx = MagicMock()
        contract.functions.submitReportExtraDataList.return_value = tx
        result = AccountingOracleContract.submit_report_extra_data_list(contract, b"\xab\xcd")
        assert result == tx


# ---------------------------------------------------------------------------
# VaultHubContract — remaining 5 event methods
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVaultHubRemainingEventMethods:
    @patch("src.providers.execution.contracts.vault_hub.get_events_in_range")
    def test_get_vault_fee_updated_events(self, mock_get_events):
        log = _make_log(
            {
                "vault": _DUMMY_VAULT,
                "preInfraFeeBP": 10,
                "infraFeeBP": 11,
                "preLiquidityFeeBP": 20,
                "liquidityFeeBP": 21,
                "preReservationFeeBP": 5,
                "reservationFeeBP": 6,
            }
        )
        mock_get_events.return_value = [log]
        result = VaultHubContract.get_vault_fee_updated_events(_mock_contract(), _FROM_BLOCK, _TO_BLOCK)
        assert len(result) == 1
        assert isinstance(result[0], VaultFeesUpdatedEvent)

    @patch("src.providers.execution.contracts.vault_hub.get_events_in_range")
    def test_get_vault_rebalanced_events(self, mock_get_events):
        log = _make_log({"vault": _DUMMY_VAULT, "sharesBurned": 10, "etherWithdrawn": 20})
        mock_get_events.return_value = [log]
        result = VaultHubContract.get_vault_rebalanced_events(_mock_contract(), _FROM_BLOCK, _TO_BLOCK)
        assert len(result) == 1
        assert isinstance(result[0], VaultRebalancedEvent)

    @patch("src.providers.execution.contracts.vault_hub.get_events_in_range")
    def test_get_bad_debt_socialized_events(self, mock_get_events):
        log = _make_log({"vaultDonor": _DUMMY_VAULT, "vaultAcceptor": _DUMMY_VAULT, "badDebtShares": 3})
        mock_get_events.return_value = [log]
        result = VaultHubContract.get_bad_debt_socialized_events(_mock_contract(), _FROM_BLOCK, _TO_BLOCK)
        assert len(result) == 1
        assert isinstance(result[0], BadDebtSocializedEvent)

    @patch("src.providers.execution.contracts.vault_hub.get_events_in_range")
    def test_get_bad_debt_written_off_events(self, mock_get_events):
        log = _make_log({"vault": _DUMMY_VAULT, "badDebtShares": 5})
        mock_get_events.return_value = [log]
        result = VaultHubContract.get_bad_debt_written_off_to_be_internalized_events(
            _mock_contract(), _FROM_BLOCK, _TO_BLOCK
        )
        assert len(result) == 1
        assert isinstance(result[0], BadDebtWrittenOffToBeInternalizedEvent)

    @patch("src.providers.execution.contracts.vault_hub.get_events_in_range")
    def test_get_vault_connected_events(self, mock_get_events):
        log = _make_log(
            {
                "vault": _DUMMY_VAULT,
                "shareLimit": 100,
                "reserveRatioBP": 1000,
                "forcedRebalanceThresholdBP": 2000,
                "infraFeeBP": 50,
                "liquidityFeeBP": 60,
                "reservationFeeBP": 10,
            }
        )
        mock_get_events.return_value = [log]
        result = VaultHubContract.get_vault_connected_events(_mock_contract(), _FROM_BLOCK, _TO_BLOCK)
        assert len(result) == 1
        assert isinstance(result[0], VaultConnectedEvent)


# ---------------------------------------------------------------------------
# CSFeeDistributorContract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCSFeeDistributorContract:
    def test_shares_to_distribute(self):
        contract = _mock_contract()
        contract.functions.pendingSharesToDistribute.return_value.call.return_value = 999
        result = CSFeeDistributorContract.shares_to_distribute(contract, block_identifier="latest")
        assert result == 999

    def test_tree_root(self):
        contract = _mock_contract()
        contract.functions.treeRoot.return_value.call.return_value = b"\xaa" * 32
        result = CSFeeDistributorContract.tree_root(contract, block_identifier="latest")
        assert result == HexBytes(b"\xaa" * 32)

    def test_tree_cid(self):
        contract = _mock_contract()
        contract.functions.treeCid.return_value.call.return_value = "QmTest"
        result = CSFeeDistributorContract.tree_cid(contract, block_identifier="latest")
        assert result == "QmTest"

    def test_oracle_returns_checksum_address(self):
        contract = _mock_contract()
        contract.functions.ORACLE.return_value.call.return_value = "0x" + "ab" * 20
        result = CSFeeDistributorContract.oracle(contract, block_identifier="latest")
        assert result.startswith("0x")
        assert len(result) == 42


# ---------------------------------------------------------------------------
# CSAccountingContract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCSAccountingContract:
    def test_fee_distributor(self):
        contract = _mock_contract()
        contract.functions.FEE_DISTRIBUTOR.return_value.call.return_value = "0x" + "cd" * 20
        result = CSAccountingContract.fee_distributor(contract, block_identifier="latest")
        assert result.startswith("0x")

    def test_get_bond_curve_id(self):
        contract = _mock_contract()
        contract.functions.getBondCurveId.return_value.call.return_value = 5
        result = CSAccountingContract.get_bond_curve_id(contract, NodeOperatorId(1), block_identifier="latest")
        assert result == 5


# ---------------------------------------------------------------------------
# CSFeeOracleContract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCSFeeOracleContract:
    def test_is_paused(self):
        contract = _mock_contract()
        contract.functions.isPaused.return_value.call.return_value = False
        result = CSFeeOracleContract.is_paused(contract, block_identifier="latest")
        assert result is False

    def test_strikes(self):
        contract = _mock_contract()
        contract.functions.STRIKES.return_value.call.return_value = "0x" + "ef" * 20
        result = CSFeeOracleContract.strikes(contract, block_identifier="latest")
        assert result.startswith("0x")


# ---------------------------------------------------------------------------
# CSModuleContract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCSModuleContract:
    def test_accounting(self):
        contract = _mock_contract()
        contract.functions.ACCOUNTING.return_value.call.return_value = "0x" + "11" * 20
        result = CSModuleContract.accounting(contract, block_identifier="latest")
        assert result.startswith("0x")

    def test_parameters_registry(self):
        contract = _mock_contract()
        contract.functions.PARAMETERS_REGISTRY.return_value.call.return_value = "0x" + "22" * 20
        result = CSModuleContract.parameters_registry(contract, block_identifier="latest")
        assert result.startswith("0x")

    def test_is_paused(self):
        contract = _mock_contract()
        contract.functions.isPaused.return_value.call.return_value = True
        result = CSModuleContract.is_paused(contract, block="latest")
        assert result is True


# ---------------------------------------------------------------------------
# CSStrikesContract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCSStrikesContract:
    def test_tree_root(self):
        contract = _mock_contract()
        contract.functions.treeRoot.return_value.call.return_value = b"\xbb" * 32
        result = CSStrikesContract.tree_root(contract, block_identifier="latest")
        assert result == HexBytes(b"\xbb" * 32)

    def test_tree_cid(self):
        contract = _mock_contract()
        contract.functions.treeCid.return_value.call.return_value = "QmStrikes"
        result = CSStrikesContract.tree_cid(contract, block_identifier="latest")
        assert result == "QmStrikes"


# ---------------------------------------------------------------------------
# DataBusContract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDataBusContract:
    def test_send_message(self):
        contract = _mock_contract()
        tx = MagicMock()
        contract.functions.sendMessage.return_value = tx
        result = DataBusContract.send_message(contract, b"\x01" * 32, b"\xde\xad")
        assert result == tx


# ---------------------------------------------------------------------------
# CuratedStakingModuleContract — remaining pass-throughs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCuratedStakingModulePassThroughs:
    def test_get_type(self):
        contract = _mock_contract()
        contract.functions.getType.return_value.call.return_value = b"curated-onchain-v1"
        result = CuratedStakingModuleContract.get_type(contract, block_identifier="latest")
        assert result == b"curated-onchain-v1"

    def test_get_meta_registry_address(self):
        contract = _mock_contract()
        contract.functions.META_REGISTRY.return_value.call.return_value = _ADDR
        result = CuratedStakingModuleContract.get_meta_registry_address(contract, block_identifier="latest")
        assert result == _ADDR
