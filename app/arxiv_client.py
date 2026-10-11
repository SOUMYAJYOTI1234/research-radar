"""Outbound requests to the arXiv API and parsing of its Atom feed."""

import asyncio
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

ENDPOINT = "https://export.arxiv.org/api/query"
TIMEOUT_SECONDS = 10.0
MAX_RESULTS = 50

ATOM = "{http://www.w3.org/2005/Atom}"
OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"
ARXIV = "{http://arxiv.org/schemas/atom}"

# "http://arxiv.org/abs/2301.01234v2" -> "2301.01234"; "…/abs/hep-th/9901001v1" -> "hep-th/9901001".
_ID_PATTERN = re.compile(r"/abs/(?P<arxiv_id>.+?)(?:v\d+)?$")


class ArxivUnavailable(Exception):
    """Raised for every way an arXiv request can fail to give a usable feed."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _IncompleteEntry(Exception):
    """One entry lacks a required field; the entry is skipped, not the feed."""


@dataclass
class ArxivEntry:
    arxiv_id: str
    title: str
    abstract: str
    authors: list[str]
    published: str
    updated: str
    primary_category: str
    abs_url: str
    pdf_url: str


def user_agent() -> str:
    contact = os.environ.get("CONTACT_EMAIL", "").strip()
    if contact:
        return f"ResearchRadar/1.0 (course project; contact: {contact})"
    return "ResearchRadar/1.0 (course project)"


class RateLimiter:
    """Starts requests at least `min_interval` seconds apart, one at a time.

    The lock is held for the whole request, so a second request waits until the
    first has its response (or error), then until `min_interval` has passed since
    the first one started.
    """

    def __init__(
        self,
        min_interval: float = 3.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._last_start: float | None = None

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        async with self._lock:
            if self._last_start is not None:
                wait = self._last_start + self.min_interval - self._clock()
                if wait > 0:
                    await self._sleep(wait)
            self._last_start = self._clock()
            yield


# One limiter for the whole process, shared by the app and the evaluation script.
SHARED_LIMITER = RateLimiter()


class ArxivClient:
    """Sends one search to arXiv per fetch() call, through a rate limiter. Never retries."""

    def __init__(self, http: httpx.AsyncClient, limiter: RateLimiter | None = None):
        self._http = http
        self._headers = {"User-Agent": user_agent()}
        self.limiter = SHARED_LIMITER if limiter is None else limiter

    async def fetch(self, search_query: str) -> tuple[int, list[ArxivEntry]]:
        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": MAX_RESULTS,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        async with self.limiter.slot():
            try:
                # httpx applies its timeout to each phase (connect, read, ...) separately,
                # so the outer deadline caps the whole request at the same limit.
                async with asyncio.timeout(TIMEOUT_SECONDS):
                    response = await self._http.get(
                        ENDPOINT, params=params, headers=self._headers, timeout=TIMEOUT_SECONDS
                    )
            except (httpx.TimeoutException, TimeoutError) as exc:
                raise ArxivUnavailable("arXiv timed out") from exc
            except httpx.TransportError as exc:
                raise ArxivUnavailable("could not connect to arXiv") from exc
        if response.status_code != 200:
            raise ArxivUnavailable(f"arXiv returned HTTP {response.status_code}")
        return parse_feed(response.content)


def parse_feed(xml: bytes | str) -> tuple[int, list[ArxivEntry]]:
    """Return (total_results, entries) from an arXiv Atom feed, without duplicate IDs."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ArxivUnavailable("arXiv sent unparseable XML") from exc
    if root.tag != f"{ATOM}feed":
        raise ArxivUnavailable("arXiv sent a document that is not an Atom feed")

    raw_entries = root.findall(f"{ATOM}entry")
    if len(raw_entries) == 1 and "api/errors" in (raw_entries[0].findtext(f"{ATOM}id") or ""):
        message = _collapse(raw_entries[0].findtext(f"{ATOM}summary") or "")
        raise ArxivUnavailable(f"arXiv returned an error: {message}")

    try:
        total_results = int(root.findtext(f"{OPENSEARCH}totalResults") or "")
    except ValueError as exc:
        raise ArxivUnavailable("arXiv feed has no result count") from exc

    entries: list[ArxivEntry] = []
    seen: set[str] = set()
    for raw in raw_entries:
        try:
            entry = _parse_entry(raw)
        except _IncompleteEntry as exc:
            entry_id = (raw.findtext(f"{ATOM}id") or "").strip() or "unknown id"
            logger.warning("Skipped an arXiv entry (%s): %s", entry_id, exc)
            continue
        if entry.arxiv_id not in seen:
            seen.add(entry.arxiv_id)
            entries.append(entry)
    return total_results, entries


def _parse_entry(raw: ET.Element) -> ArxivEntry:
    match = _ID_PATTERN.search(_required_text(raw, "id").strip())
    if match is None:
        raise _IncompleteEntry("unrecognised <id>")
    arxiv_id = match["arxiv_id"]

    primary = raw.find(f"{ARXIV}primary_category")
    if primary is None or not primary.get("term"):
        raise _IncompleteEntry("no primary category")

    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
    for link in raw.findall(f"{ATOM}link"):
        href = link.get("href")
        if link.get("title") == "pdf" and href:
            if href.startswith("http://"):
                href = "https://" + href.removeprefix("http://")
            pdf_url = href
            break

    return ArxivEntry(
        arxiv_id=arxiv_id,
        title=_collapse(_required_text(raw, "title")),
        abstract=_collapse(_required_text(raw, "summary")),
        authors=[_collapse(author.findtext(f"{ATOM}name") or "") for author in raw.findall(f"{ATOM}author")],
        published=_date(raw, "published"),
        updated=_date(raw, "updated"),
        primary_category=primary.get("term"),
        abs_url=f"https://arxiv.org/abs/{arxiv_id}",
        pdf_url=pdf_url,
    )


def _required_text(raw: ET.Element, tag: str) -> str:
    text = raw.findtext(f"{ATOM}{tag}")
    if text is None:
        raise _IncompleteEntry(f"no <{tag}>")
    return text


def _date(raw: ET.Element, tag: str) -> str:
    """'2023-01-03T18:59:59Z' -> '2023-01-03'."""
    try:
        return datetime.fromisoformat(_required_text(raw, tag).strip()).date().isoformat()
    except ValueError as exc:
        raise _IncompleteEntry(f"unreadable <{tag}> date") from exc


def _collapse(text: str) -> str:
    return " ".join(text.split())
