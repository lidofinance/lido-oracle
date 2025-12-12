from anyio import fail_after
from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse


class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    """Bounds total request processing time."""

    def __init__(self, app: FastAPI, timeout: float):
        super().__init__(app)
        self.timeout = timeout

    async def dispatch(self, request, call_next: RequestResponseEndpoint):  # type: ignore[override]
        try:
            with fail_after(self.timeout):
                return await call_next(request)
        except TimeoutError:
            return JSONResponse(
                {"detail": f"Request timed out after {self.timeout} seconds"},
                status_code=504,
            )
