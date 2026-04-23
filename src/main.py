import sys
from decimal import getcontext

import variables
from constants import PRECISION_E27
from metrics.logging import logging
from type_aliases import OracleModuleName


logger = logging.getLogger(__name__)

getcontext().prec = PRECISION_E27


def main(module: OracleModuleName):
    # pylint: disable=import-outside-toplevel,too-many-return-statements

    if module is OracleModuleName.CHECK:
        errors = variables.check_uri_required_variables()
        variables.raise_from_errors(errors)
        from modules.checks import entrypoint as check_entrypoint

        return check_entrypoint.run()

    if module is OracleModuleName.PERFORMANCE_WEB_SERVER:
        errors = variables.check_perf_web_server_required_variables()
        variables.raise_from_errors(errors)
        from modules.sidecars.performance.web import entrypoint as web_entrypoint

        return web_entrypoint.run()

    if module is OracleModuleName.PERFORMANCE_COLLECTOR:
        errors = variables.check_perf_collector_required_variables()
        variables.raise_from_errors(errors)
        from modules.sidecars.performance.collector import entrypoint as collector_entrypoint

        return collector_entrypoint.run()

    # TODO: this function can be splitted or simplified or whatever.
    errors = variables.check_all_required_variables(module)
    variables.raise_from_errors(errors)

    if module is OracleModuleName.ACCOUNTING:
        from modules.oracles.accounting import entrypoint as accounting_entrypoint

        return accounting_entrypoint.run()

    if module is OracleModuleName.EJECTOR:
        from modules.oracles.ejector import entrypoint as ejector_entrypoint

        return ejector_entrypoint.run()

    if module is OracleModuleName.CSM:
        from modules.oracles.staking_modules.community_staking import entrypoint as csm_entrypoint

        return csm_entrypoint.run()

    if module is OracleModuleName.CM:
        from modules.oracles.staking_modules.curated import entrypoint as cm_entrypoint

        return cm_entrypoint.run()


if __name__ == '__main__':
    module_name_arg = sys.argv[-1]
    if module_name_arg not in OracleModuleName:
        msg = f'Last arg should be one of {[str(item) for item in OracleModuleName]}, received {module_name_arg}.'
        logger.error({'msg': msg})
        raise ValueError(msg)

    raise SystemExit(main(OracleModuleName(module_name_arg)))
