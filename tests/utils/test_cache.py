import random
import pytest

from hexbytes import HexBytes
from web3.types import BlockIdentifier

from src.providers.execution.base_interface import ContractInterface
from src.utils.cache import clear_global_cache, global_lru_cache


class Calc:
    @global_lru_cache(maxsize=2)
    def get(self, a, b):
        return a + b


@pytest.mark.unit
def test_clear_global_cache():
    calc = Calc()
    calc.get(1, 2)
    assert calc.get.cache_info().currsize == 1

    calc.get(2, 1)
    assert calc.get.cache_info().currsize == 2

    clear_global_cache()

    assert calc.get.cache_info().currsize == 0


class Contract(ContractInterface):
    def __init__(self):
        pass

    @global_lru_cache(maxsize=5)
    def func(self, block_identifier: BlockIdentifier = 'latest'):
        pass

    @global_lru_cache(maxsize=1)
    def func_1(self, module_id: int, block_identifier: BlockIdentifier = 'latest'):
        return random.random()


@pytest.mark.unit
def test_cache_do_not_cache_contract_with_relative_blocks():
    c = Contract()

    c.func()
    assert c.func.cache_info().currsize == 0
    c.func(block_identifier=HexBytes('11'))
    c.func(block_identifier=HexBytes('11'))
    c.func(block_identifier=HexBytes('22'))
    c.func(block_identifier='latest')
    c.func(block_identifier='finalized')
    c.func('finalized')
    assert c.func.cache_info().currsize == 2

    c.func(HexBytes('22'))
    c.func(HexBytes('11'))
    c.func(HexBytes('33'))
    c.func('finalized')
    assert c.func.cache_info().currsize == 3

    result_1 = c.func_1(1, 1)
    result_2 = c.func_1(1)
    result_3 = c.func_1(1, 1)

    assert result_1 != result_2
    assert result_1 == result_3
