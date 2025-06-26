from dataclasses import dataclass
from hexbytes import HexBytes

from src.utils.types import bytes_to_hex_str


@dataclass
class TokenRebasedEvent:
    report_timestamp: int
    time_elapsed: int
    pre_total_shares: int
    pre_total_ether: int
    post_total_shares: int
    post_total_ether: int
    shares_minted_as_fees: int
    event: str
    log_index: int
    transaction_index: int
    transaction_hash: HexBytes
    address: str
    block_hash: str
    block_number: int

    @classmethod
    def from_log(cls, log: dict) -> "TokenRebasedEvent":
        args = log["args"]
        return cls(
            report_timestamp=args["reportTimestamp"],
            time_elapsed=args["timeElapsed"],
            pre_total_shares=args["preTotalShares"],
            pre_total_ether=args["preTotalEther"],
            post_total_shares=args["postTotalShares"],
            post_total_ether=args["postTotalEther"],
            shares_minted_as_fees=args["sharesMintedAsFees"],
            event=log["event"],
            log_index=log["logIndex"],
            transaction_index=log["transactionIndex"],
            transaction_hash=log["transactionHash"],
            address=log["address"],
            block_hash=bytes_to_hex_str(log["blockHash"]),
            block_number=log["blockNumber"],
        )

@dataclass
class MintedSharesOnVaultEvent:
    vault: str
    amount_of_shares: int
    locked_amount: int
    event: str
    log_index: int
    transaction_index: int
    transaction_hash: HexBytes
    address: str
    block_hash: HexBytes
    block_number: int

    @classmethod
    def from_log(cls, log: dict) -> "MintedSharesOnVaultEvent":
        args = log["args"]
        return cls(
            vault=args["vault"],
            amount_of_shares=args["amountOfShares"],
            locked_amount=args["lockedAmount"],
            event=log["event"],
            log_index=log["logIndex"],
            transaction_index=log["transactionIndex"],
            transaction_hash=log["transactionHash"],
            address=log["address"],
            block_hash=log["blockHash"],
            block_number=log["blockNumber"],
        )

@dataclass
class BurnedSharesOnVaultEvent:
    vault: str
    amount_of_shares: int
    event: str
    log_index: int
    transaction_index: int
    transaction_hash: HexBytes
    address: str
    block_hash: HexBytes
    block_number: int

    @classmethod
    def from_log(cls, log: dict) -> "BurnedSharesOnVaultEvent":
        args = log["args"]
        return cls(
            vault=args["vault"],
            amount_of_shares=args["amountOfShares"],
            event=log["event"],
            log_index=log["logIndex"],
            transaction_index=log["transactionIndex"],
            transaction_hash=log["transactionHash"],
            address=log["address"],
            block_hash=log["blockHash"],
            block_number=log["blockNumber"],
        )

@dataclass
class VaultFeesUpdatedEvent:
    vault: str
    pre_infra_fee_bp: int
    infra_fee_bp: int
    pre_liquidity_fee_bp: int
    liquidity_fee_bp: int
    pre_reservation_fee_bp: int
    reservation_fee_bp: int
    event: str
    log_index: int
    transaction_index: int
    transaction_hash: HexBytes
    address: str
    block_hash: HexBytes
    block_number: int

    @classmethod
    def from_log(cls, log: dict) -> "VaultFeesUpdatedEvent":
        args = log["args"]
        return cls(
            vault=args["vault"],
            pre_infra_fee_bp=args["preInfraFeeBP"],
            infra_fee_bp=args["infraFeeBP"],
            pre_liquidity_fee_bp=args["preLiquidityFeeBP"],
            liquidity_fee_bp=args["liquidityFeeBP"],
            pre_reservation_fee_bp=args["preReservationFeeBP"],
            reservation_fee_bp=args["reservationFeeBP"],
            event=log["event"],
            log_index=log["logIndex"],
            transaction_index=log["transactionIndex"],
            transaction_hash=log["transactionHash"],
            address=log["address"],
            block_hash=log["blockHash"],
            block_number=log["blockNumber"],
        )
