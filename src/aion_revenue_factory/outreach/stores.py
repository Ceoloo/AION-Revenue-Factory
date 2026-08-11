"""Durable operational stores — drop-in replacements for InMemoryOutreachStore.

The whole point: ``store = InMemoryOutreachStore()`` becomes
``store = PostgresOutreachStore(dsn)`` (or ``SqliteOutreachStore(path)``) with
**no change to the campaign engine, worker, or webhook processor** — all three
implement the identical ``OutreachStore`` protocol.

Design
------
One ``SqlOutreachStore`` implements the protocol against any DB-API 2.0
connection. Each entity is stored as a few indexed/queried columns plus a full
JSON ``data`` blob (lossless round-trip via ``serialization``). The two
integrity guarantees the engine relies on are enforced by the **database**, not
just application code:

- no duplicate sends  -> ``UNIQUE(idempotency_key)`` on the queue table, with
  ``INSERT ... ON CONFLICT DO NOTHING`` + ``rowcount`` telling us insert-vs-dup.
- idempotent events   -> ``UNIQUE(dedupe_key)`` on the events table, same trick.

So a crash/restart with 437 queued emails loses nothing: the rows are on disk,
and re-processing can't double-send because the constraints survive the restart.

``SqliteOutreachStore`` is stdlib-only (durable to a file, zero new deps).
``PostgresOutreachStore`` lazily imports ``psycopg`` (``pip install
'aion-revenue-factory[postgres]'``) and runs the exact same SQL.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from .enums import QueueStatus
from .models import (
    AIGeneration,
    Campaign,
    CampaignLead,
    EmailEvent,
    EmailMessage,
    Lead,
    QueueItem,
    SuppressionEntry,
)
from .serialization import (
    campaign_from_dict,
    campaign_lead_from_dict,
    event_from_dict,
    generation_from_dict,
    lead_from_dict,
    message_from_dict,
    queue_item_from_dict,
    suppression_from_dict,
    to_json,
)

# Portable DDL (TEXT/INTEGER only) so the identical schema works on sqlite and
# Postgres. See migrations/0001_outreach_operational.sql for the Postgres file.
_DDL = [
    """CREATE TABLE IF NOT EXISTS outreach_campaigns (
        id TEXT PRIMARY KEY, state TEXT, name TEXT, data TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS outreach_leads (
        id TEXT PRIMARY KEY, email TEXT, data TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS outreach_campaign_leads (
        id TEXT PRIMARY KEY, campaign_id TEXT, lead_id TEXT, data TEXT NOT NULL,
        UNIQUE (campaign_id, lead_id))""",
    """CREATE TABLE IF NOT EXISTS outreach_queue (
        id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
        campaign_id TEXT, lead_id TEXT, step_id TEXT, status TEXT,
        scheduled_at TEXT, completed_day TEXT, claimed_at TEXT, data TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS outreach_messages (
        id TEXT PRIMARY KEY, provider_message_id TEXT, data TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS outreach_events (
        id TEXT PRIMARY KEY, dedupe_key TEXT NOT NULL UNIQUE,
        campaign_id TEXT, event_type TEXT, data TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS outreach_generations (
        id TEXT PRIMARY KEY, campaign_id TEXT, data TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS outreach_suppression (
        email TEXT PRIMARY KEY, data TEXT NOT NULL)""",
]

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_outreach_queue_status ON outreach_queue (status)",
    "CREATE INDEX IF NOT EXISTS ix_outreach_queue_campaign ON outreach_queue (campaign_id)",
    "CREATE INDEX IF NOT EXISTS ix_outreach_queue_lead ON outreach_queue (lead_id)",
    "CREATE INDEX IF NOT EXISTS ix_outreach_queue_sched ON outreach_queue (scheduled_at)",
    "CREATE INDEX IF NOT EXISTS ix_outreach_queue_sentday ON outreach_queue (status, completed_day)",
    "CREATE INDEX IF NOT EXISTS ix_outreach_queue_claimed ON outreach_queue (status, claimed_at)",
    "CREATE INDEX IF NOT EXISTS ix_outreach_messages_provider ON outreach_messages (provider_message_id)",
    "CREATE INDEX IF NOT EXISTS ix_outreach_events_campaign ON outreach_events (campaign_id)",
    "CREATE INDEX IF NOT EXISTS ix_outreach_events_type ON outreach_events (event_type)",
    "CREATE INDEX IF NOT EXISTS ix_outreach_cleads_campaign ON outreach_campaign_leads (campaign_id)",
    "CREATE INDEX IF NOT EXISTS ix_outreach_generations_campaign ON outreach_generations (campaign_id)",
]


@dataclass(frozen=True)
class Dialect:
    """Minimal per-driver differences."""

    placeholder: str = "?"  # sqlite "?", psycopg "%s"
    # SELECT ... FOR UPDATE SKIP LOCKED is the Postgres claim primitive; sqlite
    # has no row locks (it serializes writers), so it claims under BEGIN IMMEDIATE.
    supports_skip_locked: bool = False
    # Statement that opens the claim transaction. Empty means the driver starts
    # one implicitly on the first statement (psycopg with autocommit off).
    begin_stmt: str = "BEGIN IMMEDIATE"


SQLITE = Dialect(placeholder="?", supports_skip_locked=False, begin_stmt="BEGIN IMMEDIATE")
POSTGRES = Dialect(placeholder="%s", supports_skip_locked=True, begin_stmt="")


def _col_dt(dt: Optional[datetime]) -> Optional[str]:
    """Canonical UTC ISO string for a timestamp column (stable lexical order)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


class SqlOutreachStore:
    """OutreachStore backed by any DB-API 2.0 connection."""

    def __init__(self, connection, dialect: Dialect = SQLITE, *, ensure_schema: bool = True) -> None:
        self._conn = connection
        self._dialect = dialect
        self._lock = threading.RLock()
        if ensure_schema:
            self.ensure_schema()

    # ---- low-level ----
    def _q(self, sql: str) -> str:
        if self._dialect.placeholder == "?":
            return sql
        return sql.replace("?", self._dialect.placeholder)

    def _exec(self, sql: str, params: tuple = (), *, fetch: Optional[str] = None):
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(self._q(sql), params)
                if fetch == "one":
                    row = cur.fetchone()
                    result = row
                elif fetch == "all":
                    result = cur.fetchall()
                else:
                    result = cur.rowcount
                self._conn.commit()
                return result
            finally:
                cur.close()

    def _transaction(self, work: Callable):
        """Run ``work(cursor)`` in one atomic transaction (for claim/reclaim)."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                if self._dialect.begin_stmt:
                    cur.execute(self._dialect.begin_stmt)
                result = work(cur)
                self._conn.commit()
                return result
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def ensure_schema(self) -> None:
        for stmt in _DDL:
            self._exec(stmt)
        for stmt in _INDEXES:
            self._exec(stmt)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _norm(email: str) -> str:
        return email.strip().lower()

    # ---- campaigns ----
    def save_campaign(self, campaign: Campaign) -> None:
        self._exec(
            "INSERT INTO outreach_campaigns (id, state, name, data) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET state=excluded.state, name=excluded.name, data=excluded.data",
            (campaign.id, campaign.state.value, campaign.name, to_json(campaign)),
        )

    def get_campaign(self, campaign_id: str) -> Optional[Campaign]:
        row = self._exec("SELECT data FROM outreach_campaigns WHERE id=?", (campaign_id,), fetch="one")
        return campaign_from_dict(_json(row[0])) if row else None

    def campaigns(self) -> list[Campaign]:
        rows = self._exec("SELECT data FROM outreach_campaigns ORDER BY id", fetch="all")
        return [campaign_from_dict(_json(r[0])) for r in rows]

    # ---- leads ----
    def save_lead(self, lead: Lead) -> None:
        self._exec(
            "INSERT INTO outreach_leads (id, email, data) VALUES (?, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET email=excluded.email, data=excluded.data",
            (lead.id, self._norm(lead.email), to_json(lead)),
        )

    def get_lead(self, lead_id: str) -> Optional[Lead]:
        row = self._exec("SELECT data FROM outreach_leads WHERE id=?", (lead_id,), fetch="one")
        return lead_from_dict(_json(row[0])) if row else None

    def leads(self) -> list[Lead]:
        rows = self._exec("SELECT data FROM outreach_leads ORDER BY id", fetch="all")
        return [lead_from_dict(_json(r[0])) for r in rows]

    # ---- campaign membership ----
    def save_campaign_lead(self, cl: CampaignLead) -> None:
        self._exec(
            "INSERT INTO outreach_campaign_leads (id, campaign_id, lead_id, data) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET data=excluded.data",
            (cl.id, cl.campaign_id, cl.lead_id, to_json(cl)),
        )

    def campaign_leads(self, campaign_id: str) -> list[CampaignLead]:
        rows = self._exec(
            "SELECT data FROM outreach_campaign_leads WHERE campaign_id=? ORDER BY id",
            (campaign_id,), fetch="all",
        )
        return [campaign_lead_from_dict(_json(r[0])) for r in rows]

    def get_campaign_lead(self, campaign_id: str, lead_id: str) -> Optional[CampaignLead]:
        row = self._exec(
            "SELECT data FROM outreach_campaign_leads WHERE campaign_id=? AND lead_id=?",
            (campaign_id, lead_id), fetch="one",
        )
        return campaign_lead_from_dict(_json(row[0])) if row else None

    # ---- queue ----
    @staticmethod
    def _completed_day(item: QueueItem) -> Optional[str]:
        if item.status is QueueStatus.SENT and item.completed_at is not None:
            return item.completed_at.date().isoformat()
        return None

    def enqueue(self, item: QueueItem) -> bool:
        rowcount = self._exec(
            "INSERT INTO outreach_queue "
            "(id, idempotency_key, campaign_id, lead_id, step_id, status, scheduled_at, completed_day, claimed_at, data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (idempotency_key) DO NOTHING",
            (
                item.id, item.idempotency_key, item.campaign_id, item.lead_id, item.step_id,
                item.status.value, _col_dt(item.scheduled_at),
                self._completed_day(item), _col_dt(item.claimed_at), to_json(item),
            ),
        )
        return bool(rowcount)

    def has_queue_key(self, idempotency_key: str) -> bool:
        row = self._exec(
            "SELECT 1 FROM outreach_queue WHERE idempotency_key=?", (idempotency_key,), fetch="one"
        )
        return row is not None

    def queue_items(self, status: Optional[QueueStatus] = None) -> list[QueueItem]:
        if status is not None:
            rows = self._exec(
                "SELECT data FROM outreach_queue WHERE status=? ORDER BY scheduled_at, id",
                (status.value,), fetch="all",
            )
        else:
            rows = self._exec("SELECT data FROM outreach_queue ORDER BY scheduled_at, id", fetch="all")
        return [queue_item_from_dict(_json(r[0])) for r in rows]

    def save_queue_item(self, item: QueueItem) -> None:
        self._exec(
            "INSERT INTO outreach_queue "
            "(id, idempotency_key, campaign_id, lead_id, step_id, status, scheduled_at, completed_day, claimed_at, data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET status=excluded.status, scheduled_at=excluded.scheduled_at, "
            "completed_day=excluded.completed_day, claimed_at=excluded.claimed_at, data=excluded.data",
            (
                item.id, item.idempotency_key, item.campaign_id, item.lead_id, item.step_id,
                item.status.value, _col_dt(item.scheduled_at),
                self._completed_day(item), _col_dt(item.claimed_at), to_json(item),
            ),
        )

    def claim_due(self, now: datetime, limit: int, worker_id: str = "") -> list[QueueItem]:
        """Atomically claim up to ``limit`` due PENDING items across workers.

        Postgres selects candidates ``FOR UPDATE SKIP LOCKED`` (concurrent
        workers never see each other's rows); sqlite claims under a
        ``BEGIN IMMEDIATE`` write transaction. In both cases the per-row
        ``UPDATE ... WHERE id=? AND status='pending'`` guard is the atomic
        commit point, so an item is claimed by exactly one worker.
        """
        if limit <= 0:
            return []
        now_iso = _col_dt(now)
        lock_clause = " FOR UPDATE SKIP LOCKED" if self._dialect.supports_skip_locked else ""

        def work(cur):
            cur.execute(self._q(
                "SELECT id, data FROM outreach_queue WHERE status=? AND scheduled_at <= ? "
                "ORDER BY scheduled_at LIMIT ?" + lock_clause),
                (QueueStatus.PENDING.value, now_iso, limit))
            rows = cur.fetchall()
            claimed: list[QueueItem] = []
            for item_id, data in rows:
                item = queue_item_from_dict(_json(data))
                item.status = QueueStatus.PROCESSING
                item.claimed_by = worker_id
                item.claimed_at = _now_utc(now)
                cur.execute(self._q(
                    "UPDATE outreach_queue SET status=?, claimed_at=?, data=? "
                    "WHERE id=? AND status=?"),
                    (item.status.value, _col_dt(item.claimed_at), to_json(item),
                     item_id, QueueStatus.PENDING.value))
                if cur.rowcount == 1:
                    claimed.append(item)
            return claimed

        return self._transaction(work)

    def reclaim_stale(self, now: datetime, older_than_seconds: float) -> int:
        """Return items claimed before the cutoff to PENDING (crashed workers)."""
        cutoff = _now_utc(now) - timedelta(seconds=older_than_seconds)
        cutoff_iso = _col_dt(cutoff)

        def work(cur):
            cur.execute(self._q(
                "SELECT id, data FROM outreach_queue "
                "WHERE status=? AND claimed_at IS NOT NULL AND claimed_at < ?"),
                (QueueStatus.PROCESSING.value, cutoff_iso))
            rows = cur.fetchall()
            for item_id, data in rows:
                item = queue_item_from_dict(_json(data))
                item.status = QueueStatus.PENDING
                item.claimed_by = ""
                item.claimed_at = None
                cur.execute(self._q(
                    "UPDATE outreach_queue SET status=?, claimed_at=?, data=? WHERE id=?"),
                    (item.status.value, None, to_json(item), item_id))
            return len(rows)

        return self._transaction(work)

    def sends_on(self, day_iso: str, campaign_id: Optional[str] = None) -> int:
        if campaign_id is not None:
            row = self._exec(
                "SELECT COUNT(*) FROM outreach_queue WHERE status=? AND completed_day=? AND campaign_id=?",
                (QueueStatus.SENT.value, day_iso, campaign_id), fetch="one",
            )
        else:
            row = self._exec(
                "SELECT COUNT(*) FROM outreach_queue WHERE status=? AND completed_day=?",
                (QueueStatus.SENT.value, day_iso), fetch="one",
            )
        return int(row[0]) if row else 0

    # ---- messages ----
    def save_message(self, message: EmailMessage) -> None:
        self._exec(
            "INSERT INTO outreach_messages (id, provider_message_id, data) VALUES (?, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET provider_message_id=excluded.provider_message_id, data=excluded.data",
            (message.id, message.provider_message_id, to_json(message)),
        )

    def get_message(self, message_id: str) -> Optional[EmailMessage]:
        row = self._exec("SELECT data FROM outreach_messages WHERE id=?", (message_id,), fetch="one")
        return message_from_dict(_json(row[0])) if row else None

    def message_by_provider_id(self, provider_message_id: str) -> Optional[EmailMessage]:
        if not provider_message_id:
            return None
        row = self._exec(
            "SELECT data FROM outreach_messages WHERE provider_message_id=? LIMIT 1",
            (provider_message_id,), fetch="one",
        )
        return message_from_dict(_json(row[0])) if row else None

    # ---- events ----
    def record_event(self, event: EmailEvent) -> bool:
        rowcount = self._exec(
            "INSERT INTO outreach_events (id, dedupe_key, campaign_id, event_type, data) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT (dedupe_key) DO NOTHING",
            (event.id, event.dedupe_key, event.campaign_id, event.event_type.value, to_json(event)),
        )
        return bool(rowcount)

    def events(self) -> list[EmailEvent]:
        rows = self._exec("SELECT data FROM outreach_events ORDER BY id", fetch="all")
        return [event_from_dict(_json(r[0])) for r in rows]

    # ---- generations ----
    def save_generation(self, generation: AIGeneration) -> None:
        self._exec(
            "INSERT INTO outreach_generations (id, campaign_id, data) VALUES (?, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET data=excluded.data",
            (generation.id, generation.campaign_id, to_json(generation)),
        )

    def generations(self) -> list[AIGeneration]:
        rows = self._exec("SELECT data FROM outreach_generations ORDER BY id", fetch="all")
        return [generation_from_dict(_json(r[0])) for r in rows]

    # ---- suppression ----
    def add_suppression(self, entry: SuppressionEntry) -> None:
        self._exec(
            "INSERT INTO outreach_suppression (email, data) VALUES (?, ?) "
            "ON CONFLICT (email) DO UPDATE SET data=excluded.data",
            (self._norm(entry.email), to_json(entry)),
        )

    def is_suppressed(self, email: str) -> bool:
        row = self._exec(
            "SELECT 1 FROM outreach_suppression WHERE email=?", (self._norm(email),), fetch="one"
        )
        return row is not None

    def suppression_entries(self) -> list[SuppressionEntry]:
        rows = self._exec("SELECT data FROM outreach_suppression ORDER BY email", fetch="all")
        return [suppression_from_dict(_json(r[0])) for r in rows]


def _json(value):
    import json

    return json.loads(value)


def _now_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class SqliteOutreachStore(SqlOutreachStore):
    """Durable, stdlib-only store (sqlite). Great for a single-node deployment.

    ``path=":memory:"`` gives an ephemeral store; a file path persists across
    restarts. Uses ``check_same_thread=False`` + the base lock so the worker and
    the HTTP surface can share one connection safely.
    """

    def __init__(self, path: str = ":memory:") -> None:
        import sqlite3

        # isolation_level=None -> autocommit: normal writes commit immediately,
        # and the claim path manages its own BEGIN IMMEDIATE transaction. WAL +
        # busy_timeout let concurrent worker processes serialize cleanly rather
        # than error with "database is locked".
        conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        super().__init__(conn, SQLITE)


class PostgresOutreachStore(SqlOutreachStore):
    """Durable, production store backed by Postgres/Supabase via ``psycopg`` (v3).

    Install the driver: ``pip install 'aion-revenue-factory[postgres]'``. Pass a
    DSN/connection string (``postgresql://user:pass@host:5432/db``) or an already
    open connection. The SQL is identical to the sqlite path (only the parameter
    placeholder differs), so the engine cannot tell which backend it is on.
    """

    def __init__(
        self,
        dsn: str = "",
        *,
        connection=None,
        connect: Optional[Callable] = None,
        ensure_schema: bool = True,
    ) -> None:
        if connection is None:
            if connect is not None:
                connection = connect()
            else:
                try:
                    import psycopg  # type: ignore
                except ImportError as exc:  # pragma: no cover - env-dependent
                    raise RuntimeError(
                        "PostgresOutreachStore requires psycopg. Install with "
                        "`pip install 'aion-revenue-factory[postgres]'`."
                    ) from exc
                # autocommit off: the claim path relies on an explicit
                # transaction so SELECT ... FOR UPDATE SKIP LOCKED holds its row
                # locks until the claiming UPDATEs commit. Ordinary writes commit
                # per-statement via _exec.
                connection = psycopg.connect(dsn, autocommit=False)
        super().__init__(connection, POSTGRES, ensure_schema=ensure_schema)
