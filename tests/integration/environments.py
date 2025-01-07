from dataclasses import dataclass
from typing import Dict


@dataclass
class Environment:
    execution_client_uri: str
    chain_id: int
    lido_locator_address: str


ENVIRONMENTS = {
    'mainnet': Environment(
        execution_client_uri='https://eth.drpc.org',
        chain_id=1,
        lido_locator_address='0xC1d0b3DE6792Bf6b4b37EccdcC24e45978Cfd2Eb',
    ),
    'holesky_vaults_devnet_2': Environment(
        execution_client_uri='https://holesky.drpc.org',
        chain_id=17000,
        lido_locator_address='0x012428B1810377a69c0Af28580293CB58D816dED',
    ),
}
