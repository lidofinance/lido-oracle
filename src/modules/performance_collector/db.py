import sqlite3
from contextlib import contextmanager
from typing import Optional

from src import variables
from src.modules.performance_collector.codec import ProposalDuty, SyncDuty, EpochDataCodec, AttDutyMisses
from src.types import EpochNumber


class DutiesDB:
    def __init__(self, path: str):
        self._path = path
        self._conn = sqlite3.connect(self._path, check_same_thread=False, timeout=30.0)  # TODO: Timeout?
        # Optimize SQLite for performance: WAL mode for concurrent access,
        # normal sync for speed/safety balance, memory temp storage
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA temp_store=MEMORY;")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS duties
            (
                epoch INTEGER PRIMARY KEY,
                blob  BLOB NOT NULL
            );
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS epochs_demand
            (
                consumer STRING PRIMARY KEY,
                l_epoch INTEGER,
                r_epoch INTEGER
            )
            """
        )
        self._conn.commit()

    def __del__(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    @contextmanager
    def connection(self):
        try:
            yield self._conn.cursor()
        finally:
            self._conn.commit()

    def store_demand(self, consumer: str, l_epoch: int, r_epoch: int) -> None:
        with self.connection() as cur:
            cur.execute(
                "INSERT OR REPLACE INTO epochs_demand(consumer, l_epoch, r_epoch) VALUES(?, ?, ?)",
                (consumer, l_epoch, r_epoch),
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
        with self.connection() as cur:
            cur.execute(
                "INSERT OR REPLACE INTO duties(epoch, blob) VALUES(?, ?)",
                (epoch, sqlite3.Binary(blob)),
            )

    def _auto_prune(self, current_epoch: int) -> None:
        if variables.PERFORMANCE_COLLECTOR_RETENTION_EPOCHS <= 0:
            return
        threshold = int(current_epoch) - variables.PERFORMANCE_COLLECTOR_RETENTION_EPOCHS
        if threshold <= 0:
            return
        with self.connection() as cur:
            # TODO: logging?
            cur.execute("DELETE FROM duties WHERE epoch < ?", (threshold,))

    def is_range_available(self, l_epoch: int, r_epoch: int) -> bool:
        if int(l_epoch) > int(r_epoch):
            raise ValueError("Invalid epoch range")
        with self.connection() as cur:
            cur.execute(
                "SELECT COUNT(1) FROM duties WHERE epoch BETWEEN ? AND ?",
                (int(l_epoch), int(r_epoch)),
            )
            (cnt,) = cur.fetchone() or (0,)
        return int(cnt) == (r_epoch - l_epoch + 1)

    def missing_epochs_in(self, l_epoch: int, r_epoch: int) -> list[int]:
        if l_epoch > r_epoch:
            raise ValueError("Invalid epoch range")
        with self.connection() as cur:
            cur.execute(
                "SELECT epoch FROM duties WHERE epoch BETWEEN ? AND ? ORDER BY epoch",
                (l_epoch, r_epoch),
            )
            present = [int(row[0]) for row in cur.fetchall()]
        missing = []
        exp = l_epoch
        for e in present:
            while exp < e:
                missing.append(exp)
                exp += 1
            exp = e + 1
        while exp <= r_epoch:
            missing.append(exp)
            exp += 1
        return missing

    def _get_entry(self, epoch: int) -> Optional[bytes]:
        with self.connection() as cur:
            cur.execute("SELECT blob FROM duties WHERE epoch=?", (int(epoch),))
            row = cur.fetchone()
        if not row:
            return None
        return bytes(row[0])

    def get_epoch_blob(self, epoch: int) -> Optional[bytes]:
        return self._get_entry(epoch)

    def has_epoch(self, epoch: int) -> bool:
        with self.connection() as cur:
            cur.execute("SELECT 1 FROM duties WHERE epoch=? LIMIT 1", (int(epoch),))
            ok = cur.fetchone() is not None
        return ok

    def min_epoch(self) -> int:
        with self.connection() as cur:
            cur.execute("SELECT MIN(epoch) FROM duties")
            val = int(cur.fetchone()[0] or 0)
        return val

    def max_epoch(self) -> int:
        with self.connection() as cur:
            cur.execute("SELECT MAX(epoch) FROM duties")
            val = int(cur.fetchone()[0] or 0)
        return val

    def min_unprocessed_epoch(self, l_epoch: int, r_epoch: int) -> int | None:
        with self.connection() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM duties WHERE epoch BETWEEN ? AND ?",
                (l_epoch, r_epoch),
            )
            (count,) = cur.fetchone()
            expected_count = r_epoch - l_epoch + 1

            if count >= expected_count:
                # No gaps in the requested range
                return None

            cur.execute("SELECT 1 FROM duties WHERE epoch = ? LIMIT 1", (l_epoch,))
            if cur.fetchone() is None:
                return l_epoch

            # Find first gap in the requested range
            cur.execute(
                """
                SELECT epoch + 1 as missing_epoch
                FROM (
                    SELECT
                        epoch,
                        LAG(epoch, 1, epoch - 1) OVER (ORDER BY epoch) as prev_epoch
                    FROM duties
                    WHERE epoch BETWEEN ? AND ?
                    ORDER BY epoch
                )
                WHERE epoch - prev_epoch > 1
                LIMIT 1
                """,
                (l_epoch, r_epoch)
            )

            result = cur.fetchone()
            return result[0] if result else None

    def epochs_demand(self) -> dict[str, tuple[int, int]]:
        data = {}
        with self.connection() as cur:
            cur.execute("SELECT consumer, l_epoch, r_epoch FROM epochs_demand")
            demands = cur.fetchall()
            for consumer, l_epoch, r_epoch in demands:
                data[consumer] = (int(l_epoch), int(r_epoch))
        return data
