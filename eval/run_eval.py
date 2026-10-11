"""Live evaluation of Research Radar on the golden topics. Calls arXiv and takes several minutes.

Run from the project root:
    python eval/run_eval.py
        The production configuration; writes eval/results.md.
    python eval/run_eval.py --configs baseline,a,b,ab
        A controlled experiment (evaluation spec, "Controlled experiments"); writes
        eval/experiments/<run date>-<name>/<topics>.md. Production settings are restored afterwards.
It calls the uncached run_search() (no filters, max_papers=20) through the shared 3-second limiter.
"""

import argparse
import asyncio
import json
import math
import statistics
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # so `python eval/run_eval.py` can import the app

import httpx  # noqa: E402

from app import arxiv_client, search_loop  # noqa: E402
from app.arxiv_client import ArxivClient, ArxivUnavailable, parse_feed  # noqa: E402
from app.models import SearchResponse  # noqa: E402
from app.search_loop import run_search  # noqa: E402
from app.topic import normalise, strategies_for  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
GOLDEN_PATH = EVAL_DIR / "golden_topics.json"
HELDOUT_PATH = EVAL_DIR / "heldout_topics.json"
RESULTS_PATH = EVAL_DIR / "results.md"
EXPERIMENTS_DIR = EVAL_DIR / "experiments"
MAX_PAPERS = 20
TOP_N = 20
LOOP_CHECKS = {
    "empty_after_all_rounds": "empty after all rounds",
    "narrowing": "narrowing used (title or date)",
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
    if check == "narrowing":
        return any(row.strategy.endswith(("+date_narrowed", "+title_narrowed")) for row in trace)
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


# --- Controlled experiment (evaluation spec, "Controlled experiments") --------------------------------------


@dataclass(frozen=True)
class Config:
    name: str
    narrowing: str  # search_loop.NARROWING
    max_results: int  # arxiv_client.MAX_RESULTS

    def describe(self) -> str:
        narrowing = "title, then date" if self.narrowing == "title_then_date" else "date"
        return f"`{self.name}`: {narrowing} narrowing, max_results={self.max_results}"


CONFIGS = {
    "baseline": Config("baseline", "date", 50),
    "a": Config("a", "title_then_date", 50),
    "b": Config("b", "date", 100),
    "ab": Config("ab", "title_then_date", 100),
}
PREFERENCE = {"a": 0, "b": 1, "ab": 2}  # on equal hits: a single change before ab, and a before b
MIN_EXTRA_HITS = 2
MAX_SEARCH_SECONDS = 40.0
MAX_REQUEST_P90 = 7.0


@contextmanager
def use_config(config: Config) -> Iterator[None]:
    """Switch the two evaluation-only settings for one search, then restore the production values."""
    saved = (search_loop.NARROWING, arxiv_client.MAX_RESULTS)
    search_loop.NARROWING, arxiv_client.MAX_RESULTS = config.narrowing, config.max_results
    try:
        yield
    finally:
        search_loop.NARROWING, arxiv_client.MAX_RESULTS = saved


@dataclass
class RequestRecord:
    query: str
    seconds: float  # sending to full response, without the limiter wait
    size: int  # bytes received
    ids: list[str]  # arXiv IDs in the response, in arXiv's order


class Recorder:
    """httpx event hooks that time every arXiv request and keep the IDs it returned."""

    def __init__(self) -> None:
        self.requests: list[RequestRecord] = []
        self._started: dict[int, float] = {}

    async def on_request(self, request: httpx.Request) -> None:
        self._started[id(request)] = time.perf_counter()

    async def on_response(self, response: httpx.Response) -> None:
        await response.aread()
        started = self._started.pop(id(response.request), None)
        seconds = time.perf_counter() - started if started is not None else 0.0
        try:
            ids = [entry.arxiv_id for entry in parse_feed(response.content)[1]]
        except ArxivUnavailable:
            ids = []
        query = response.request.url.params.get("search_query", "")
        self.requests.append(RequestRecord(query, seconds, len(response.content), ids))

    @property
    def hooks(self) -> dict:
        return {"request": [self.on_request], "response": [self.on_response]}

    def take(self) -> list[RequestRecord]:
        taken, self.requests = self.requests, []
        return taken


@dataclass
class RunRecord:
    config: str
    result: TopicResult
    search_seconds: float
    requests: list[RequestRecord] = field(default_factory=list)


async def run_experiment(
    topics: list[GoldenTopic],
    configs: list[Config],
    client: ArxivClient,
    recorder: Recorder,
    today: date,
    pause: float = 3.0,
) -> list[RunRecord]:
    """Every configuration back to back for each topic, with a pause so no search waits on the previous one.

    arXiv caches identical request URLs, and configurations with the same pool size send the same first request.
    The order alternates (forward, then reversed) from topic to topic, so each one meets the cold cache equally often.
    """

    async def search(terms: list[str]) -> SearchResponse:
        return await run_search(terms, None, None, MAX_PAPERS, client, today)

    records = []
    for number, golden in enumerate(topics, 1):
        order = configs if number % 2 == 1 else list(reversed(configs))
        for config in order:
            await asyncio.sleep(pause)
            recorder.take()
            with use_config(config):
                started = time.perf_counter()
                result = await evaluate_topic(golden, search)
                seconds = time.perf_counter() - started
            records.append(RunRecord(config.name, result, seconds, recorder.take()))
            if pause:
                print(f"[{number}/{len(topics)}] {golden.topic} / {config.name}: {result.response.status}, "
                      f"{len(result.response.trace)} request(s), {seconds:.1f} s, "
                      f"hits: {', '.join(result.hits) or 'none'}", flush=True)
    return records


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(1, math.ceil(pct / 100 * len(ordered))) - 1]


