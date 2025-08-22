from web3 import Web3 as _Web3

from src.web3py.extensions import (
    CSM,
    ConsensusClientModule,
    KeysAPIClientModule,
    LidoContracts,
    LidoValidatorsProvider,
    TransactionUtils,
    IPFS,
)


class Web3(_Web3):
    lido_contracts: LidoContracts
    lido_validators: LidoValidatorsProvider
    transaction: TransactionUtils
    cc: ConsensusClientModule
    kac: KeysAPIClientModule
    csm: CSM
    ipfs: IPFS
