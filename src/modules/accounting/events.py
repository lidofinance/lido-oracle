from dataclasses import dataclass
from hexbytes import HexBytes
from typing import Any, Dict, Union
from web3.types import EventData

@dataclass(frozen=True)
class EventBase:
    event: str
    log_index: int
    transaction_index: int
    transaction_hash: HexBytes
    address: str
    block_hash: HexBytes
    block_number: int

    @classmethod
    def _extract_common(cls, log: EventData) -> Dict[str, Any]:
        """Extract fields common to all events."""
        return {
            "event": log["event"],
            "log_index": log["logIndex"],
            "transaction_index": log["transactionIndex"],
            "transaction_hash": log["transactionHash"],
            "address": log["address"],
            "block_hash": log["blockHash"],
            "block_number": log["blockNumber"],
        }


@dataclass(frozen=True)
class MintedSharesOnVaultEvent(EventBase):
    vault: str
    amount_of_shares: int
    locked_amount: int

    @classmethod
    def from_log(cls, log: EventData) -> "MintedSharesOnVaultEvent":
        args = log["args"]
        return cls(
            vault=args["vault"],
            amount_of_shares=args["amountOfShares"],
            locked_amount=args["lockedAmount"],
            **cls._extract_common(log),
        )


@dataclass(frozen=True)
class BurnedSharesOnVaultEvent(EventBase):
    vault: str
    amount_of_shares: int

    @classmethod
    def from_log(cls, log: EventData) -> "BurnedSharesOnVaultEvent":
        args = log["args"]
        return cls(
            vault=args["vault"],
            amount_of_shares=args["amountOfShares"],
            **cls._extract_common(log),
        )


@dataclass(frozen=True)
class VaultFeesUpdatedEvent(EventBase):
    vault: str
    pre_infra_fee_bp: int
    infra_fee_bp: int
    pre_liquidity_fee_bp: int
    liquidity_fee_bp: int
    pre_reservation_fee_bp: int
    reservation_fee_bp: int

    @classmethod
    def from_log(cls, log: EventData) -> "VaultFeesUpdatedEvent":
        args = log["args"]
        return cls(
            vault=args["vault"],
            pre_infra_fee_bp=args["preInfraFeeBP"],
            infra_fee_bp=args["infraFeeBP"],
            pre_liquidity_fee_bp=args["preLiquidityFeeBP"],
            liquidity_fee_bp=args["liquidityFeeBP"],
            pre_reservation_fee_bp=args["preReservationFeeBP"],
            reservation_fee_bp=args["reservationFeeBP"],
            **cls._extract_common(log),
        )


@dataclass(frozen=True)
class VaultRebalancedEvent(EventBase):
    vault: str
    shares_burned: int
    ether_withdrawn: int

    @classmethod
    def from_log(cls, log: EventData) -> "VaultRebalancedEvent":
        args = log["args"]
        return cls(
            vault=args["vault"],
            shares_burned=args["sharesBurned"],
            ether_withdrawn=args["etherWithdrawn"],
            **cls._extract_common(log),
        )


@dataclass(frozen=True)
class BadDebtSocializedEvent(EventBase):
    vault_donor: str
    vault_acceptor: str
    bad_debt_shares: int

    @classmethod
    def from_log(cls, log: EventData) -> "BadDebtSocializedEvent":
        args = log["args"]
        return cls(
            vault_donor=args["vaultDonor"],
            vault_acceptor=args["vaultAcceptor"],
            bad_debt_shares=args["badDebtShares"],
            **cls._extract_common(log),
        )


@dataclass(frozen=True)
class BadDebtWrittenOffToBeInternalizedEvent(EventBase):
    vault: str
    bad_debt_shares: int

    @classmethod
    def from_log(cls, log: EventData) -> "BadDebtWrittenOffToBeInternalizedEvent":
        args = log["args"]
        return cls(
            vault=args["vault"],
            bad_debt_shares=args["badDebtShares"],
            **cls._extract_common(log),
        )

VaultEventType = Union[
    MintedSharesOnVaultEvent,
    BurnedSharesOnVaultEvent,
    VaultFeesUpdatedEvent,
    VaultRebalancedEvent,
    BadDebtSocializedEvent,
    BadDebtWrittenOffToBeInternalizedEvent
]
