"""24-hour in-memory cache of search responses."""

import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any

TTL_SECONDS = 24 * 60 * 60
MAX_ENTRIES = 200


class TTLCache:
    """Keeps up to `max_entries` responses for `ttl` seconds, evicting the least recently used.

    A response whose `status` is "failed" is never stored.
    """

    def __init__(
        self,
        ttl: float = TTL_SECONDS,
        max_entries: int = MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.ttl = ttl
        self.max_entries = max_entries
        self._clock = clock
        self._items: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._items)

    def get(self, key: Hashable) -> Any | None:
        item = self._items.get(key)
        if item is None:
            return None
        stored_at, value = item
        if self._clock() - stored_at >= self.ttl:
            del self._items[key]
            return None
        self._items.move_to_end(key)
        return value

    def set(self, key: Hashable, value: Any) -> bool:
        """Store `value` under `key`. Returns False, storing nothing, for a failed response."""
        if value.status == "failed":
            return False
        self._items[key] = (self._clock(), value)
        self._items.move_to_end(key)
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)
        return True
