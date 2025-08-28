from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.utils.timeit import timeit


@pytest.mark.unit
def test_timeit_log_fn_no_args():
    log_fn = Mock()

    @timeit(log_fn)
    def fn(): ...

    fn()
    log_fn.assert_called_once()
    assert log_fn.call_args.args[0] == SimpleNamespace()


@pytest.mark.unit
def test_timeit_log_fn_args():
    log_fn = Mock()

    @timeit(log_fn)
    def fn(a, b, k): ...

    fn(2, 0, k="any")
    log_fn.assert_called_once()
    assert log_fn.call_args.args[0] == SimpleNamespace(a=2, b=0, k="any")


@pytest.mark.unit
def test_timeit_log_fn_args_method():
    log_fn = Mock()

    class Some:
        @timeit(log_fn)
        def fn(self, a, b): ...

    some = Some()
    some.fn(42, b="any")

    log_fn.assert_called_once()
    assert log_fn.call_args.args[0] == SimpleNamespace(a=42, b="any", self=some)


@pytest.mark.unit
def test_timeit_log_fn_called_on_exception():
    log_fn = Mock()

    @timeit(log_fn)
    def fn():
        raise ValueError

    with pytest.raises(ValueError):
        fn()

    log_fn.assert_not_called()


@pytest.mark.unit
def test_timeit_duration(monkeypatch: pytest.MonkeyPatch):
    log_fn = Mock()

    @timeit(log_fn)
    def fn(): ...

    time = Mock(side_effect=[1, 12.34])
    with monkeypatch.context() as m:
        m.setattr("time.time", time)
        fn()

    assert time.call_count == 2
    log_fn.assert_called_once_with(SimpleNamespace(), 11.34)
