import pytest
from eth_typing import BlockNumber
from hexbytes import HexBytes

from modules.oracles.accounting.events import (
    BadDebtSocializedEvent,
    BadDebtWrittenOffToBeInternalizedEvent,
    BurnedSharesOnVaultEvent,
    MintedSharesOnVaultEvent,
    VaultConnectedEvent,
    VaultFeesUpdatedEvent,
    VaultRebalancedEvent,
)


COMMON_FIELDS = {
    "event": "SomeEvent",
    "logIndex": 1,
    "transactionIndex": 2,
    "transactionHash": HexBytes("0xabcd"),
    "address": "0xDEAD",
    "blockHash": HexBytes("0x1234"),
    "blockNumber": BlockNumber(100),
}


def _log(args: dict) -> dict:
    return {**COMMON_FIELDS, "args": args}


@pytest.mark.unit
def test_minted_shares_on_vault_from_log():
    log = _log({"vault": "0xVault", "amountOfShares": 500, "lockedAmount": 200})
    event = MintedSharesOnVaultEvent.from_log(log)
    assert event.vault == "0xVault"
    assert event.amount_of_shares == 500
    assert event.locked_amount == 200
    assert event.block_number == BlockNumber(100)
    assert event.log_index == 1


@pytest.mark.unit
def test_burned_shares_on_vault_from_log():
    log = _log({"vault": "0xVault", "amountOfShares": 300})
    event = BurnedSharesOnVaultEvent.from_log(log)
    assert event.vault == "0xVault"
    assert event.amount_of_shares == 300
    assert event.transaction_index == 2


@pytest.mark.unit
def test_vault_fees_updated_from_log():
    log = _log(
        {
            "vault": "0xVault",
            "preInfraFeeBP": 100,
            "infraFeeBP": 150,
            "preLiquidityFeeBP": 200,
            "liquidityFeeBP": 250,
            "preReservationFeeBP": 300,
            "reservationFeeBP": 350,
        }
    )
    event = VaultFeesUpdatedEvent.from_log(log)
    assert event.vault == "0xVault"
    assert event.pre_infra_fee_bp == 100
    assert event.infra_fee_bp == 150
    assert event.pre_liquidity_fee_bp == 200
    assert event.liquidity_fee_bp == 250
    assert event.pre_reservation_fee_bp == 300
    assert event.reservation_fee_bp == 350


@pytest.mark.unit
def test_vault_rebalanced_from_log():
    log = _log({"vault": "0xVault", "sharesBurned": 400, "etherWithdrawn": 1_000_000})
    event = VaultRebalancedEvent.from_log(log)
    assert event.vault == "0xVault"
    assert event.shares_burned == 400
    assert event.ether_withdrawn == 1_000_000


@pytest.mark.unit
def test_bad_debt_socialized_from_log():
    log = _log({"vaultDonor": "0xDonor", "vaultAcceptor": "0xAcceptor", "badDebtShares": 50})
    event = BadDebtSocializedEvent.from_log(log)
    assert event.vault_donor == "0xDonor"
    assert event.vault_acceptor == "0xAcceptor"
    assert event.bad_debt_shares == 50


@pytest.mark.unit
def test_bad_debt_written_off_from_log():
    log = _log({"vault": "0xVault", "badDebtShares": 75})
    event = BadDebtWrittenOffToBeInternalizedEvent.from_log(log)
    assert event.vault == "0xVault"
    assert event.bad_debt_shares == 75


@pytest.mark.unit
def test_vault_connected_from_log():
    log = _log(
        {
            "vault": "0xVault",
            "shareLimit": 1000,
            "reserveRatioBP": 500,
            "forcedRebalanceThresholdBP": 300,
            "infraFeeBP": 100,
            "liquidityFeeBP": 200,
            "reservationFeeBP": 150,
        }
    )
    event = VaultConnectedEvent.from_log(log)
    assert event.vault == "0xVault"
    assert event.share_limit == 1000
    assert event.reserve_ratio_bp == 500
    assert event.forced_rebalance_threshold_bp == 300
    assert event.infra_fee_bp == 100
    assert event.liquidity_fee_bp == 200
    assert event.reservation_fee_bp == 150
