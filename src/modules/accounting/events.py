from dataclasses import dataclass
from hexbytes import HexBytes

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
