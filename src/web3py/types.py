from web3 import Web3 as _Web3

from src.providers.performance.client import PerformanceClient
from src.web3py.extensions import (
    StakingModuleContracts,
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
    staking_module: StakingModuleContracts
    ipfs: IPFS
    performance: PerformanceClient
