import sqlite3
from typing import Dict, Optional, Sequence

from src import variables
from src.modules.performance_collector.codec import ProposalDuty, SyncDuty, EpochBlobCodec, AttMissDuty
from src.modules.performance_collector.types import AttestationCommittees, ProposeDuties, SyncCommittees
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
        att_misses: set[AttMissDuty],
        proposals: Sequence[ProposalDuty] | None = None,
        sync_misses: Sequence[SyncDuty] | None = None,
    ) -> bytes:

        blob = EpochBlobCodec.encode(att_misses, proposals, sync_misses)

        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO duties(epoch, blob) VALUES(?, ?)",
            (epoch, sqlite3.Binary(blob)),
        )
        conn.commit()
        conn.close()
        return blob

    def store_epoch_from_duties(
        self,
        epoch: EpochNumber,
        att_committees: AttestationCommittees,
        propose_duties: ProposeDuties,
        sync_committees: SyncCommittees,
    ) -> bytes:
        att_misses = set()
        for committee in att_committees.values():
            for duty in committee:
                if not duty.included:
                    att_misses.add(duty.validator_index)

        proposals_list: list[ProposalDuty] = []
        for proposer_duty in propose_duties.values():
            proposals_list.append(
                ProposalDuty(validator_index=proposer_duty.validator_index, is_proposed=proposer_duty.included)
            )

        # FIXME: should we get it like a map?
        sync_miss_map: Dict[int, int] = {}
        for duties in sync_committees.values():
            for duty in duties:
                vid = duty.validator_index
                if sync_miss_map.get(vid) is None:
                    sync_miss_map[duty.validator_index] = 0
                if not duty.included:
                    sync_miss_map[vid] += 1
        sync_misses: list[SyncDuty] = [
            SyncDuty(validator_index=vid, missed_count=cnt) for vid, cnt in sync_miss_map.items()
        ]

        blob = self.store_epoch(epoch, att_misses, proposals_list, sync_misses)

        self._auto_prune(epoch)

        return blob

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
