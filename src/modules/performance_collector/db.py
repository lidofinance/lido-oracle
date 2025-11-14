import sqlite3
from time import time
from contextlib import contextmanager
from typing import Optional

from src import variables
from src.modules.performance_collector.codec import ProposalDuty, SyncDuty, EpochDataCodec, AttDutyMisses
from src.types import EpochNumber
from src.utils.range import sequence


class DutiesDB:
    def __init__(self, path: str):
        self._path = path
        self.migrate()
        # Check SQLite thread safety.
        # Doc: https://docs.python.org/3/library/sqlite3.html#sqlite3.threadsafety
        assert sqlite3.threadsafety > 0, "SQLite is not compiled with thread safety"

    @contextmanager
    def cursor(self):
        conn = sqlite3.connect(
            self._path, check_same_thread=False, timeout=variables.PERFORMANCE_COLLECTOR_DB_CONNECTION_TIMEOUT
        )
        yield conn.cursor()
        conn.commit()
        conn.close()

    def migrate(self):
        with self.cursor() as cur:
            # Optimize SQLite for performance: WAL mode for concurrent access,
            # normal sync for speed/safety balance, memory temp storage
            cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute("PRAGMA synchronous=NORMAL;")
            cur.execute("PRAGMA temp_store=MEMORY;")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS duties
                (
                    epoch INTEGER PRIMARY KEY,
                    blob  BLOB NOT NULL
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS epochs_demand
                (
                    consumer   STRING PRIMARY KEY,
                    l_epoch    INTEGER,
                    r_epoch    INTEGER,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def store_demand(self, consumer: str, l_epoch: int, r_epoch: int) -> None:
        with self.cursor() as cur:
            updated_at = int(time())
            cur.execute(
                "INSERT OR REPLACE INTO epochs_demand(consumer, l_epoch, r_epoch, updated_at) VALUES(?, ?, ?, ?)",
                (consumer, l_epoch, r_epoch, updated_at),
            )

    def store_epoch(
        self,
        epoch: EpochNumber,
        att_misses: AttDutyMisses,
        proposals: list[ProposalDuty],
        syncs: list[SyncDuty],
    ) -> bytes:
        blob = EpochDataCodec.encode(att_misses, proposals, syncs)
        self._store_blob(epoch, blob)
        self._auto_prune(epoch)
        return blob

    def _store_blob(self, epoch: int, blob: bytes) -> None:
        with self.cursor() as cur:
            cur.execute(
                "INSERT OR REPLACE INTO duties(epoch, blob) VALUES(?, ?)",
                (epoch, sqlite3.Binary(blob)),
            )

    def _auto_prune(self, current_epoch: int) -> None:
        if variables.PERFORMANCE_COLLECTOR_DB_RETENTION_EPOCHS <= 0:
            return
        threshold = int(current_epoch) - variables.PERFORMANCE_COLLECTOR_DB_RETENTION_EPOCHS
        if threshold <= 0:
            return
        with self.cursor() as cur:
            cur.execute("DELETE FROM duties WHERE epoch < ?", (threshold,))

    def is_range_available(self, l_epoch: int, r_epoch: int) -> bool:
        if int(l_epoch) > int(r_epoch):
            raise ValueError("Invalid epoch range")
        with self.cursor() as cur:
            cur.execute(
                "SELECT COUNT(1) FROM duties WHERE epoch BETWEEN ? AND ?",
                (int(l_epoch), int(r_epoch)),
            )
            (cnt,) = cur.fetchone() or (0,)
        return int(cnt) == (r_epoch - l_epoch + 1)

    def missing_epochs_in(self, l_epoch: int, r_epoch: int) -> list[int]:
        if l_epoch > r_epoch:
            raise ValueError("Invalid epoch range")
        with self.cursor() as cur:
            cur.execute(
                "SELECT epoch FROM duties WHERE epoch BETWEEN ? AND ? ORDER BY epoch",
                (l_epoch, r_epoch),
            )
            present = [int(row[0]) for row in cur.fetchall()]
        missing = []
        for epoch in sequence(l_epoch, r_epoch):
            if epoch not in present:
                missing.append(epoch)
        return missing

    def _get_entry(self, epoch: int) -> Optional[bytes]:
        with self.cursor() as cur:
            cur.execute("SELECT blob FROM duties WHERE epoch=?", (int(epoch),))
            row = cur.fetchone()
        if not row:
            return None
        return bytes(row[0])

    def get_epoch_blob(self, epoch: int) -> Optional[bytes]:
        return self._get_entry(epoch)

    def has_epoch(self, epoch: int) -> bool:
        with self.cursor() as cur:
            cur.execute("SELECT 1 FROM duties WHERE epoch=? LIMIT 1", (int(epoch),))
            ok = cur.fetchone() is not None
        return ok

    def min_epoch(self) -> int | None:
        with self.cursor() as cur:
            cur.execute("SELECT MIN(epoch) FROM duties")
            val = cur.fetchone()[0]
        return int(val) if val else None

    def max_epoch(self) -> int | None:
        with self.cursor() as cur:
            cur.execute("SELECT MAX(epoch) FROM duties")
            val = cur.fetchone()[0]
        return int(val) if val else None

    def epochs_demand(self) -> dict[str, tuple[int, int]]:
        data = {}
        with self.cursor() as cur:
            cur.execute("SELECT consumer, l_epoch, r_epoch, updated_at FROM epochs_demand")
            demands = cur.fetchall()
            for consumer, l_epoch, r_epoch, updated_at in demands:
                data[consumer] = (int(l_epoch), int(r_epoch), int(updated_at))
        return data
