from time import sleep
from typing import Optional, List

from prometheus_client import start_http_server
from web3 import Web3
from web3_multi_provider import MultiProvider

from src import variables
from src.contracts import contracts
from src.metrics.logging import logging
from src.metrics.healthcheck_server import start_pulse_server, pulse
from src.metrics.prometheus.basic import FINALIZED_EPOCH_NUMBER, SLOT_NUMBER

from src.metrics.prometheus.basic import EXCEPTIONS_COUNT
from src.modules.accounting import Accounting
from src.modules.ejection import Ejector
from src.modules.interface import OracleModule
from src.protocol_upgrade_checker import wait_for_withdrawals
from src.providers.beacon import BeaconChainClient, NoSlotsFound
from src.providers.web3_middleware import add_requests_metric_middleware
from src.web3_utils.typings import EpochNumber, SlotNumber
from src.variables import DAEMON, WEB3_PROVIDER_URI, BEACON_NODE

logger = logging.getLogger(__name__)


class Oracle:
    _last_finalized_epoch: EpochNumber = 0

    def __init__(self, web3: Web3, beacon_chain_client: BeaconChainClient):
        self._w3 = web3
        self._beacon_chain_client = beacon_chain_client

        self.modules: List[OracleModule] = [
            Accounting(self._w3, self._beacon_chain_client),
            Ejector(self._w3, self._beacon_chain_client),
        ]

    def _fetch_beacon_specs(self):
        _, self.slots_per_epoch, self.seconds_per_slot, _ = contracts.oracle.functions.getBeaconSpec().call()
        # _, self.slots_per_epoch, self.seconds_per_slot, _ = contracts.validator_exit_bus.functions.getBeaconSpec().call()

    def run_as_daemon(self):
        while True:
            pulse()
            logger.info({'msg': 'Run cycle.'})
            self.run_cycle()

    def run_cycle(self):
        self._fetch_beacon_specs()
        epoch = self._fetch_next_finalized_epoch()
        logger.info({'msg': 'Get finalized epoch.', 'value': epoch})

        try:
            self.run_once(epoch)
        except KeyboardInterrupt as error:
            logger.error({'msg': 'Key interrupt.', 'error': error})
            raise KeyboardInterrupt from error
        except NoSlotsFound as error:
            logger.error({'msg': 'No slots for current epoch.', 'error': error})
        except Exception as error:
            logger.error({'msg': 'Unexpected exception.', 'error': error})
            raise Exception from error

    def _fetch_next_finalized_epoch(self) -> EpochNumber:
        while True:
            current_finalized_epoch = EpochNumber(int(self._beacon_chain_client.get_head_finality_checkpoints()['finalized']['epoch']))

            if current_finalized_epoch > self._last_finalized_epoch:
                self._last_finalized_epoch = current_finalized_epoch

                return current_finalized_epoch
            else:
                sleep_time = self.slots_per_epoch * self.seconds_per_slot / 4
                logger.info({'msg': f'Waiting for next finalized epoch. Sleep for {sleep_time} sec.'})
                sleep(sleep_time)

    def run_once(self, epoch: Optional[EpochNumber] = None):
        if epoch is None:
            epoch = EpochNumber(int(self._beacon_chain_client.get_head_finality_checkpoints()['finalized']['epoch']))

        FINALIZED_EPOCH_NUMBER.set(epoch)
        slot = self._beacon_chain_client.get_first_slot_in_epoch(epoch, self.slots_per_epoch)
        slot_number = SlotNumber(int(slot['message']['slot']))
        SLOT_NUMBER.set(slot_number)
        block_hash = slot['message']['body']['execution_payload']['block_hash']

        logger.info({
            'msg': 'Fetch first proposed slot in epoch.',
            'epoch': epoch,
            'slot': slot_number,
            'block_hash': block_hash,
        })

        for module in self.modules:
            try:
                module.run_module(slot_number, block_hash)
            except Exception as error:
                EXCEPTIONS_COUNT.labels(module.__class__.__name__).inc()
                logger.error({'msg': f'Module {module.__class__.__name__} failed.', 'error': str(error)})


if __name__ == '__main__':
    logger.info({'msg': 'Oracle startup.'})

    logger.info({'msg': f'Start healthcheck server for Docker container on port {variables.HEALTHCHECK_SERVER_PORT}'})
    start_pulse_server()

    logger.info({'msg': f'Start http server with prometheus metrics on port {variables.PROMETHEUS_PORT}'})
    start_http_server(variables.PROMETHEUS_PORT)

    logger.info({'msg': 'Initialize multi web3 provider.'})
    w3 = Web3(MultiProvider(WEB3_PROVIDER_URI))

    logger.info({'msg': 'Add metrics middleware for ETH1 requests.'})
    add_requests_metric_middleware(w3)

    logger.info({'msg': 'Check protocol version.'})
    wait_for_withdrawals(w3)

    logger.info({'msg': 'Initialize contracts.'})
    contracts.initialize(w3)

    logger.info({'msg': 'Initialize Consensus Layer client.'})
    beacon_client = BeaconChainClient(BEACON_NODE)

    logger.info({'msg': 'Initialize Oracle.'})
    oracle = Oracle(w3, beacon_client)

    if DAEMON:
        logger.info({'msg': 'Run Oracle as Daemon.'})
        oracle.run_as_daemon()
    else:
        logger.info({'msg': 'Run Oracle once.'})
        oracle.run_cycle()
