import sqlite3
from typing import Optional

from src import variables
from src.modules.performance_collector.codec import ProposalDuty, SyncDuty, EpochDataCodec, AttDutyMisses
from src.types import EpochNumber


class DutiesDB:
    def __init__(self, path: str, *, default_num_validators: Optional[int] = None):
        self.path = path
        self.default_num_validators = default_num_validators
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        return conn

    def _init_schema(self):
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS duties
            (
                epoch INTEGER PRIMARY KEY,
                blob BLOB NOT NULL
            );
            """
        )
        conn.commit()
        conn.close()

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
        conn = self._connect()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT OR REPLACE INTO duties(epoch, blob) VALUES(?, ?)",
                (epoch, sqlite3.Binary(blob)),
            )
            conn.commit()
        finally:
            conn.close()

    def _auto_prune(self, current_epoch: int) -> None:
        retention = int(getattr(variables, 'PERFORMANCE_COLLECTOR_RETENTION_EPOCHS', 0))
        if retention <= 0:
            return
        threshold = int(current_epoch) - retention
        if threshold <= 0:
            return
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM duties WHERE epoch < ?", (threshold,))
            conn.commit()
        finally:
            conn.close()

    def is_range_available(self, l_epoch: int, r_epoch: int) -> bool:
        if int(l_epoch) > int(r_epoch):
            raise ValueError("Invalid epoch range")
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(1) FROM duties WHERE epoch BETWEEN ? AND ?",
            (int(l_epoch), int(r_epoch)),
        )
        (cnt,) = cur.fetchone() or (0,)
        conn.close()
        return int(cnt) == (r_epoch - l_epoch + 1)

    def missing_epochs_in(self, l_epoch: int, r_epoch: int) -> list[int]:
        if l_epoch > r_epoch:
            raise ValueError("Invalid epoch range")
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT epoch FROM duties WHERE epoch BETWEEN ? AND ? ORDER BY epoch",
            (l_epoch, r_epoch),
        )
        present = [int(row[0]) for row in cur.fetchall()]
        conn.close()
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
        conn = self._connect()
        cur = conn.cursor()
        cur.execute("SELECT blob FROM duties WHERE epoch=?", (int(epoch),))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return bytes(row[0])

    def get_epoch_blob(self, epoch: int) -> Optional[bytes]:
        return self._get_entry(epoch)

    def has_epoch(self, epoch: int) -> bool:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM duties WHERE epoch=? LIMIT 1", (int(epoch),))
        ok = cur.fetchone() is not None
        conn.close()
        return ok

    def min_epoch(self) -> int:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute("SELECT MIN(epoch) FROM duties")
        val = int(cur.fetchone()[0] or 0)
        conn.close()
        return val

    def max_epoch(self) -> int:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute("SELECT MAX(epoch) FROM duties")
        val = int(cur.fetchone()[0] or 0)
        conn.close()
        return val

    def min_unprocessed_epoch(self) -> int:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute("SELECT MIN(epoch), MAX(epoch) FROM duties")
        row = cur.fetchone()
        if not row or row[0] is None or row[1] is None:
            conn.close()
            return 0
        l_epoch, r_epoch = int(row[0]), int(row[1])
        cur.execute(
            """
            SELECT MIN(t.epoch + 1)
            FROM duties t
            LEFT JOIN duties d2 ON d2.epoch = t.epoch + 1
            WHERE t.epoch BETWEEN ? AND ? AND d2.epoch IS NULL
            """,
            (l_epoch, r_epoch),
        )
        (missing,) = cur.fetchone()
        conn.close()
        return int(missing) if missing else (r_epoch + 1)
