from _typeshed import Incomplete

class TimeoutError(AssertionError):
    value: Incomplete
    def __init__(self, value: str = ...) -> None: ...

def timeout(
    seconds: int | None = ...,
    use_signals: bool = True,
    timeout_exception: type[TimeoutError] = TimeoutError,
    exception_message: str | None = ...,
): ...
