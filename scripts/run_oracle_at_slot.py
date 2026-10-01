#!/usr/bin/env python3
"""
Run a single Accounting or Ejector oracle cycle pinned to a specific slot.

Forces DAEMON=False (single cycle, then exit) and configures Prometheus / healthcheck
servers to use free ports, so multiple instances (e.g. accounting + ejector)
can be started in parallel without port clashes.

Usage:
    poetry run python scripts/run_oracle_at_slot.py accounting
    poetry run python scripts/run_oracle_at_slot.py ejector --slot 8500000

Env vars (EXECUTION_CLIENT_URI, CONSENSUS_CLIENT_URI, KEYS_API_URI, LIDO_LOCATOR_ADDRESS, ...)
must already be exported, e.g. via `set -a && source .env && set +a`.
"""

import argparse
import logging
import os
import socket
import sys


GREEN = '\033[92m'
RESET = '\033[0m'


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('module', choices=['accounting', 'ejector'], help='Oracle module to run.')
    parser.add_argument(
        '--slot',
        type=int,
        default=None,
        help='Reference slot to build the report for. Defaults to the latest finalized slot.',
    )
    parser.add_argument('--prometheus-port', type=int, default=None, help='Defaults to a free port.')
    parser.add_argument('--healthcheck-port', type=int, default=None, help='Defaults to a free port.')
    return parser.parse_args()


class ReportLogCapture(logging.Handler):
    """
    Watches for the 'Build report.' log record, then the next 'Build `submitReport(...)`' record,
    so their contents can be printed clearly at the end of the run.
    """

    def __init__(self) -> None:
        super().__init__()
        self.report_value: str | None = None
        self.submit_message: str | None = None

    def emit(self, record: logging.LogRecord) -> None:
        if not isinstance(record.msg, dict):
            return
        msg_field = record.msg.get('msg')

        if self.report_value is None and msg_field == 'Build report.':
            self.report_value = str(record.msg.get('value'))
            return

        if (
            self.report_value is not None
            and self.submit_message is None
            and isinstance(msg_field, str)
            and msg_field.startswith('Build `submitReport(')
        ):
            self.submit_message = msg_field

    def print_summary(self) -> None:
        if self.report_value is not None:
            print(f'{GREEN}Build report. value={self.report_value}{RESET}')
        if self.submit_message is not None:
            print(f'{GREEN}{self.submit_message}{RESET}')


def main() -> None:
    args = parse_args()

    prometheus_port = args.prometheus_port or find_free_port()
    healthcheck_port = args.healthcheck_port or find_free_port()

    # Must be set before `src.variables` (or anything importing it) is loaded,
    # since those values are read from the environment at import time.
    os.environ['DAEMON'] = 'False'
    # Force dry mode (no on-chain tx signing/sending) regardless of the caller's shell env.
    os.environ.pop('MEMBER_PRIV_KEY', None)
    os.environ.pop('MEMBER_PRIV_KEY_FILE', None)
    os.environ.pop('TELEMETRY_PRIV_KEY', None)
    os.environ.pop('TELEMETRY_PRIV_KEY_FILE', None)
    os.environ['PROMETHEUS_PORT'] = str(prometheus_port)
    os.environ['HEALTHCHECK_SERVER_PORT'] = str(healthcheck_port)

    print(
        f'[run_oracle_at_slot] module={args.module} slot={args.slot} '
        f'prometheus_port={prometheus_port} healthcheck_port={healthcheck_port}',
        file=sys.stderr,
    )

    # pylint: disable=import-outside-toplevel
    from src import variables
    from src.modules.oracles.common.consensus import ConsensusModule, logger as consensus_logger
    from src.types import BlockStamp, ReferenceBlockStamp, SlotNumber
    from src.utils.blockstamp import get_reference_blockstamp

    forced_ref_slot = SlotNumber(int(args.slot)) if args.slot else None

    def get_blockstamp_for_report(self: ConsensusModule, last_finalized_blockstamp: BlockStamp) -> ReferenceBlockStamp:
        """Patched: always build the report blockstamp for the forced reference slot."""
        converter = self._get_web3_converter(last_finalized_blockstamp)  # pylint: disable=protected-access

        ref_slot = forced_ref_slot or SlotNumber(last_finalized_blockstamp.slot_number)

        bs = get_reference_blockstamp(
            cc=self.w3.cc,
            ref_slot=ref_slot,
            ref_epoch=converter.get_epoch_by_slot(ref_slot),
            last_finalized_slot_number=last_finalized_blockstamp.slot_number,
            el=self.w3.eth,
        )
        consensus_logger.info({'msg': 'Calculate blockstamp for report.', 'value': bs})

        return bs

    ConsensusModule.get_blockstamp_for_report = get_blockstamp_for_report  # type: ignore[method-assign]
    report_capture = ReportLogCapture()
    logging.getLogger().addHandler(report_capture)

    try:
        from src.types import OracleModuleName

        if args.module == 'accounting':
            errors = variables.check_all_required_variables(OracleModuleName.ACCOUNTING)
            variables.raise_from_errors(errors)

            from src.modules.oracles.accounting import entrypoint as accounting_entrypoint

            accounting_entrypoint.run()
        else:
            errors = variables.check_all_required_variables(OracleModuleName.EJECTOR)
            variables.raise_from_errors(errors)

            from src.modules.oracles.ejector import entrypoint as ejector_entrypoint

            ejector_entrypoint.run()
    finally:
        report_capture.print_summary()


if __name__ == '__main__':
    main()
