"""Outbound requests to the arXiv API and parsing of its Atom feed."""

import asyncio
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime

import httpx

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


class ArxivClient:
    """Sends one search to arXiv per fetch() call. Never retries."""

    def __init__(self, http: httpx.AsyncClient):
        self._http = http
        self._headers = {"User-Agent": user_agent()}

    async def fetch(self, search_query: str) -> tuple[int, list[ArxivEntry]]:
        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": MAX_RESULTS,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
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
        entry = _parse_entry(raw)
        if entry.arxiv_id not in seen:
            seen.add(entry.arxiv_id)
            entries.append(entry)
    return total_results, entries


def _parse_entry(raw: ET.Element) -> ArxivEntry:
    match = _ID_PATTERN.search(_required_text(raw, "id").strip())
    if match is None:
        raise ArxivUnavailable("arXiv entry has an unrecognised id")
    arxiv_id = match["arxiv_id"]

    primary = raw.find(f"{ARXIV}primary_category")
    if primary is None or not primary.get("term"):
        raise ArxivUnavailable("arXiv entry has no primary category")

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
        raise ArxivUnavailable(f"arXiv entry has no <{tag}>")
    return text


def _date(raw: ET.Element, tag: str) -> str:
    """'2023-01-03T18:59:59Z' -> '2023-01-03'."""
    try:
        return datetime.fromisoformat(_required_text(raw, tag).strip()).date().isoformat()
    except ValueError as exc:
        raise ArxivUnavailable(f"arXiv entry has an unreadable <{tag}> date") from exc


def _collapse(text: str) -> str:
    return " ".join(text.split())
