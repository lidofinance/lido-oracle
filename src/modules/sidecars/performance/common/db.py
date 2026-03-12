from datetime import UTC, datetime
from typing import Any, ClassVar

from pydantic import PostgresDsn
from sqlalchemy import ARRAY, Boolean, Column, DateTime, Integer, SmallInteger, delete, desc
from sqlalchemy.engine import Engine
from sqlalchemy.sql import func
from sqlmodel import Field, Session, SQLModel, col, create_engine, select

from src import variables
from src.modules.sidecars.performance.common.types import AttDutyMisses, ProposalDuty, SyncDuty
from src.types import EpochNumber
from src.utils.range import sequence


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


class Duty(SQLModel, table=True):
    __tablename__: ClassVar[str] = "duties"

    epoch: int = Field(sa_column=Column(Integer, primary_key=True, autoincrement=False))
    attestations: list[int] = Field(default_factory=list, sa_column=Column(ARRAY(Integer()), nullable=False))
    proposals_vids: list[int] = Field(default_factory=list, sa_column=Column(ARRAY(Integer()), nullable=False))
    proposals_flags: list[bool] = Field(default_factory=list, sa_column=Column(ARRAY(Boolean()), nullable=False))
    syncs_vids: list[int] = Field(default_factory=list, sa_column=Column(ARRAY(Integer()), nullable=False))
    syncs_misses: list[int] = Field(default_factory=list, sa_column=Column(ARRAY(SmallInteger()), nullable=False))


class EpochsDemand(SQLModel, table=True):
    __tablename__: ClassVar[str] = "epochs_demands"

    consumer: str = Field(primary_key=True)
    from_epoch: int
    to_epoch: int
    updated_at: datetime | None = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))


class DutiesDB:
    def __init__(
        self,
        *,
        connect_timeout: int | None = None,
        statement_timeout_ms: int | None = None,
    ):
        self.engine = self._build_engine(connect_timeout, statement_timeout_ms)
        self._setup_database()

    def _build_engine(self, connect_timeout: int | None, statement_timeout_ms: int | None) -> Engine:
        connect_args: dict[str, Any] = {}
        if connect_timeout:
            connect_args["connect_timeout"] = connect_timeout
        if statement_timeout_ms is not None:
            connect_args["options"] = f"-c statement_timeout={statement_timeout_ms}"

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
        return str(
            PostgresDsn.build(
                scheme="postgresql",
                username=variables.PERFORMANCE_DB_USER,
                password=variables.PERFORMANCE_DB_PASSWORD,
                host=variables.PERFORMANCE_DB_HOST,
                port=variables.PERFORMANCE_DB_PORT,
                path=variables.PERFORMANCE_DB_NAME,
            )
        )

    def _setup_database(self) -> None:
        SQLModel.metadata.create_all(self.engine)

    def get_session(self) -> Session:
        session = Session(self.engine, expire_on_commit=False)
        return session

    def store_demand(self, consumer: str, from_epoch: EpochNumber, to_epoch: EpochNumber) -> EpochsDemand:
        with self.get_session() as session:
            demand = session.get(EpochsDemand, consumer)
            if demand:
                demand.from_epoch = from_epoch
                demand.to_epoch = to_epoch
                demand.updated_at = get_datetime_utc()
            else:
                demand = EpochsDemand(
                    consumer=consumer,
                    from_epoch=from_epoch,
                    to_epoch=to_epoch,
                )
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

    def is_range_available(self, from_epoch: EpochNumber, to_epoch: EpochNumber) -> bool:
        if int(from_epoch) > int(to_epoch):
            raise ValueError("Invalid epoch range")

        with self.get_session() as session:
            stmt = (
                select(func.count())
                .select_from(Duty)
                .where(  # pylint: disable=not-callable
                    (col(Duty.epoch) >= from_epoch), (col(Duty.epoch) <= to_epoch)
                )
            )
            count = session.exec(stmt).one()
            return count == (to_epoch - from_epoch + 1)

    def missing_epochs_in(self, from_epoch: EpochNumber, to_epoch: EpochNumber) -> list[EpochNumber]:
        if from_epoch > to_epoch:
            raise ValueError("Invalid epoch range")

        with self.get_session() as session:
            present_duties = session.exec(
                select(Duty.epoch)
                .where((col(Duty.epoch) >= from_epoch), (col(Duty.epoch) <= to_epoch))
                .order_by(col(Duty.epoch))
            ).all()
            present = {EpochNumber(int(epoch)) for epoch in present_duties}

        return [epoch for epoch in sequence(from_epoch, to_epoch) if epoch not in present]

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

    def get_epochs_demands_max_updated_at(self) -> datetime | None:
        with self.get_session() as session:
            return session.exec(select(func.max(EpochsDemand.updated_at))).one()
