"""The bounded arXiv search loop and its trace."""

import logging
import time
from dataclasses import asdict, dataclass
from datetime import date

from app.arxiv_client import ArxivClient, ArxivEntry, ArxivUnavailable
from app.bibtex import make_entries
from app.models import Group, Paper, SearchResponse, TraceEntry
from app.ranking import group, rank
from app.topic import build_query, strategies_for

logger = logging.getLogger(__name__)

MAX_REQUESTS = 3
MIN_ACCEPTED = 10
MAX_ACCEPTED = 1000

EMPTY_MESSAGE = "No arXiv papers matched. Try fewer or more general words."
FAILED_MESSAGE = "arXiv could not be reached just now. Please try again in a minute."


@dataclass
class TraceRow:
    round: int
    strategy: str
    query: str
    total_results: int
    returned: int
    decision: str
    reason: str
    duration_ms: int


@dataclass
class LoopResult:
    entries: list[ArxivEntry]
    trace: list[TraceRow]
    status: str
    message: str


@dataclass
class _Round:
    row: TraceRow
    entries: list[ArxivEntry]


def _count(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _matches(n: int) -> str:
    return _count(n, "match", "matches")


def describe_outcome(
    papers: int,
    requests: int,
    max_papers: int,
    *,
    failed: bool = False,
    kept_after_failure: bool = False,
) -> tuple[str, str]:
    """Return (status, message) for `papers` papers found with `requests` arXiv requests."""
    if failed:
        return "failed", FAILED_MESSAGE
    if papers == 0:
        return "empty", EMPTY_MESSAGE
    target = min(10, max_papers)
    status = "partial" if kept_after_failure or papers < target else "completed"
    return status, f"Found {_count(papers, 'paper', 'papers')} in {_count(requests, 'search', 'searches')}."


def _best(rounds: list[_Round]) -> _Round | None:
    """The round with the most returned papers; ties go to the later round."""
    return max(rounds, key=lambda r: (r.row.returned, r.row.round), default=None)


async def run_loop(
    terms: list[str],
    category: str | None,
    from_year: int | None,
    max_papers: int,
    client: ArxivClient,
    today: date,
) -> LoopResult:
    """Search arXiv from narrow to broad, with at most MAX_REQUESTS requests."""
    strategies = strategies_for(terms)
    trace: list[TraceRow] = []
    succeeded: list[_Round] = []

    async def request(strategy: str, narrowed: bool = False) -> _Round | None:
        """Run one round and add its trace row. Returns None if arXiv failed."""
        name = f"{strategy}+date_narrowed" if narrowed else strategy
        query = build_query(strategy, terms, category, from_year, today, narrowed=narrowed)
        number = len(trace) + 1
        started = time.perf_counter()
        try:
            total, entries = await client.fetch(query)
        except ArxivUnavailable as exc:
            duration_ms = round((time.perf_counter() - started) * 1000)
            logger.info("arXiv round %d: strategy=%s failed (%s) duration_ms=%d", number, name, exc.reason, duration_ms)
            trace.append(TraceRow(number, name, query, 0, 0, "failed", "", duration_ms))
            return None
        duration_ms = round((time.perf_counter() - started) * 1000)
        logger.info("arXiv round %d: strategy=%s total_results=%d duration_ms=%d", number, name, total, duration_ms)
        row = TraceRow(number, name, query, total, len(entries), "", "", duration_ms)
        trace.append(row)
        succeeded.append(_Round(row, entries))
        return succeeded[-1]

    def finish(entries: list[ArxivEntry], *, failed: bool = False, kept_after_failure: bool = False) -> LoopResult:
        papers = min(len(entries), max_papers)
        status, message = describe_outcome(
            papers, len(trace), max_papers, failed=failed, kept_after_failure=kept_after_failure
        )
        return LoopResult(entries, trace, status, message)

    def after_failure() -> LoopResult:
        failed_row = trace[-1]
        earlier = _best([r for r in succeeded if r.row.returned > 0])
        if earlier is None:
            failed_row.reason = "arXiv did not respond, so the search could not finish."
            return finish([], failed=True)
        failed_row.reason = f"arXiv did not respond, so I kept the results from round {earlier.row.round}."
        return finish(earlier.entries, kept_after_failure=True)

    def no_broader_round_reason(total: int) -> str:
        if total == 0:
            return "No matches, and no broader search is left."
        return f"Only {_matches(total)}, and no broader search is left, so I kept these results."

    index = 0
    while True:
        strategy = strategies[index]
        current = await request(strategy)
        if current is None:
            return after_failure()
        row = current.row
        total = row.total_results

        # Rule 1: a good size.
        if MIN_ACCEPTED <= total <= MAX_ACCEPTED:
            row.decision = "accept"
            row.reason = f"{_matches(total)}, a good number for a reading list."
            return finish(current.entries)

        if total > MAX_ACCEPTED:
            # Rule 2: narrow to the last 5 years, once, if allowed.
            if from_year is None and len(trace) < MAX_REQUESTS:
                row.decision = "narrow"
                row.reason = f"{total} matches are too many, so I searched only the last 5 years."
                narrowed = await request(strategy, narrowed=True)
                if narrowed is None:
                    return after_failure()
                narrowed.row.decision = "accept"
                narrowed_total = narrowed.row.total_results
                if narrowed_total >= MIN_ACCEPTED:
                    narrowed.row.reason = f"{_matches(narrowed_total)} in the last 5 years, so I kept these results."
                    return finish(narrowed.entries)
                narrowed.row.reason = (
                    f"Only {_matches(narrowed_total)} in the last 5 years, so I kept the round-{row.round} results."
                )
                return finish(current.entries)
            # Rule 3: broad, and narrowing is not available.
            row.decision = "accept"
            if category:
                row.reason = "Broad topic; adding more specific words or a from year may help."
            else:
                row.reason = "Broad topic; adding a category may help."
            return finish(current.entries)

        # Fewer than 10 results.
        if len(trace) >= MAX_REQUESTS:
            # Hard limit: keep the best round so far.
            best = _best(succeeded)
            row.decision = "accept"
            if best is current:
                row.reason = no_broader_round_reason(total)
            else:
                row.reason = f"Only {_matches(total)}, so I kept the round-{best.row.round} results."
            return finish(best.entries)
        if index + 1 < len(strategies):
            # Rule 4: broaden.
            row.decision = "broaden"
            if strategy == "exact":
                row.reason = f"Only {_matches(total)} for the exact phrase, so I searched for all the words separately."
            else:
                row.reason = f"Only {_matches(total)} with all the words, so I searched for any of the words."
            index += 1
            continue
        # Rule 5: nothing broader is left.
        row.decision = "accept"
        row.reason = no_broader_round_reason(total)
        return finish(current.entries)


async def run_search(
    topic_terms: list[str],
    category: str | None,
    from_year: int | None,
    max_papers: int,
    client: ArxivClient,
    today: date,
) -> SearchResponse:
    """The full uncached search: the loop, then ranking, grouping and BibTeX."""
    loop = await run_loop(topic_terms, category, from_year, max_papers, client, today)
    ranking = rank(loop.entries, topic_terms, max_papers, today)
    group_ids, groups = group(ranking)
    bibtex = make_entries(ranking.entries)
    papers = [
        Paper(
            arxiv_id=entry.arxiv_id,
            title=entry.title,
            authors=entry.authors,
            published=entry.published,
            updated=entry.updated,
            primary_category=entry.primary_category,
            abstract=entry.abstract,
            abs_url=entry.abs_url,
            pdf_url=entry.pdf_url,
            score=score,
            group_id=group_id,
            bibtex=entry_bibtex,
        )
        for entry, score, group_id, entry_bibtex in zip(ranking.entries, ranking.scores, group_ids, bibtex)
    ]
    # The loop's status and message already count min(papers found, max_papers), which is
    # exactly the number of papers kept here.
    return SearchResponse(
        status=loop.status,
        message=loop.message,
        cached=False,
        query_terms=list(topic_terms),
        papers=papers,
        groups=[Group(group_id=g.group_id, label=g.label, size=g.size) for g in groups],
        trace=[TraceEntry(**asdict(row)) for row in loop.trace],
    )
