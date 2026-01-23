from time import time
from typing import Any

from sqlalchemy import ARRAY, Boolean, Column, Integer, SmallInteger, delete, desc
from sqlalchemy.engine import Engine
from sqlalchemy.sql import func
from sqlmodel import SQLModel, Field, Session, create_engine, select, col

from src import variables
from src.modules.sidecars.performance.common.types import ProposalDuty, SyncDuty, AttDutyMisses
from src.types import EpochNumber
from src.utils.range import sequence


class Duty(SQLModel, table=True):
    __tablename__ = "duties"

    epoch: int = Field(primary_key=True)
    attestations: list[int] = Field(default=None, sa_column=Column(ARRAY(Integer())))
    proposals_vids: list[int] = Field(default=None, sa_column=Column(ARRAY(Integer())))
    proposals_flags: list[bool] = Field(default=None, sa_column=Column(ARRAY(Boolean())))
    syncs_vids: list[int] = Field(default=None, sa_column=Column(ARRAY(Integer())))
    syncs_misses: list[int] = Field(default=None, sa_column=Column(ARRAY(SmallInteger())))


class EpochsDemand(SQLModel, table=True):
    __tablename__ = "epochs_demands"

    consumer: str = Field(primary_key=True)
    l_epoch: int
    r_epoch: int
    updated_at: int


