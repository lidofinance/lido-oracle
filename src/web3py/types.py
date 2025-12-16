from web3 import Web3 as _Web3

from src.providers.performance.client import PerformanceClient
from src.web3py.extensions import (
    CSMContracts,
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
    csm: CSMContracts
    ipfs: IPFS
    performance: PerformanceClient
