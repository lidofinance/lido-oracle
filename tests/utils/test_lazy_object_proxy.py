import pytest
from src.utils.lazy_object_proxy import LazyObjectProxy


class Counter:
    """
    Custom class to test lazy object proxy.
    """

    def __init__(self, initial_value: int = 0):
        self.value = initial_value

    def increment(self) -> None:
        self.value += 1

    def decrement(self) -> None:
        self.value -= 1

    def get_value(self) -> int:
        return self.value

    def __str__(self) -> str:
        return f"Counter({self.value})"

    def __repr__(self) -> str:
        return f"Counter(value={self.value})"

    def __bool__(self) -> bool:
        return self.value != 0

    def __eq__(self, other) -> bool:
        if isinstance(other, Counter):
            return self.value == other.value
        return False

    def __lt__(self, other) -> bool:
        if isinstance(other, Counter):
            return self.value < other.value
        return False


@pytest.mark.unit
class TestUnitLazyObjectProxy:

    def test_lazy_init__access_attr__lazy_inited(self):
        is_object_created = False

        def factory():
            nonlocal is_object_created
            is_object_created = True
            return Counter(0)

        proxy = LazyObjectProxy(factory)

        assert not is_object_created
        proxy.value
        assert is_object_created

    def test_methods__call_methods__methods_calls_init_object(self):
        proxy = LazyObjectProxy(lambda: Counter(5))

        initial_value = proxy.get_value()
        proxy.increment()
        incremented_value = proxy.get_value()
        proxy.decrement()
        final_value = proxy.get_value()

        assert initial_value == 5
        assert incremented_value == 6
        assert final_value == 5

    def test_attributes__call_set_get_attribute__attributes_init_object(self):
        proxy = LazyObjectProxy(lambda: Counter(5))

        initial_value = proxy.value
        proxy.value = 10
        new_value = proxy.value

        assert initial_value == 5
        assert new_value == 10
        assert proxy.get_value() == 10

    def test_delete__delete_attribute__delete_init_object(self):
        proxy = LazyObjectProxy(lambda: Counter(5))

        del proxy.value

        with pytest.raises(AttributeError):
            proxy.value

    def test_delete__delete_protected__error(self):
        proxy = LazyObjectProxy(lambda: Counter(5))

        with pytest.raises(TypeError, match="can't delete _factory"):
            del proxy._factory
        with pytest.raises(TypeError, match="can't delete _wrapped_obj"):
            del proxy._wrapped_obj
        with pytest.raises(TypeError, match="can't delete _is_inited"):
            del proxy._is_inited

    def test_str__to_string__str_init_object(self):
        proxy = LazyObjectProxy(lambda: Counter(5))

        str_result = str(proxy)
        proxy.increment()
        new_str_result = str(proxy)

        assert str_result == "Counter(5)"
        assert new_str_result == "Counter(6)"

    def test_repr__to_repr__repr_init_object(self):
        proxy = LazyObjectProxy(lambda: Counter(5))

        repr_result = repr(proxy)
        proxy.decrement()
        new_repr_result = repr(proxy)

        assert repr_result == "Counter(value=5)"
        assert new_repr_result == "Counter(value=4)"

    def test_bool__to_bool__bool_init_object(self):
        proxy_zero = LazyObjectProxy(lambda: Counter(0))
        proxy_nonzero = LazyObjectProxy(lambda: Counter(1))

        bool_zero = bool(proxy_zero)
        bool_nonzero = bool(proxy_nonzero)

        assert bool_zero is False
        assert bool_nonzero is True

    def test_comparisons__compare__comparisons_init_object(self):
        proxy1 = LazyObjectProxy(lambda: Counter(5))
        proxy2 = LazyObjectProxy(lambda: Counter(10))
        proxy3 = LazyObjectProxy(lambda: Counter(5))

        eq_result = proxy1 == proxy3
        ne_result = proxy1 != proxy2
        lt_result = proxy1 < proxy2
        not_lt_result = not (proxy2 < proxy1)

        assert eq_result
        assert ne_result
        assert lt_result
        assert not_lt_result

    def test_class__get_class__class_init_object(self):
        proxy = LazyObjectProxy(lambda: Counter(5))

        class_type = proxy.__class__

        assert class_type == Counter

    def test_access_non_existent_method__call_non_existent_method__assert_error(self):
        proxy = LazyObjectProxy(lambda: Counter(5))

        with pytest.raises(AttributeError):
            proxy.nonexistent_method()
