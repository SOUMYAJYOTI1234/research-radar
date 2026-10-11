"""Live evaluation of Research Radar on the golden topics. Calls arXiv and takes several minutes.

Run from the project root:  python eval/run_eval.py
It calls the uncached run_search() (no filters, max_papers=20) through the shared 3-second limiter,
and writes eval/results.md.
"""

import asyncio
import json
import subprocess
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # so `python eval/run_eval.py` can import the app

import httpx  # noqa: E402

from app.arxiv_client import ArxivClient  # noqa: E402
from app.models import SearchResponse  # noqa: E402
from app.search_loop import run_search  # noqa: E402
from app.topic import normalise, strategies_for  # noqa: E402

GOLDEN_PATH = Path(__file__).with_name("golden_topics.json")
RESULTS_PATH = Path(__file__).with_name("results.md")
MAX_PAPERS = 20
TOP_N = 20
LOOP_CHECKS = {
    "empty_after_all_rounds": "empty after all rounds",
    "date_narrowing": "date narrowing used",
}

Search = Callable[[list[str]], Awaitable[SearchResponse]]


@dataclass
class GoldenTopic:
    topic: str
    expected_ids: list[str]
    note: str = ""
    loop_check: str | None = None  # set for the loop-behaviour cases, which are not counted as hits


@dataclass
class TopicResult:
    golden: GoldenTopic
    terms: list[str]
    response: SearchResponse
    hits: dict[str, int]  # expected arXiv ID -> rank (1-based) in the top 20
    misses: list[str]


def load_topics(path: Path = GOLDEN_PATH) -> list[GoldenTopic]:
    return [GoldenTopic(**item) for item in json.loads(path.read_text(encoding="utf-8"))]


async def evaluate_topic(golden: GoldenTopic, search: Search) -> TopicResult:
    terms = normalise(golden.topic)
    response = await search(terms)
    top = [paper.arxiv_id for paper in response.papers[:TOP_N]]
    hits = {arxiv_id: top.index(arxiv_id) + 1 for arxiv_id in golden.expected_ids if arxiv_id in top}
    misses = [arxiv_id for arxiv_id in golden.expected_ids if arxiv_id not in hits]
    return TopicResult(golden, terms, response, hits, misses)


def loop_check_passed(result: TopicResult) -> bool | None:
    """None for a golden topic; otherwise whether the loop behaved as the case expects."""
    check = result.golden.loop_check
    if check is None:
        return None
    trace = result.response.trace
    if check == "empty_after_all_rounds":
        return result.response.status == "empty" and len(trace) == len(strategies_for(result.terms))
    if check == "date_narrowing":
        return any(row.strategy.endswith("+date_narrowed") for row in trace)
    raise ValueError(f"unknown loop_check {check!r}")


