from datetime import UTC, datetime
from typing import Any, ClassVar

from pydantic import PostgresDsn
from sqlalchemy import ARRAY, Boolean, Column, DateTime, Integer, SmallInteger, asc, delete, desc, exists
from sqlalchemy.engine import Engine
from sqlalchemy.sql import func
from sqlalchemy.types import JSON
from sqlmodel import Field, Session, SQLModel, col, create_engine, select

from src import variables
from src.modules.sidecars.performance.common.types import AttDutyMisses, ProposalDuty, SyncDuty
from src.types import EpochNumber
from src.utils.range import sequence


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


class Duty(SQLModel, table=True):
    """Aggregated validator duties and misses for a single epoch."""

    __tablename__: ClassVar[str] = "duties"

    epoch: int = Field(
        description="Epoch number for which duty data is stored.",
        sa_column=Column(Integer, primary_key=True, autoincrement=False),
    )
    missed_attestation_vids: list[int] = Field(
        default_factory=list,
        description="Validator indices that missed attestation duties in this epoch.",
        sa_column=Column(ARRAY(Integer()), nullable=False),
    )
    proposals_vids: list[int] = Field(
        default_factory=list,
        description="Validator indices for proposer duties in this epoch.",
        sa_column=Column(ARRAY(Integer()), nullable=False),
    )
    proposals_flags: list[bool] = Field(
        default_factory=list,
        description="Proposal success flags aligned with 'proposals_vids' by index.",
        sa_column=Column(ARRAY(Boolean()), nullable=False),
    )
    syncs_vids: list[int] = Field(
        default_factory=list,
        description="Validator indices for sync committee duties in this epoch.",
        sa_column=Column(ARRAY(Integer()), nullable=False),
    )
    syncs_misses: list[int] = Field(
        default_factory=list,
        description="Miss counters aligned with 'syncs_vids' by index.",
        sa_column=Column(ARRAY(SmallInteger()), nullable=False),
    )


class EpochsDemand(SQLModel, table=True):
    """Requested epoch range that a consumer expects from the performance collector."""

    __tablename__: ClassVar[str] = "epochs_demands"

    consumer: str = Field(
        primary_key=True,
        description="Unique consumer identifier for the requested epoch range.",
    )
    from_epoch: int = Field(
        ge=0,
        description="Start epoch of the requested range (uint).",
    )
    to_epoch: int = Field(
        ge=0,
        description="End epoch of the requested range (uint).",
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
        description="UTC timestamp when this demand was last updated.",
    )


class Settings(SQLModel, table=True):
    __tablename__: ClassVar[str] = "settings"

    key: str = Field(primary_key=True)
    value: Any = Field(sa_column=Column(JSON, nullable=False))


RETENTION_EPOCHS_KEY = "retention_epochs"
RETENTION_EPOCHS_DEFAULT = 225 * 30 * 6


