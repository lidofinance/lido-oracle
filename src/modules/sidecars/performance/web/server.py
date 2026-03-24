import logging
from contextlib import asynccontextmanager
from typing import Annotated, Literal, cast

import gunicorn.app.base
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.params import Body
from pydantic import BaseModel
from sqlmodel import select

from src.modules.sidecars.performance.common.db import DutiesDB, Duty
from src.modules.sidecars.performance.web.metrics import attach_metrics
from src.modules.sidecars.performance.web.middleware import RequestTimeoutMiddleware
from src.modules.sidecars.performance.web.validation import (
    ConsumerParam,
    EpochParam,
    EpochRangeParam,
    EpochsDemandParam,
    EpochsDemandResponse,
    LimitedEpochRangeParam,
    RetentionEpochsParam,
    RetentionEpochsResponse,
)
from src.types import EpochNumber
from src.variables import (
    PERFORMANCE_WEB_SERVER_API_HOST,
    PERFORMANCE_WEB_SERVER_API_PORT,
    PERFORMANCE_WEB_SERVER_DB_CONNECTION_TIMEOUT,
    PERFORMANCE_WEB_SERVER_DB_STATEMENT_TIMEOUT_MS,
    PERFORMANCE_WEB_SERVER_KEEPALIVE,
    PERFORMANCE_WEB_SERVER_MAX_REQUESTS,
    PERFORMANCE_WEB_SERVER_REQUEST_TIMEOUT,
    PERFORMANCE_WEB_SERVER_TIMEOUT,
    PERFORMANCE_WEB_SERVER_WORKER_CONNECTIONS,
    PERFORMANCE_WEB_SERVER_WORKERS,
)


logger = logging.getLogger(__name__)


class HealthCheckResp(BaseModel):
    status: Literal["ok"] | None = None
    detail: str | None = None


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

api_v1 = APIRouter(prefix="/v1")


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


DBDep = Annotated[DutiesDB, Depends(get_db)]


@app.get("/health", response_model=HealthCheckResp, response_model_exclude_none=True)
def health(db: DBDep):
    try:
        with db.get_session() as session:
            session.exec(select(1)).one()
    except Exception as error:  # pylint: disable=broad-exception-caught
        logger.error("Healthcheck DB connection failed: %s", error)
        raise HTTPException(status_code=503, detail=f"Database connection failed: {str(error)}") from error
    return {"status": "ok"}


@api_v1.get("/check-epochs", response_model=bool)
def epochs_check(epoch_range: Annotated[EpochRangeParam, Query()], db: DBDep):
    return db.is_range_available(epoch_range.from_epoch, epoch_range.to_epoch)


@api_v1.get("/missing-epochs", response_model=list[EpochNumber])
def epochs_missing(epoch_range: Annotated[LimitedEpochRangeParam, Query()], db: DBDep):
    return db.missing_epochs_in(epoch_range.from_epoch, epoch_range.to_epoch)


@api_v1.get("/epochs", response_model=list[Duty])
def epochs_data(epoch_range: Annotated[LimitedEpochRangeParam, Query()], db: DBDep):
    return db.get_epochs_data(epoch_range.from_epoch, epoch_range.to_epoch)


@api_v1.get("/epochs/{epoch}", response_model=Duty | None)
def epoch_data(epoch_param: Annotated[EpochParam, Path()], db: DBDep):
    return db.get_epoch_data(epoch_param.epoch)


@api_v1.get("/demands", response_model=list[EpochsDemandResponse])
def epochs_demands(db: DBDep):
    return db.get_epochs_demands()


@api_v1.get("/demands/{consumer}", response_model=EpochsDemandResponse | None)
def one_epochs_demand(consumer_param: Annotated[ConsumerParam, Path()], db: DBDep):
    return db.get_epochs_demand(consumer_param.consumer)


@api_v1.post("/demands", response_model=EpochsDemandResponse)
def set_epochs_demand(demand_to_add: Annotated[EpochsDemandParam, Body()], db: DBDep):
    retention = db.get_retention_epochs()
    demand_span = demand_to_add.to_epoch - demand_to_add.from_epoch + 1
    if demand_span > retention:
        raise HTTPException(
            status_code=422,
            detail=f"Demand epoch range ({demand_span} epochs) exceeds the retention interval ({retention} epochs)",
        )

    max_stored_epoch = db.max_epoch()
    if max_stored_epoch is not None:
        min_epoch_to_keep = max_stored_epoch - retention + 1
        if min_epoch_to_keep > 0 and demand_to_add.from_epoch < min_epoch_to_keep:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Demand start epoch ({demand_to_add.from_epoch}) is older than retainable range start "
                    f"({min_epoch_to_keep}) for newest stored epoch ({max_stored_epoch})"
                ),
            )

    return db.store_demand(demand_to_add.consumer, demand_to_add.from_epoch, demand_to_add.to_epoch)


@api_v1.delete("/demands/{consumer}", response_model=EpochsDemandResponse)
def delete_epochs_demand(consumer_param: Annotated[ConsumerParam, Path()], db: DBDep):
    to_delete = db.get_epochs_demand(consumer_param.consumer)
    if not to_delete:
        raise HTTPException(status_code=404, detail=f"No demand found for consumer '{consumer_param.consumer}'")
    db.delete_demand(to_delete)
    return to_delete


@api_v1.get("/admin/settings/retention-epochs", response_model=RetentionEpochsResponse)
def get_retention_epochs(db: DBDep):
    return RetentionEpochsResponse(retention_epochs=db.get_retention_epochs())


@api_v1.put("/admin/settings/retention-epochs", response_model=RetentionEpochsResponse)
def set_retention_epochs(body: Annotated[RetentionEpochsParam, Body()], db: DBDep):
    db.set_retention_epochs(body.retention_epochs)
    return RetentionEpochsResponse(retention_epochs=body.retention_epochs)


app.include_router(api_v1)


def serve():
    class StandaloneApplication(gunicorn.app.base.BaseApplication):
        def __init__(self, app, options=None):
            self.options = options or {}
            self.application = app
            super().__init__()

        def init(self, parser, opts, args): ...

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
