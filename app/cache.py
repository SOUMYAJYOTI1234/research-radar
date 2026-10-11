"""24-hour in-memory cache of search responses."""

import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from datetime import date
from typing import Any

from app.arxiv_client import ArxivClient
from app.models import SearchResponse
from app.search_loop import run_search

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


# The process-wide cache used by the API route. Lost on restart, which the spec accepts.
SEARCH_CACHE = TTLCache()


async def cached_search(
    topic_terms: list[str],
    category: str | None,
    from_year: int | None,
    max_papers: int,
    client: ArxivClient,
    today: date,
    cache: TTLCache | None = None,
) -> SearchResponse:
    """run_search() behind the 24-hour cache. A hit makes no arXiv request and has cached=True."""
    cache = SEARCH_CACHE if cache is None else cache
    key = (tuple(topic_terms), category, from_year, max_papers)
    stored = cache.get(key)
    if stored is not None:
        return stored.model_copy(update={"cached": True}, deep=True)
    response = await run_search(topic_terms, category, from_year, max_papers, client, today)
    # Store a copy, so a caller changing the returned response cannot change later hits.
    cache.set(key, response.model_copy(deep=True))
    return response
