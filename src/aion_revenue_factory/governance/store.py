"""Pluggable persistence for the Agent Governance Ledger.

Two concerns are stored:

* the **agent registry** -- the current :class:`AgentIdentity` for each agent;
* the **action ledger** -- the append-only, hash-chained sequence of
  :class:`ActionRecord` entries across all agents.

Two reference stores are provided, mirroring the orchestration package:

* :class:`InMemoryLedgerStore` -- fast, for tests and single-process use.
* :class:`JsonlLedgerStore`   -- durable append-only JSONL snapshots.

Product repositories that already run Postgres/Supabase should implement the
:class:`LedgerStore` protocol against it (see ``agent_governance`` tables in
``aion-unified-schema.sql``) rather than introducing a parallel ledger.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Iterable, Optional, Protocol

from .models import AgentIdentity, ActionRecord

GENESIS_HASH = "0" * 64


class LedgerStore(Protocol):
    # -- agent registry --
    def save_agent(self, agent: AgentIdentity) -> None: ...
    def get_agent(self, agent_id: str) -> Optional[AgentIdentity]: ...
    def list_agents(self) -> Iterable[AgentIdentity]: ...

    # -- action ledger --
    def append_record(self, record: ActionRecord) -> None: ...
    def last_hash(self) -> str: ...
    def list_records(self, agent_id: Optional[str] = None) -> Iterable[ActionRecord]: ...


class InMemoryLedgerStore:
    def __init__(self) -> None:
        self._agents: dict[str, AgentIdentity] = {}
        self._records: list[ActionRecord] = []
        self._last_hash = GENESIS_HASH
        self._lock = threading.RLock()

    def save_agent(self, agent: AgentIdentity) -> None:
        with self._lock:
            self._agents[agent.agent_id] = agent

    def get_agent(self, agent_id: str) -> Optional[AgentIdentity]:
        with self._lock:
            return self._agents.get(agent_id)

    def list_agents(self) -> Iterable[AgentIdentity]:
        with self._lock:
            return list(self._agents.values())

    def append_record(self, record: ActionRecord) -> None:
        with self._lock:
            self._records.append(record)
            self._last_hash = record.entry_hash

    def last_hash(self) -> str:
        with self._lock:
            return self._last_hash

    def list_records(self, agent_id: Optional[str] = None) -> Iterable[ActionRecord]:
        with self._lock:
            if agent_id is None:
                return list(self._records)
            return [r for r in self._records if r.agent_id == agent_id]


class JsonlLedgerStore:
    """Durable store backed by two append-only JSONL files.

    * ``<path>``            -- the action ledger (one sealed record per line);
    * ``<path>.agents``     -- agent registry snapshots (latest per id wins).

    Append is crash-safe: a partial trailing line is skipped on read. The
    action ledger is never rewritten, which is what keeps the hash chain
    trustworthy on disk.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self.agents_path = f"{path}.agents"
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)

    # -- agent registry --
    def save_agent(self, agent: AgentIdentity) -> None:
        with self._lock:
            with open(self.agents_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(agent.to_dict(), separators=(",", ":")) + "\n")

    def _load_agents(self) -> dict[str, dict]:
        snapshots: dict[str, dict] = {}
        if not os.path.exists(self.agents_path):
            return snapshots
        with open(self.agents_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                snapshots[obj["agent_id"]] = obj
        return snapshots

    def get_agent(self, agent_id: str) -> Optional[AgentIdentity]:
        obj = self._load_agents().get(agent_id)
        return AgentIdentity.from_dict(obj) if obj else None

    def list_agents(self) -> Iterable[AgentIdentity]:
        return [AgentIdentity.from_dict(o) for o in self._load_agents().values()]

    # -- action ledger --
    def append_record(self, record: ActionRecord) -> None:
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record.to_dict(), separators=(",", ":")) + "\n")

    def _load_records(self) -> list[ActionRecord]:
        records: list[ActionRecord] = []
        if not os.path.exists(self.path):
            return records
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue  # skip partial trailing write
                records.append(ActionRecord.from_dict(obj))
        return records

    def last_hash(self) -> str:
        with self._lock:
            records = self._load_records()
            return records[-1].entry_hash if records else GENESIS_HASH

    def list_records(self, agent_id: Optional[str] = None) -> Iterable[ActionRecord]:
        records = self._load_records()
        if agent_id is None:
            return records
        return [r for r in records if r.agent_id == agent_id]