def classify(expected_id: str, result: TopicResult, requests: list[RequestRecord]) -> str:
    """Where an expected paper ended up in one search."""
    if expected_id in result.hits:
        return f"rank {result.hits[expected_id]}"
    by_query = {r.query: r for r in requests}
    kept = {paper.arxiv_id for paper in result.response.papers}
    accepted = None
    if kept:
        for row in reversed(result.response.trace):
            ids = by_query[row.query].ids if row.query in by_query else []
            if kept <= set(ids):
                accepted = ids
                break
    if accepted is not None and expected_id in accepted:
        return f"in pool (arXiv #{accepted.index(expected_id) + 1}), ranked out"
    if any(expected_id in r.ids for r in requests):
        return "excluded by narrowing"
    return "not in pool"


@dataclass
class ConfigSummary:
    name: str
    hit_topics: list[str]
    golden_count: int
    requests_mean: float
    search_median: float
    search_max: float
    request_p90: float
    request_max: float
    kb_mean: float
    kb_max: float
    failed_topics: list[str]
    loops_passed: bool


def _failed(record: RunRecord) -> bool:
    response = record.result.response
    return response.status == "failed" or any(row.decision == "failed" for row in response.trace)


def summarise(records: list[RunRecord], configs: list[Config]) -> dict[str, ConfigSummary]:
    summaries = {}
    for config in configs:
        mine = [r for r in records if r.config == config.name]
        golden = [r for r in mine if r.result.golden.loop_check is None]
        loops = [r for r in mine if r.result.golden.loop_check is not None]
        times = [r.search_seconds for r in mine]
        request_times = [req.seconds for r in mine for req in r.requests]
        kb = [sum(req.size for req in r.requests) / 1024 for r in mine]
        summaries[config.name] = ConfigSummary(
            name=config.name,
            hit_topics=[r.result.golden.topic for r in golden if r.result.hits],
            golden_count=len(golden),
            requests_mean=statistics.fmean(len(r.result.response.trace) for r in mine) if mine else 0.0,
            search_median=statistics.median(times) if times else 0.0,
            search_max=max(times, default=0.0),
            request_p90=percentile(request_times, 90),
            request_max=max(request_times, default=0.0),
            kb_mean=statistics.fmean(kb) if kb else 0.0,
            kb_max=max(kb, default=0.0),
            failed_topics=[r.result.golden.topic for r in mine if _failed(r)],
            loops_passed=all(loop_check_passed(r.result) for r in loops),
        )
    return summaries


