from web3 import Web3 as _Web3

from src.web3_extentions import LidoContracts, TransactionUtils, ConsensusClientModule, KeysAPIClientModule


class Web3(_Web3):
    lido_contracts: LidoContracts
    transaction: TransactionUtils
    cc: ConsensusClientModule
    kac: KeysAPIClientModule
