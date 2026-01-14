from anyio import fail_after
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class RequestTimeoutMiddleware:
    """Bounds total request processing time."""

    def __init__(self, app: ASGIApp, timeout: int):
        self.app = app
        self.timeout = timeout

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        try:
            with fail_after(self.timeout):
                await self.app(scope, receive, send)
        except TimeoutError:
            response = JSONResponse(
                {"detail": f"Request timed out after {self.timeout} seconds"},
                status_code=504,
            )
            await response(scope, receive, send)
