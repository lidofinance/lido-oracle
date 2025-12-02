from typing import Optional
import logging
from fastapi import FastAPI, HTTPException, Depends, Query
import uvicorn
from pydantic import BaseModel
from uvicorn.config import LOGGING_CONFIG

from src.modules.performance.common.db import DutiesDB, Duty, EpochsDemand
from src.variables import PERFORMANCE_WEB_SERVER_API_PORT
from src.modules.performance.web.metrics import attach_metrics
from src.types import EpochNumber
from src.metrics.logging import JsonFormatter, handler


class EpochsDemandRequest(BaseModel):
    consumer: str
    l_epoch: EpochNumber
    r_epoch: EpochNumber


class HealthCheckResp(BaseModel):
    status: str = "ok"


app = FastAPI(title="Performance Collector API")
attach_metrics(app)

_db_instance: Optional[DutiesDB] = None


async def get_db() -> DutiesDB:
    global _db_instance
    if _db_instance is None:
        _db_instance = DutiesDB()
    return _db_instance


async def validate_epoch_bounds(l_epoch: EpochNumber, r_epoch: EpochNumber) -> None:
    if l_epoch > r_epoch:
        raise HTTPException(status_code=400, detail="'l_epoch' must be <= 'r_epoch'")


@app.get("/health", response_model=HealthCheckResp)
async def health():
    return {"status": "ok"}


@app.get("/check-epochs", response_model=bool)
async def epochs_check(
    from_epoch: EpochNumber = Query(..., alias="from"),
    to_epoch: EpochNumber = Query(..., alias="to"),
    db: DutiesDB = Depends(get_db),
):
    await validate_epoch_bounds(from_epoch, to_epoch)
    return bool(db.is_range_available(from_epoch, to_epoch))


@app.get("/missing-epochs", response_model=list[EpochNumber])
async def epochs_missing(
    from_epoch: EpochNumber = Query(..., alias="from"),
    to_epoch: EpochNumber = Query(..., alias="to"),
    db: DutiesDB = Depends(get_db),
):
    await validate_epoch_bounds(from_epoch, to_epoch)
    return db.missing_epochs_in(from_epoch, to_epoch)


@app.get("/epochs", response_model=list[Duty])
async def epochs_data(
    from_epoch: EpochNumber = Query(..., alias="from"),
    to_epoch: EpochNumber = Query(..., alias="to"),
    db: DutiesDB = Depends(get_db),
):
    await validate_epoch_bounds(from_epoch, to_epoch)
    return db.get_epochs_data(from_epoch, to_epoch)


@app.get("/epochs/{epoch}", response_model=Duty | None)
async def epoch_data(epoch: EpochNumber, db: DutiesDB = Depends(get_db)):
    return db.get_epoch_data(epoch)


@app.get("/demands", response_model=list[EpochsDemand])
async def epochs_demands(db: DutiesDB = Depends(get_db)):
    return db.get_epochs_demands()


@app.get("/demands/{consumer}", response_model=EpochsDemand | None)
async def one_epochs_demand(consumer: str, db: DutiesDB = Depends(get_db)):
    return db.get_epochs_demand(consumer)


@app.post("/demands", response_model=EpochsDemand)
async def set_epochs_demand(demand_to_add: EpochsDemandRequest, db: DutiesDB = Depends(get_db)):
    await validate_epoch_bounds(demand_to_add.l_epoch, demand_to_add.r_epoch)
    db.store_demand(demand_to_add.consumer, demand_to_add.l_epoch, demand_to_add.r_epoch)
    return db.get_epochs_demand(demand_to_add.consumer)


@app.delete("/demands", response_model=EpochsDemand)
async def delete_epochs_demand(consumer: str = Query(...), db: DutiesDB = Depends(get_db)):
    to_delete = db.get_epochs_demand(consumer)
    if not to_delete:
        raise HTTPException(status_code=404, detail=f"No demand found for consumer '{consumer}'")
    db.delete_demand(consumer)
    return to_delete


def serve():
    # Prepare logging config with the app-wise formatter
    logging_config = LOGGING_CONFIG.copy()
    for formatter_name in logging_config["formatters"]:
        logging_config["formatters"][formatter_name] = {
            "()": JsonFormatter,
        }
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PERFORMANCE_WEB_SERVER_API_PORT,
        log_config=logging_config,
    )
