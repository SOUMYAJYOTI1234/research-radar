import asyncio
from pathlib import Path

import httpx
import pytest

from app.arxiv_client import ArxivClient, ArxivEntry, RateLimiter

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class FakeClock:
    """A clock for RateLimiter: sleep() moves time forward instead of waiting."""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        await asyncio.sleep(0)  # still give other tasks a turn, as a real sleep would


@pytest.fixture
def anyio_backend():
    # Run async tests on asyncio only, so the anyio plugin does not need trio.
    return "asyncio"


@pytest.fixture
def load_fixture():
    """Return a function that reads a recorded Atom file from tests/fixtures/."""

    def load(name: str) -> bytes:
        return (FIXTURES_DIR / name).read_bytes()

    return load


@pytest.fixture
def mock_arxiv(load_fixture):
    """Return a function that builds a fake arXiv: mock_arxiv(routes) -> (client, request_log).

    `routes` maps a search_query string to a reply:
    - a fixture file name: served with status 200,
    - an int: that HTTP status with an empty body,
    - an httpx.Response: returned as is,
    - an httpx exception class: raised, as a real transport would.
    A search_query missing from `routes` fails the test with a KeyError.
    Every request is appended to request_log before it is answered.
    """

    def build(routes):
        request_log = []

        def handler(request: httpx.Request) -> httpx.Response:
            request_log.append(request)
            reply = routes[request.url.params["search_query"]]
            if isinstance(reply, str):
                return httpx.Response(
                    200,
                    content=load_fixture(reply),
                    headers={"Content-Type": "application/atom+xml; charset=utf-8"},
                )
            if isinstance(reply, int):
                return httpx.Response(reply)
            if isinstance(reply, httpx.Response):
                return reply
            raise reply("simulated failure", request=request)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return client, request_log

    return build


@pytest.fixture
def make_entry():
    """Return a function that builds an ArxivEntry; only the fields a test cares about need passing."""

    def make(
        arxiv_id="2401.00001",
        title="A Study of Graphs",
        abstract="We study graphs.",
        authors=("Ada Lovelace",),
        published="2024-01-02",
        primary_category="cs.LG",
    ):
        return ArxivEntry(
            arxiv_id=arxiv_id,
            title=title,
            abstract=abstract,
            authors=list(authors),
            published=published,
            updated=published,
            primary_category=primary_category,
            abs_url=f"https://arxiv.org/abs/{arxiv_id}",
            pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
        )

    return make


@pytest.fixture
def fake_clock():
    return FakeClock()


@pytest.fixture
def limiter(fake_clock):
    """A real RateLimiter driven by the fake clock, so tests never really sleep."""
    return RateLimiter(clock=fake_clock, sleep=fake_clock.sleep)


@pytest.fixture
def arxiv(mock_arxiv, limiter):
    """arxiv(routes) -> (ArxivClient on the fake transport and fake-clock limiter, request_log)."""

    def build(routes):
        http, request_log = mock_arxiv(routes)
        return ArxivClient(http, limiter), request_log

    return build
