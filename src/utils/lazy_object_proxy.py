import operator
from typing import Callable, TypeVar, Any, Generic

WrappedType = TypeVar('WrappedType')


class LazyObjectProxy(Generic[WrappedType]):

    def __init__(self, factory: Callable[[], WrappedType]) -> None:
        self._factory: Callable[[], WrappedType] = factory
        self._wrapped_obj: WrappedType | None = None
        self._is_inited: bool = False

    def _setup(self) -> None:
        if not self._is_inited:
            self._wrapped_obj = self._factory()
            self._is_inited = True

    @staticmethod
    def _proxy_method(method: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(self: 'LazyObjectProxy[WrappedType]', *args: Any, **kwargs: Any) -> Any:
            self._setup()  # pylint: disable=protected-access
            return method(self._wrapped_obj, *args, **kwargs)  # pylint: disable=protected-access
        return wrapper

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"_factory", "_wrapped_obj", "_is_inited"}:
            super().__setattr__(name, value)
        else:
            self._setup()
            setattr(self._wrapped_obj, name, value)

    def __delattr__(self, name: str) -> None:
        if name in {"_factory", "_wrapped_obj", "_is_inited"}:
            raise TypeError(f"can't delete {name}")
        self._setup()
        delattr(self._wrapped_obj, name)

    __getattr__ = _proxy_method(getattr)
    __bytes__ = _proxy_method(bytes)
    __str__ = _proxy_method(str)
    __repr__ = _proxy_method(repr)
    __bool__ = _proxy_method(bool)
    __dir__ = _proxy_method(dir)
    __hash__ = _proxy_method(hash)
    __eq__ = _proxy_method(operator.eq)
    __lt__ = _proxy_method(operator.lt)
    __gt__ = _proxy_method(operator.gt)
    __ne__ = _proxy_method(operator.ne)
    __getitem__ = _proxy_method(operator.getitem)
    __setitem__ = _proxy_method(operator.setitem)
    __delitem__ = _proxy_method(operator.delitem)
    __iter__ = _proxy_method(iter)
    __len__ = _proxy_method(len)
    __contains__ = _proxy_method(operator.contains)

    __class__ = property(  # type: ignore[assignment]
        _proxy_method(operator.attrgetter("__class__"))
    )