def decide(summaries: dict[str, ConfigSummary]) -> tuple[str | None, dict[str, list[str]]]:
    """The pre-registered decision rule. Returns (chosen configuration or None, failed criteria per configuration)."""
    baseline = summaries["baseline"]
    why: dict[str, list[str]] = {}
    for name, s in summaries.items():
        if name == "baseline":
            continue
        failed = []
        if len(s.hit_topics) < len(baseline.hit_topics) + MIN_EXTRA_HITS:
            failed.append(f"1. hits {len(s.hit_topics)} < baseline {len(baseline.hit_topics)} + {MIN_EXTRA_HITS}")
        lost = [topic for topic in baseline.hit_topics if topic not in s.hit_topics]
        if lost:
            failed.append(f"2. lost baseline hits: {', '.join(lost)}")
        if s.failed_topics:
            failed.append(f"3. failed searches: {', '.join(s.failed_topics)}")
        if s.search_max > MAX_SEARCH_SECONDS:
            failed.append(f"4. max search time {s.search_max:.1f} s > {MAX_SEARCH_SECONDS:.0f} s")
        if s.request_p90 > MAX_REQUEST_P90:
            failed.append(f"5. request p90 {s.request_p90:.1f} s > {MAX_REQUEST_P90:.0f} s")
        if not s.loops_passed:
            failed.append("6. a loop case failed")
        why[name] = failed
    qualifying = [name for name, failed in why.items() if not failed]
    if not qualifying:
        return None, why
    choice = min(qualifying, key=lambda name: (-len(summaries[name].hit_topics), PREFERENCE.get(name, 99)))
    return choice, why


def _path(record: RunRecord) -> str:
    rows = record.result.response.trace
    steps = " > ".join(f"{row.strategy} {row.total_results}" + (" FAILED" if row.decision == "failed" else "")
                       for row in rows)
    return f"{steps} ({len(rows)} req, {record.search_seconds:.1f} s)"


