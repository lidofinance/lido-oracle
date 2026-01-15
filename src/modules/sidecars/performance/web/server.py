from typing import cast
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException, Depends, Query, Request
from pydantic import BaseModel
import gunicorn.app.base

from src.modules.sidecars.performance.common.db import DutiesDB, Duty, EpochsDemand
from src.modules.sidecars.performance.web.middleware import RequestTimeoutMiddleware
from src.variables import (
    PERFORMANCE_WEB_SERVER_API_HOST,
    PERFORMANCE_WEB_SERVER_API_PORT,
    PERFORMANCE_WEB_SERVER_DB_CONNECTION_TIMEOUT,
    PERFORMANCE_WEB_SERVER_DB_STATEMENT_TIMEOUT_MS,
    PERFORMANCE_WEB_SERVER_MAX_EPOCH_RANGE,
    PERFORMANCE_WEB_SERVER_REQUEST_TIMEOUT,
    PERFORMANCE_WEB_SERVER_WORKERS,
    PERFORMANCE_WEB_SERVER_WORKER_CONNECTIONS,
    PERFORMANCE_WEB_SERVER_MAX_REQUESTS,
    PERFORMANCE_WEB_SERVER_TIMEOUT,
    PERFORMANCE_WEB_SERVER_KEEPALIVE,
)
from src.modules.sidecars.performance.web.metrics import attach_metrics
from src.types import EpochNumber

logger = logging.getLogger(__name__)


class EpochsDemandRequest(BaseModel):
    consumer: str
    l_epoch: EpochNumber
    r_epoch: EpochNumber


class HealthCheckResp(BaseModel):
    status: str = "ok"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = DutiesDB(
        connect_timeout=PERFORMANCE_WEB_SERVER_DB_CONNECTION_TIMEOUT,
        statement_timeout_ms=PERFORMANCE_WEB_SERVER_DB_STATEMENT_TIMEOUT_MS,
    )
    yield


app = FastAPI(title="Performance Collector API", lifespan=lifespan)
attach_metrics(app)
app.add_middleware(RequestTimeoutMiddleware, timeout=PERFORMANCE_WEB_SERVER_REQUEST_TIMEOUT)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    content_length = request.headers.get("content-length", "0")
    url_info = f"{request.method} {request.url.path}?{request.url.query}"
    logger.info("Request: %s | Content-Length: %s", url_info, content_length)

    response = await call_next(request)
    logger.info("Response: %s | Status: %s", url_info, response.status_code)

    return response


def get_db() -> DutiesDB:
    return cast(DutiesDB, app.state.db)


def validate_epoch_bounds(l_epoch: EpochNumber, r_epoch: EpochNumber) -> None:
    if l_epoch > r_epoch:
        raise HTTPException(status_code=400, detail="'l_epoch' must be <= 'r_epoch'")


def validate_range_size(l_epoch: EpochNumber, r_epoch: EpochNumber) -> None:
    range_size = int(r_epoch) - int(l_epoch) + 1
    if range_size > PERFORMANCE_WEB_SERVER_MAX_EPOCH_RANGE:
        raise HTTPException(
            status_code=400,
            detail=f"Requested epoch range is too large; maximum allowed size is {PERFORMANCE_WEB_SERVER_MAX_EPOCH_RANGE} epochs",
        )


def query_epoch_range(
    from_epoch: EpochNumber = Query(..., alias="from"),
    to_epoch: EpochNumber = Query(..., alias="to"),
) -> tuple[EpochNumber, EpochNumber]:
    validate_epoch_bounds(from_epoch, to_epoch)
    return from_epoch, to_epoch


@app.get("/health", response_model=HealthCheckResp)
def health():
    return {"status": "ok"}


@app.get("/check-epochs", response_model=bool)
def epochs_check(
        epoch_range: tuple[EpochNumber, EpochNumber] = Depends(query_epoch_range),
        db: DutiesDB = Depends(get_db),
):
    l_epoch, r_epoch = epoch_range
    return db.is_range_available(l_epoch, r_epoch)


@app.get("/missing-epochs", response_model=list[EpochNumber])
def epochs_missing(
        epoch_range: tuple[EpochNumber, EpochNumber] = Depends(query_epoch_range),
        db: DutiesDB = Depends(get_db),
):
    l_epoch, r_epoch = epoch_range
    return db.missing_epochs_in(l_epoch, r_epoch)


@app.get("/epochs", response_model=list[Duty])
def epochs_data(
        epoch_range: tuple[EpochNumber, EpochNumber] = Depends(query_epoch_range),
        db: DutiesDB = Depends(get_db),
):
    l_epoch, r_epoch = epoch_range
    validate_range_size(l_epoch, r_epoch)
    return db.get_epochs_data(l_epoch, r_epoch)


@app.get("/epochs/{epoch}", response_model=Duty | None)
def epoch_data(epoch: EpochNumber, db: DutiesDB = Depends(get_db)):
    return db.get_epoch_data(epoch)


@app.get("/demands", response_model=list[EpochsDemand])
def epochs_demands(db: DutiesDB = Depends(get_db)):
    return db.get_epochs_demands()


@app.get("/demands/{consumer}", response_model=EpochsDemand | None)
def one_epochs_demand(consumer: str, db: DutiesDB = Depends(get_db)):
    return db.get_epochs_demand(consumer)


@app.post("/demands", response_model=EpochsDemand)
def set_epochs_demand(demand_to_add: EpochsDemandRequest, db: DutiesDB = Depends(get_db)):
    validate_epoch_bounds(demand_to_add.l_epoch, demand_to_add.r_epoch)
    db.store_demand(demand_to_add.consumer, demand_to_add.l_epoch, demand_to_add.r_epoch)
    return db.get_epochs_demand(demand_to_add.consumer)


@app.delete("/demands", response_model=EpochsDemand)
def delete_epochs_demand(consumer: str = Query(...), db: DutiesDB = Depends(get_db)):
    to_delete = db.get_epochs_demand(consumer)
    if not to_delete:
        raise HTTPException(status_code=404, detail=f"No demand found for consumer '{consumer}'")
    db.delete_demand(consumer)
    return to_delete


def serve():

    class StandaloneApplication(gunicorn.app.base.BaseApplication):
        def __init__(self, app, options=None):
            self.options = options or {}
            self.application = app
            super().__init__()

        def init(self, parser, opts, args):
            return None

        def load_config(self):
            for key, value in self.options.items():
                if key in self.cfg.settings and value is not None:
                    self.cfg.set(key.lower(), value)

        def load(self):
            return self.application

    options = {
        'bind': f'{PERFORMANCE_WEB_SERVER_API_HOST}:{PERFORMANCE_WEB_SERVER_API_PORT}',
        'workers': PERFORMANCE_WEB_SERVER_WORKERS,
        'worker_class': 'uvicorn.workers.UvicornWorker',
        'worker_connections': PERFORMANCE_WEB_SERVER_WORKER_CONNECTIONS,
        'max_requests': PERFORMANCE_WEB_SERVER_MAX_REQUESTS,
        'timeout': PERFORMANCE_WEB_SERVER_TIMEOUT,
        'keepalive': PERFORMANCE_WEB_SERVER_KEEPALIVE,
    }

    StandaloneApplication(app, options).run()
