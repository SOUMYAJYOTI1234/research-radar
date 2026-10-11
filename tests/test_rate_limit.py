"""AC7: two outbound arXiv requests are never less than 3 seconds apart."""

import asyncio

import httpx
import pytest

from app import arxiv_client
from app.arxiv_client import ArxivClient, ArxivUnavailable, RateLimiter

pytestmark = pytest.mark.anyio


async def test_consecutive_starts_are_at_least_3_seconds_apart(limiter, fake_clock):
    starts = []
    for _ in range(4):
        async with limiter.slot():
            starts.append(fake_clock())
    assert starts == [0.0, 3.0, 6.0, 9.0]
    assert fake_clock.sleeps == [3.0, 3.0, 3.0]


async def test_no_wait_once_3_seconds_have_passed(limiter, fake_clock):
    async with limiter.slot():
        pass
    fake_clock.now += 3.0
    async with limiter.slot():
        pass
    fake_clock.now += 7.5
    async with limiter.slot():
        pass
    assert fake_clock.sleeps == []


async def test_interval_is_measured_from_the_previous_start(limiter, fake_clock):
    async with limiter.slot():
        fake_clock.now += 2.0  # the first request takes 2 s
    async with limiter.slot():
        second_start = fake_clock()
    assert fake_clock.sleeps == [1.0]
    assert second_start == 3.0


async def test_second_request_does_not_start_until_the_first_finishes(mock_arxiv, limiter, fake_clock):
    gate = asyncio.Event()
    events = []

    async def handler(request):
        query = request.url.params["search_query"]
        events.append(f"start {query} at {fake_clock()}")
        if query == "first":
            await gate.wait()
        events.append(f"end {query}")
        return httpx.Response(200, content=b"<not-a-feed/>")

    client = ArxivClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)), limiter)
    first = asyncio.create_task(client.fetch("first"))
    second = asyncio.create_task(client.fetch("second"))
    for _ in range(20):
        await asyncio.sleep(0)
    assert events == ["start first at 0.0"], "second request started while the first was in flight"

    fake_clock.now += 1.0  # the first request takes 1 s in total
    gate.set()
    for task in (first, second):
        with pytest.raises(ArxivUnavailable):
            await task
    assert events == ["start first at 0.0", "end first", "start second at 3.0", "end second"]


async def test_lock_is_released_after_a_failed_request(arxiv, fake_clock):
    client, log = arxiv({"q": 500})
    for _ in range(2):
        with pytest.raises(ArxivUnavailable):
            await client.fetch("q")
    assert len(log) == 2
    assert fake_clock.sleeps == [3.0]


async def test_clients_share_one_process_wide_limiter(mock_arxiv):
    first = ArxivClient(mock_arxiv({})[0])
    second = ArxivClient(mock_arxiv({})[0])
    assert first.limiter is second.limiter is arxiv_client.SHARED_LIMITER
    assert isinstance(arxiv_client.SHARED_LIMITER, RateLimiter)
    assert arxiv_client.SHARED_LIMITER.min_interval == 3.0
