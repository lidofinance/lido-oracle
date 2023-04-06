
from src.utils.cache import clear_global_cache, global_lru_cache


class Calc:
    @global_lru_cache(maxsize=1)
    def get(self, a, b):
        return a + b


def test_clear_global_cache():
    calc = Calc()
    calc.get(1, 2)
    assert calc.get.cache_info().currsize == 1

    clear_global_cache()

    assert calc.get.cache_info().currsize == 0
