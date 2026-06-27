from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class QueryState:
    query_id: str
    owner_id: str | None = None
    cancelled: bool = False
    cancel_callbacks: list[Callable[[], None]] = field(default_factory=list)


class _CancelHandle:
    def __init__(self, registry: "QueryRegistry", query_id: str, callback: Callable[[], None]):
        self._registry = registry
        self._query_id = query_id
        self._callback = callback

    def close(self) -> None:
        self._registry.detach(self._query_id, self._callback)


class QueryRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._queries: dict[str, QueryState] = {}

    def register(self, query_id: str, owner_id: str | None = None) -> QueryState:
        with self._lock:
            state = QueryState(query_id=query_id, owner_id=owner_id)
            self._queries[query_id] = state
            return state

    def finish(self, query_id: str) -> None:
        with self._lock:
            self._queries.pop(query_id, None)

    def attach(self, query_id: str, callback: Callable[[], None]) -> _CancelHandle:
        with self._lock:
            state = self._queries.setdefault(query_id, QueryState(query_id=query_id))
            state.cancel_callbacks.append(callback)
            cancelled = state.cancelled
        if cancelled:
            callback()
        return _CancelHandle(self, query_id, callback)

    def detach(self, query_id: str, callback: Callable[[], None]) -> None:
        with self._lock:
            state = self._queries.get(query_id)
            if not state:
                return
            state.cancel_callbacks = [cb for cb in state.cancel_callbacks if cb is not callback]

    def cancel(self, query_id: str, owner_id: str | None = None) -> bool:
        with self._lock:
            state = self._queries.get(query_id)
            if state is None:
                return False
            if owner_id is not None and state.owner_id is not None and state.owner_id != owner_id:
                return False
            state.cancelled = True
            callbacks = list(state.cancel_callbacks)
        for callback in callbacks:
            try:
                callback()
            except Exception:
                pass
        return True

    def is_cancelled(self, query_id: str) -> bool:
        with self._lock:
            return bool(self._queries.get(query_id).cancelled if query_id in self._queries else False)


query_registry = QueryRegistry()
