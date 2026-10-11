"""The TTL cache, and AC6: an identical search within 24 hours is served from cache with no arXiv request."""

from dataclasses import dataclass
from datetime import date

import pytest

from app.cache import TTLCache, cached_search
from app.topic import build_query

DAY = 24 * 60 * 60
TODAY = date(2026, 10, 11)
TERMS = ["diffusion", "models", "time", "series"]
EXACT = build_query("exact", TERMS, None, None, TODAY)


@dataclass
class Response:
    status: str
    message: str = ""


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def key(n):
    return ((f"term{n}",), None, None, 20)


def test_hit_before_24_hours():
    clock = Clock()
    cache = TTLCache(clock=clock)
    stored = Response("completed", "Found 12 papers in 1 search.")
    cache.set(key(1), stored)
    clock.now += DAY - 1
    assert cache.get(key(1)) is stored


def test_miss_after_24_hours():
    clock = Clock()
    cache = TTLCache(clock=clock)
    cache.set(key(1), Response("completed"))
    clock.now += DAY
    assert cache.get(key(1)) is None
    assert len(cache) == 0, "an expired entry is removed"


def test_miss_for_a_different_key():
    cache = TTLCache(clock=Clock())
    cache.set(key(1), Response("completed"))
    assert cache.get(key(2)) is None
    assert cache.get((("term1",), "cs.LG", None, 20)) is None


def test_least_recently_used_entry_is_evicted_at_201_entries():
    cache = TTLCache(clock=Clock())
    for n in range(200):
        cache.set(key(n), Response("completed"))
    assert cache.get(key(0)) is not None  # key 0 becomes the most recently used
    cache.set(key(200), Response("completed"))
    assert len(cache) == 200
    assert cache.get(key(1)) is None, "key 1 was the least recently used"
    assert cache.get(key(0)) is not None
    assert cache.get(key(200)) is not None


def test_setting_an_existing_key_refreshes_it():
    clock = Clock()
    cache = TTLCache(clock=clock)
    cache.set(key(1), Response("partial"))
    clock.now += DAY - 10
    newer = Response("completed")
    cache.set(key(1), newer)
    clock.now += 20
    assert cache.get(key(1)) is newer
    assert len(cache) == 1


def test_completed_partial_and_empty_are_stored():
    cache = TTLCache(clock=Clock())
    for n, status in enumerate(["completed", "partial", "empty"]):
        assert cache.set(key(n), Response(status)) is True
        assert cache.get(key(n)).status == status


def test_failed_is_never_stored():
    cache = TTLCache(clock=Clock())
    assert cache.set(key(1), Response("failed")) is False
    assert cache.get(key(1)) is None
    assert len(cache) == 0


def test_failed_does_not_replace_a_stored_response():
    cache = TTLCache(clock=Clock())
    good = Response("completed")
    cache.set(key(1), good)
    cache.set(key(1), Response("failed"))
    assert cache.get(key(1)) is good


# --- cached_search (AC6) -----------------------------------------------------------------


@pytest.mark.anyio
async def test_identical_search_within_24_hours_makes_no_arxiv_request(arxiv):
    client, log = arxiv({EXACT: "normal.xml"})
    clock = Clock()
    cache = TTLCache(clock=clock)

    first = await cached_search(TERMS, None, None, 20, client, TODAY, cache)
    assert first.cached is False
    assert len(log) == 1

    clock.now += DAY - 1
    second = await cached_search(TERMS, None, None, 20, client, TODAY, cache)
    assert len(log) == 1, "a cache hit must not call arXiv"
    assert second.cached is True
    assert second.message == first.message
    assert second.trace == first.trace
    assert second.papers == first.papers
    assert second.groups == first.groups
    assert second.status == first.status


@pytest.mark.anyio
async def test_same_search_after_24_hours_calls_arxiv_again(arxiv):
    client, log = arxiv({EXACT: "normal.xml"})
    clock = Clock()
    cache = TTLCache(clock=clock)
    await cached_search(TERMS, None, None, 20, client, TODAY, cache)
    clock.now += DAY
    again = await cached_search(TERMS, None, None, 20, client, TODAY, cache)
    assert len(log) == 2
    assert again.cached is False


@pytest.mark.anyio
async def test_failed_search_is_not_cached_so_a_retry_calls_arxiv(arxiv):
    client, log = arxiv({EXACT: 500})
    cache = TTLCache(clock=Clock())
    first = await cached_search(TERMS, None, None, 20, client, TODAY, cache)
    second = await cached_search(TERMS, None, None, 20, client, TODAY, cache)
    assert (first.status, second.status) == ("failed", "failed")
    assert second.cached is False
    assert len(log) == 2
    assert len(cache) == 0


@pytest.mark.anyio
async def test_empty_search_is_cached(arxiv):
    terms = ["zxqv", "blorptastic"]
    routes = {build_query(s, terms, None, None, TODAY): "empty.xml" for s in ("exact", "all_words", "any_word")}
    client, log = arxiv(routes)
    cache = TTLCache(clock=Clock())
    await cached_search(terms, None, None, 20, client, TODAY, cache)
    second = await cached_search(terms, None, None, 20, client, TODAY, cache)
    assert (second.status, second.cached, len(log)) == ("empty", True, 3)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("category", "from_year", "max_papers"),
    [("cs.LG", None, 20), (None, 2020, 20), (None, None, 10)],
    ids=["other-category", "other-from-year", "other-max-papers"],
)
async def test_different_inputs_are_not_served_from_cache(arxiv, category, from_year, max_papers):
    other = build_query("exact", TERMS, category, from_year, TODAY)
    client, log = arxiv({EXACT: "normal.xml", other: "normal.xml"})
    cache = TTLCache(clock=Clock())
    await cached_search(TERMS, None, None, 20, client, TODAY, cache)
    result = await cached_search(TERMS, category, from_year, max_papers, client, TODAY, cache)
    assert result.cached is False
    assert len(log) == 2


@pytest.mark.anyio
async def test_changing_a_returned_response_does_not_change_the_cache(arxiv):
    client, _ = arxiv({EXACT: "normal.xml"})
    cache = TTLCache(clock=Clock())
    first = await cached_search(TERMS, None, None, 20, client, TODAY, cache)
    first.papers.clear()
    first.message = "changed"
    hit = await cached_search(TERMS, None, None, 20, client, TODAY, cache)
    assert hit.message == "Found 12 papers in 1 search."
    assert len(hit.papers) == 12
    hit.trace.clear()
    assert len((await cached_search(TERMS, None, None, 20, client, TODAY, cache)).trace) == 1