def render_experiment(
    records: list[RunRecord],
    configs: list[Config],
    summaries: dict[str, ConfigSummary],
    run_at: datetime,
    commit: str,
    topic_set: str,
) -> str:
    names = [c.name for c in configs]
    # Keyed by the topic entry itself, so two entries with the same wording never collide.
    cell = {(id(r.result.golden), r.config): r for r in records}
    entries = list({id(r.result.golden): r.result.golden for r in records}.values())
    golden_topics = [g for g in entries if g.loop_check is None]
    loop_topics = [g for g in entries if g.loop_check is not None]
    header = "| " + " | ".join(names) + " |"
    divider = "|---" * len(names) + "|"

    lines = [
        f"# Experiment: title narrowing and pool size ({topic_set} topics)",
        "",
        f"- Run: {run_at.astimezone(timezone.utc):%Y-%m-%d %H:%M} UTC",
        f"- Commit: `{commit}`",
        "- Configurations: " + "; ".join(c.describe() for c in configs) + ".",
        "- Order: interleaved per topic (every configuration back to back), alternating forward and reversed "
        "from topic to topic because arXiv caches identical request URLs; 3 s pause between searches; "
        "uncached `run_search()`, no filters, `max_papers=20`.",
        "- Decision rule: specs/evaluation-spec.md, \"Experiment: title narrowing and pool size\" (fixed before the run).",
        "",
        "## Expected paper per configuration",
        "",
        "| # | Topic | Expected " + header,
        "|---|---|---" + divider,
    ]
    for number, golden in enumerate(golden_topics, 1):
        for arxiv_id in golden.expected_ids:
            runs = [cell[(id(golden), n)] for n in names]
            lines.append(_row(number, golden.topic, arxiv_id, *[classify(arxiv_id, r.result, r.requests) for r in runs]))

    lines += ["", "## Search path per configuration", "", "| # | Topic " + header, "|---|---" + divider]
    for number, golden in enumerate(golden_topics + loop_topics, 1):
        lines.append(_row(number, golden.topic, *[_path(cell[(id(golden), n)]) for n in names]))

    if loop_topics:
        lines += ["", "## Loop-behaviour cases", "", "| Topic | Expectation " + header, "|---|---" + divider]
        for golden in loop_topics:
            results = ["pass" if loop_check_passed(cell[(id(golden), n)].result) else "FAIL" for n in names]
            lines.append(_row(golden.topic, LOOP_CHECKS[golden.loop_check], *results))

    base = summaries[names[0]]

    def changed(name: str, gained: bool) -> str:
        mine, theirs = set(summaries[name].hit_topics), set(base.hit_topics)
        diff = mine - theirs if gained else theirs - mine
        return ", ".join(sorted(diff)) or "-"

    lines += ["", "## Totals per configuration", "", "| Measure " + header, "|---" + divider]
    lines.append(_row("Golden hits", *[f"{len(summaries[n].hit_topics)} of {summaries[n].golden_count}" for n in names]))
    lines.append(_row("Gained vs baseline", *[changed(n, True) for n in names]))
    lines.append(_row("Lost vs baseline", *[changed(n, False) for n in names]))
    lines.append(_row("Mean requests per search", *[f"{summaries[n].requests_mean:.2f}" for n in names]))
    lines.append(_row("Search time median / max (s)",
                      *[f"{summaries[n].search_median:.1f} / {summaries[n].search_max:.1f}" for n in names]))
    lines.append(_row("Request time p90 / max (s)",
                      *[f"{summaries[n].request_p90:.1f} / {summaries[n].request_max:.1f}" for n in names]))
    lines.append(_row("KB from arXiv per search mean / max",
                      *[f"{summaries[n].kb_mean:.0f} / {summaries[n].kb_max:.0f}" for n in names]))
    lines.append(_row("Failed searches", *[", ".join(summaries[n].failed_topics) or "none" for n in names]))
    lines.append(_row("Loop cases", *["pass" if summaries[n].loops_passed else "FAIL" for n in names]))
    lines += ["", "Hits are counted on these golden topics only; they are not a measure of quality for all topics."]

    choice, why = decide(summaries)
    candidates = [n for n in names if n != "baseline"]
    lines += ["", "## Decision rule applied", "", "| Configuration | Qualifies | Failed criteria |", "|---|---|---|"]
    for name in candidates:
        lines.append(_row(name, "yes" if not why[name] else "no", "; ".join(why[name]) or "-"))
    lines.append("")
    if choice is None:
        lines.append("**No configuration qualifies: adopt nothing.** The failed criteria above say why.")
    else:
        lines.append(f"**Recommended configuration: `{choice}`** ({CONFIGS[choice].describe()}). "
                     "Nothing changes in production until the architect signs off.")
    lines += ["", "Architect sign-off: ____________________  Date: __________"]
    return "\n".join(lines) + "\n"


async def experiment(topics: list[GoldenTopic], configs: list[Config]) -> list[RunRecord]:
    today = datetime.now(timezone.utc).date()
    recorder = Recorder()
    async with httpx.AsyncClient(event_hooks=recorder.hooks) as http:
        return await run_experiment(topics, configs, ArxivClient(http), recorder, today)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--topics", choices=["golden", "heldout"], default="golden")
    parser.add_argument("--configs", help="comma-separated, from: " + ", ".join(CONFIGS))
    parser.add_argument("--name", default="title-narrowing-pool", help="experiment folder name")
    args = parser.parse_args(argv)

    path = GOLDEN_PATH if args.topics == "golden" else HELDOUT_PATH
    if not path.exists():
        parser.error(f"{path} does not exist")
    topics = load_topics(path)
    commit = commit_hash()
    run_at = datetime.now(timezone.utc)

    if not args.configs:
        results = asyncio.run(run(topics))
        RESULTS_PATH.write_text(render_results(results, run_at, commit), encoding="utf-8")
        print(f"Wrote {RESULTS_PATH}")
        return

    names = [name.strip() for name in args.configs.split(",") if name.strip()]
    unknown = [name for name in names if name not in CONFIGS]
    if unknown or "baseline" not in names:
        parser.error(f"--configs needs baseline and known names; unknown: {unknown}")
    configs = [CONFIGS[name] for name in names]
    records = asyncio.run(experiment(topics, configs))
    summaries = summarise(records, configs)
    out_dir = EXPERIMENTS_DIR / f"{run_at:%Y-%m-%d}-{args.name}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{args.topics}.md"
    out.write_text(render_experiment(records, configs, summaries, run_at, commit, args.topics), encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
