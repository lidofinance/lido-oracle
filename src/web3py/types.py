from web3 import Web3 as _Web3

from src.providers.performance.client import PerformanceClient
from src.web3py.extensions import (
    IPFS,
    ConsensusClientModule,
    KeysAPIClientModule,
    LidoContracts,
    LidoValidatorsProvider,
    SignerModule,
    StakingModuleContracts,
    TelemetryDataBus,
    TransactionUtils,
)


class Web3Base(_Web3):
    transaction: TransactionUtils
    cc: ConsensusClientModule
    kac: KeysAPIClientModule
    telemetry_data_bus: TelemetryDataBus
    signer: SignerModule


class Web3(Web3Base):
    lido_contracts: LidoContracts
    lido_validators: LidoValidatorsProvider
    ipfs: IPFS


class Web3StakingModule(Web3Base):
    staking_module: StakingModuleContracts
    performance: PerformanceClient
    ipfs: IPFS
