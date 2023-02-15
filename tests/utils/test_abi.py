import pytest

from src.utils.abi import get_function_output_names
from src.web3_extentions import LidoContracts

pytestmark = pytest.mark.unit


def test_get_function_output_names():
    outputs = get_function_output_names(LidoContracts.load_abi("OracleReportSanityChecker"), 'getOracleReportLimits')
    assert outputs == ['churnValidatorsPerDayLimit',
                       'oneOffCLBalanceDecreaseBPLimit',
                       'annualBalanceIncreaseBPLimit',
                       'shareRateDeviationBPLimit',
                       'requestTimestampMargin',
                       'maxPositiveTokenRebase',
                       'maxValidatorExitRequestsPerReport',
                       'maxAccountingExtraDataListItemsCount']