class DutiesDB:
    def __init__(
        self,
        *,
        connect_timeout: int | None = None,
        statement_timeout_ms: int | None = None,
    ):
        self._statement_timeout_ms = statement_timeout_ms
        self.engine = self._build_engine(connect_timeout)
        self._setup_database()

    def _build_engine(self, connect_timeout: int | None) -> Engine:
        connect_args: dict[str, Any] = {}
        if connect_timeout:
            connect_args["connect_timeout"] = connect_timeout
        if self._statement_timeout_ms is not None:
            connect_args["options"] = f"-c statement_timeout={self._statement_timeout_ms}"

        return create_engine(
            self._get_database_url(),
            echo=False,
            pool_pre_ping=True,  # Enable connection health checks
            pool_recycle=variables.PERFORMANCE_DB_POOL_RECYCLE_SECONDS,
            pool_size=variables.PERFORMANCE_DB_POOL_SIZE,
            max_overflow=variables.PERFORMANCE_DB_MAX_OVERFLOW,
            connect_args=connect_args,
        )

    @staticmethod
    def _get_database_url() -> str:
        """Get PostgreSQL database URL from environment variables"""
        host = variables.PERFORMANCE_DB_HOST
        port = variables.PERFORMANCE_DB_PORT
        name = variables.PERFORMANCE_DB_NAME
        user = variables.PERFORMANCE_DB_USER
        password = variables.PERFORMANCE_DB_PASSWORD
        return f"postgresql://{user}:{password}@{host}:{port}/{name}"

    def _setup_database(self) -> None:
        SQLModel.metadata.create_all(self.engine)

    def get_session(self) -> Session:
        session = Session(self.engine)
        return session

    def store_demand(self, consumer: str, l_epoch: EpochNumber, r_epoch: EpochNumber) -> EpochsDemand:
        with self.get_session() as session:
            demand = session.get(EpochsDemand, consumer)
            if demand:
                demand.l_epoch = l_epoch
                demand.r_epoch = r_epoch
                demand.updated_at = int(time())
            else:
                demand = EpochsDemand(consumer=consumer, l_epoch=l_epoch, r_epoch=r_epoch, updated_at=int(time()))
                session.add(demand)
            session.commit()
            return demand

    def delete_demand(self, consumer: str) -> None:
        with self.get_session() as session:
            session.exec(delete(EpochsDemand).where(col(EpochsDemand.consumer) == consumer))
            session.commit()

    def store_epoch(
        self,
        epoch: EpochNumber,
        att_misses: AttDutyMisses,
        proposals: list[ProposalDuty],
        syncs: list[SyncDuty],
    ) -> None:
        # TODO: test that store and get are consistent
        self._store_data(epoch, att_misses, proposals, syncs)
        self._auto_prune(epoch)

    def _store_data(
        self,
        epoch: EpochNumber,
        att_misses: AttDutyMisses,
        proposals: list[ProposalDuty],
        syncs: list[SyncDuty],
    ) -> None:
        att_list: list[int] = [int(v) for v in att_misses] if att_misses else []
        prop_vids: list[int] = [int(p.validator_index) for p in proposals] if proposals else []
        prop_flags: list[bool] = [bool(p.is_proposed) for p in proposals] if proposals else []
        sync_vids: list[int] = [int(s.validator_index) for s in syncs] if syncs else []
        sync_misses: list[int] = [int(s.missed_count) for s in syncs] if syncs else []

        with self.get_session() as session:
            duty = session.get(Duty, epoch)
            if duty:
                duty.attestations = att_list
                duty.proposals_vids = prop_vids
                duty.proposals_flags = prop_flags
                duty.syncs_vids = sync_vids
                duty.syncs_misses = sync_misses
            else:
                duty = Duty(
                    epoch=epoch,
                    attestations=att_list,
                    proposals_vids=prop_vids,
                    proposals_flags=prop_flags,
                    syncs_vids=sync_vids,
                    syncs_misses=sync_misses,
                )
                session.add(duty)
            session.commit()

    def _auto_prune(self, current_epoch: EpochNumber) -> None:
        if variables.PERFORMANCE_COLLECTOR_DB_RETENTION_EPOCHS <= 0:
            return
        threshold = int(current_epoch) - variables.PERFORMANCE_COLLECTOR_DB_RETENTION_EPOCHS
        if threshold <= 0:
            return

        with self.get_session() as session:
            session.exec(delete(Duty).where(col(Duty.epoch) < threshold))
            session.commit()

    def is_range_available(self, l_epoch: EpochNumber, r_epoch: EpochNumber) -> bool:
        if int(l_epoch) > int(r_epoch):
            raise ValueError("Invalid epoch range")

        with self.get_session() as session:
            stmt = select(func.count()).select_from(Duty).where((col(Duty.epoch) >= l_epoch), (col(Duty.epoch) <= r_epoch)) # pylint: disable=not-callable
            count = session.exec(stmt).one()
            return count == (r_epoch - l_epoch + 1)

    def missing_epochs_in(self, l_epoch: EpochNumber, r_epoch: EpochNumber) -> list[EpochNumber]:
        if l_epoch > r_epoch:
            raise ValueError("Invalid epoch range")

        with self.get_session() as session:
            present_duties = session.exec(
                select(Duty.epoch).where((col(Duty.epoch) >= l_epoch), (col(Duty.epoch) <= r_epoch)).order_by(col(Duty.epoch))
            ).all()
            present = {EpochNumber(int(epoch)) for epoch in present_duties}

        return [epoch for epoch in sequence(l_epoch, r_epoch) if epoch not in present]

    def get_epochs_data(self, from_epoch: EpochNumber, to_epoch: EpochNumber) -> list[Duty]:
        with self.get_session() as session:
            return list(session.exec(select(Duty).where(Duty.epoch >= from_epoch, Duty.epoch <= to_epoch)).all())

    def get_epoch_data(self, epoch: EpochNumber) -> Duty | None:
        with self.get_session() as session:
            return session.get(Duty, epoch)

    def has_epoch(self, epoch: EpochNumber) -> bool:
        return self.get_epoch_data(epoch) is not None

    def min_epoch(self) -> EpochNumber | None:
        with self.get_session() as session:
            result = session.exec(select(Duty.epoch).order_by(col(Duty.epoch)).limit(1)).first()
            return EpochNumber(int(result)) if result else None

    def max_epoch(self) -> EpochNumber | None:
        with self.get_session() as session:
            result = session.exec(select(Duty.epoch).order_by(desc(col(Duty.epoch))).limit(1)).first()
            return EpochNumber(int(result)) if result else None

    def epochs_count(self) -> int:
        with self.get_session() as session:
            stmt = select(func.count()).select_from(Duty)  # pylint: disable=not-callable
            return int(session.exec(stmt).one())

    def demands_count(self) -> int:
        with self.get_session() as session:
            stmt = select(func.count()).select_from(EpochsDemand)  # pylint: disable=not-callable
            return int(session.exec(stmt).one())

    def get_epochs_demand(self, consumer: str) -> EpochsDemand | None:
        with self.get_session() as session:
            return session.get(EpochsDemand, consumer)

    def get_epochs_demands(self) -> list[EpochsDemand]:
        with self.get_session() as session:
            return list(session.exec(select(EpochsDemand)).all())

    def get_epochs_demands_max_updated_at(self) -> int | None:
        with self.get_session() as session:
            return session.exec(select(func.max(EpochsDemand.updated_at))).one()