class IncompleteEpochRangeError(ValueError):
    def __init__(self, from_epoch: EpochNumber, to_epoch: EpochNumber, missing_epochs: list[EpochNumber]):
        self.from_epoch = from_epoch
        self.to_epoch = to_epoch
        self.missing_epochs = missing_epochs
        super().__init__(f"Incomplete epoch range [{from_epoch}, {to_epoch}]: missing epochs {missing_epochs}")


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
        self._seed_settings()

    def _seed_settings(self) -> None:
        with self.get_session() as session:
            existing = session.get(Settings, RETENTION_EPOCHS_KEY)
            if not existing:
                session.add(Settings(key=RETENTION_EPOCHS_KEY, value=RETENTION_EPOCHS_DEFAULT))
                session.commit()

    def get_session(self) -> Session:
        # Keep model attributes available after commit when objects are returned outside this context.
        return Session(self.engine, expire_on_commit=False)

    def get_retention_epochs(self) -> int:
        with self.get_session() as session:
            setting = session.get(Settings, RETENTION_EPOCHS_KEY)
            if setting is None:
                raise ValueError(f"'{RETENTION_EPOCHS_KEY}' setting not found in database")
            if not isinstance(setting.value, int):
                raise TypeError(f"'{RETENTION_EPOCHS_KEY}' setting expected an int, got {type(setting.value).__name__}")
            if setting.value <= 0:
                raise ValueError(f"'{RETENTION_EPOCHS_KEY}' must be positive, got {setting.value}")
            return setting.value

    def set_retention_epochs(self, value: int) -> None:
        if value <= 0:
            raise ValueError("retention_epochs must be positive")
        with self.get_session() as session:
            setting = session.get(Settings, RETENTION_EPOCHS_KEY)
            if setting:
                setting.value = value
            else:
                session.add(Settings(key=RETENTION_EPOCHS_KEY, value=value))
            session.commit()

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

    def delete_demand(self, demand: EpochsDemand) -> None:
        with self.get_session() as session:
            session.delete(demand)
            session.commit()

    def store_epoch(
        self,
        epoch: EpochNumber,
        att_misses: AttDutyMisses,
        proposals: list[ProposalDuty],
        syncs: list[SyncDuty],
    ) -> None:
        self._store_data(epoch, att_misses, proposals, syncs)
        self._prune(epoch)

    def _store_data(
        self,
        epoch: EpochNumber,
        att_misses: AttDutyMisses,
        proposals: list[ProposalDuty],
        syncs: list[SyncDuty],
    ) -> None:
        att_list: list[int] = list(att_misses)
        prop_vids: list[int] = [p.validator_index for p in proposals]
        prop_flags: list[bool] = [p.is_proposed for p in proposals]
        sync_vids: list[int] = [s.validator_index for s in syncs]
        sync_misses: list[int] = [s.missed_count for s in syncs]

        with self.get_session() as session:
            duty = session.get(Duty, epoch)
            if duty:
                duty.missed_attestation_vids = att_list
                duty.proposals_vids = prop_vids
                duty.proposals_flags = prop_flags
                duty.syncs_vids = sync_vids
                duty.syncs_misses = sync_misses
            else:
                duty = Duty(
                    epoch=epoch,
                    missed_attestation_vids=att_list,
                    proposals_vids=prop_vids,
                    proposals_flags=prop_flags,
                    syncs_vids=sync_vids,
                    syncs_misses=sync_misses,
                )
                session.add(duty)
            session.commit()

    def _prune(self, current_epoch: EpochNumber) -> None:
        retention = self.get_retention_epochs()
        max_stored_epoch = self.max_epoch()
        anchor_epoch = max_stored_epoch if max_stored_epoch is not None else current_epoch
        min_epoch_to_keep = anchor_epoch - retention + 1
        if min_epoch_to_keep <= 0:
            return

        with self.get_session() as session:
            session.exec(delete(Duty).where(col(Duty.epoch) < min_epoch_to_keep))
            session.commit()

    def is_range_available(self, from_epoch: EpochNumber, to_epoch: EpochNumber) -> bool:
        if from_epoch > to_epoch:
            raise ValueError("Invalid epoch range")

        with self.get_session() as session:
            stmt = select(func.count()).select_from(Duty).where(Duty.epoch >= from_epoch, Duty.epoch <= to_epoch)
            count = session.exec(stmt).one()
            return count == (to_epoch - from_epoch + 1)

    def missing_epochs_in(self, from_epoch: EpochNumber, to_epoch: EpochNumber) -> list[EpochNumber]:
        if from_epoch > to_epoch:
            raise ValueError("Invalid epoch range")

        with self.get_session() as session:
            present = set(session.exec(
                select(Duty.epoch).where(Duty.epoch >= from_epoch, Duty.epoch <= to_epoch)
            ).all())

        return [epoch for epoch in sequence(from_epoch, to_epoch) if epoch not in present]

    def get_complete_epochs_data(self, from_epoch: EpochNumber, to_epoch: EpochNumber) -> list[Duty]:
        if from_epoch > to_epoch:
            raise ValueError("Invalid epoch range")

        duties = self.get_epochs_data(from_epoch, to_epoch)
        expected_count = to_epoch - from_epoch + 1
        if len(duties) == expected_count:
            return duties

        present_epochs = {EpochNumber(duty.epoch) for duty in duties}
        missing_epochs = [epoch for epoch in sequence(from_epoch, to_epoch) if epoch not in present_epochs]
        if missing_epochs:
            raise IncompleteEpochRangeError(from_epoch, to_epoch, missing_epochs)

        return duties

    def get_epochs_data(self, from_epoch: EpochNumber, to_epoch: EpochNumber) -> list[Duty]:
        with self.get_session() as session:
            return list(session.exec(select(Duty).where(Duty.epoch >= from_epoch, Duty.epoch <= to_epoch)).all())

    def get_epoch_data(self, epoch: EpochNumber) -> Duty | None:
        with self.get_session() as session:
            return session.get(Duty, epoch)

    def has_epoch(self, epoch: EpochNumber) -> bool:
        with self.get_session() as session:
            return session.exec(select(exists().where(col(Duty.epoch) == epoch))).one()

    def min_epoch(self) -> EpochNumber | None:
        with self.get_session() as session:
            result = session.exec(select(Duty.epoch).order_by(asc(col(Duty.epoch))).limit(1)).first()
            return EpochNumber(result) if result else None

    def max_epoch(self) -> EpochNumber | None:
        with self.get_session() as session:
            result = session.exec(select(Duty.epoch).order_by(desc(col(Duty.epoch))).limit(1)).first()
            return EpochNumber(result) if result else None

    def epochs_count(self) -> int:
        with self.get_session() as session:
            return session.exec(select(func.count()).select_from(Duty)).one()

    def demands_count(self) -> int:
        with self.get_session() as session:
            return session.exec(select(func.count()).select_from(EpochsDemand)).one()

    def get_epochs_demand(self, consumer: str) -> EpochsDemand | None:
        with self.get_session() as session:
            return session.get(EpochsDemand, consumer)

    def count_stored_epochs_in_range(self, from_epoch: EpochNumber, to_epoch: EpochNumber) -> int:
        if from_epoch > to_epoch:
            raise ValueError("Invalid epoch range")

        with self.get_session() as session:
            return session.exec(
                select(func.count()).select_from(Duty).where(col(Duty.epoch).between(from_epoch, to_epoch))
            ).one()

    def get_epochs_demands(self) -> list[EpochsDemand]:
        with self.get_session() as session:
            return list(session.exec(select(EpochsDemand)).all())

    def get_epochs_demands_max_updated_at(self) -> datetime | None:
        with self.get_session() as session:
            return session.exec(select(func.max(EpochsDemand.updated_at))).one()
