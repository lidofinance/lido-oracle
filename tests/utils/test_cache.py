from functools import lru_cache

from src.utils.cache import clear_object_lru_cache


class Calc:
    @lru_cache
    def get(self, a, b):
        return a + b


def test_clear_object_lru_cache():
    calc = Calc()
    calc.get(1, 2)
    assert calc.get.cache_info().currsize == 1

    clear_object_lru_cache(calc)

    assert calc.get.cache_info().currsize == 0