def commit_hash(run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> str:
    """`git rev-parse --short HEAD`, plus "-dirty" for uncommitted changes, or "unknown" without git or a commit."""
    try:
        head = run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
        status = run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    short = head.stdout.strip()
    if not short:
        return "unknown"
    return f"{short}-dirty" if status.stdout.strip() else short


def _cell(value: object) -> str:
    """Text for a Markdown table cell."""
    return str(value).replace("|", "\\|").replace("\n", " ")


def _row(*cells: object) -> str:
    return "| " + " | ".join(_cell(c) for c in cells) + " |"


def render_results(results: list[TopicResult], run_at: datetime, commit: str) -> str:
    golden = [r for r in results if r.golden.loop_check is None]
    loops = [r for r in results if r.golden.loop_check is not None]
    n = len(golden)
    with_hit = sum(1 for r in golden if r.hits)
    found = sum(len(r.hits) for r in golden)
    expected = sum(len(r.golden.expected_ids) for r in golden)
    misses = [f"{r.golden.topic} ({', '.join(r.misses)})" for r in golden if r.misses]

    lines = [
        "# Research Radar evaluation results",
        "",
        f"- Run: {run_at.astimezone(timezone.utc):%Y-%m-%d %H:%M} UTC",
        f"- Commit: `{commit}`",
        f"- Search: uncached `run_search()`, no category or from-year filter, `max_papers={MAX_PAPERS}`, "
        "shared 3-second arXiv limiter.",
        "- arXiv adds papers every day, so results depend on the run date.",
        "",
        "## Golden topics",
        "",
        "| # | Topic | Status | Rounds | Final strategy | Final decision | Final reason | Expected | Found in top 20 (rank) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for number, r in enumerate(golden, 1):
        last = r.response.trace[-1] if r.response.trace else None
        found_text = ", ".join(f"{i} ({rank})" for i, rank in r.hits.items()) or "none"
        lines.append(_row(
            number, r.golden.topic, r.response.status, len(r.response.trace),
            last.strategy if last else "-", last.decision if last else "-", last.reason if last else "-",
            ", ".join(r.golden.expected_ids), found_text,
        ))

    lines += [
        "",
        "## Totals",
        "",
        f"- Topics with at least one hit: {with_hit} of {n}, on these {n} topics.",
        f"- Expected IDs found in the top 20: {found} of {expected}, on these {n} topics.",
        f"- Misses: {'; '.join(misses) if misses else 'none'}",
        "",
        "These topics name well-known papers on purpose, so a miss is informative. A hit rate on hand-picked "
        "topics is not a measure of quality for all users.",
    ]

    if loops:
        lines += [
            "",
            "## Loop-behaviour cases",
            "",
            "| Topic | Expectation | Status | Rounds | Strategies | Result |",
            "|---|---|---|---|---|---|",
        ]
        for r in loops:
            lines.append(_row(
                r.golden.topic, LOOP_CHECKS[r.golden.loop_check], r.response.status, len(r.response.trace),
                ", ".join(row.strategy for row in r.response.trace),
                "pass" if loop_check_passed(r) else "FAIL",
            ))

    lines += ["", "## Trace per topic"]
    for number, r in enumerate(golden + loops, 1):
        lines += [
            "",
            f"### {number}. {r.golden.topic}",
            "",
            f"{r.golden.note.rstrip('.')}. Terms: {', '.join(r.terms)}. Status: {r.response.status}. "
            f"Message: {r.response.message}",
            "",
            "| Round | Strategy | Query | Results found | Returned | Decision | Reason | Time |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for row in r.response.trace:
            lines.append(_row(
                row.round, row.strategy, f"`{row.query}`", row.total_results, row.returned,
                row.decision, row.reason, f"{row.duration_ms / 1000:.1f} s",
            ))
        if r.golden.expected_ids:
            top = ", ".join(f"{p.arxiv_id} ({p.published[:4]})" for p in r.response.papers[:5]) or "none"
            lines += ["", f"Top 5 kept: {top}"]
    return "\n".join(lines) + "\n"


async def run(topics: list[GoldenTopic]) -> list[TopicResult]:
    today = datetime.now(timezone.utc).date()
    results = []
    async with httpx.AsyncClient() as http:
        client = ArxivClient(http)  # the shared, process-wide 3-second limiter

        async def search(terms: list[str]) -> SearchResponse:
            return await run_search(terms, None, None, MAX_PAPERS, client, today)

        for number, golden in enumerate(topics, 1):
            print(f"[{number}/{len(topics)}] {golden.topic}", flush=True)
            result = await evaluate_topic(golden, search)
            print(
                f"    {result.response.status}, {len(result.response.trace)} round(s), "
                f"hits: {', '.join(result.hits) or 'none'}",
                flush=True,
            )
            results.append(result)
    return results


def main() -> None:
    commit = commit_hash()
    run_at = datetime.now(timezone.utc)
    results = asyncio.run(run(load_topics()))
    RESULTS_PATH.write_text(render_results(results, run_at, commit), encoding="utf-8")
    print(f"Wrote {RESULTS_PATH}")


if __name__ == "__main__":
    main()
