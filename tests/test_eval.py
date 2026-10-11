"""The evaluation script's own logic, with fixtures and fakes only (the live run is manual)."""

import re
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.models import Group, Paper, SearchResponse, TraceEntry
from app.search_loop import run_search
from app.topic import build_query
from eval.run_eval import (
    GOLDEN_PATH,
    GoldenTopic,
    commit_hash,
    evaluate_topic,
    load_topics,
    loop_check_passed,
    render_results,
)

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 11)
RUN_AT = datetime(2026, 10, 11, 14, 5, tzinfo=timezone.utc)
TERMS = ["diffusion", "models", "time", "series"]
NORMAL_FIRST_ID = "2301.01234"  # in tests/fixtures/normal.xml


def q(strategy, terms=TERMS, narrowed=False):
    return build_query(strategy, terms, None, None, TODAY, narrowed=narrowed)


def paper(arxiv_id):
    return Paper(
        arxiv_id=arxiv_id, title=f"Paper {arxiv_id}", authors=["A Author"], published="2024-01-01",
        updated="2024-01-01", primary_category="cs.LG", abstract="An abstract.",
        abs_url=f"https://arxiv.org/abs/{arxiv_id}", pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
        score=0.5, group_id=0, bibtex="@misc{x}",
    )


def response(ids, status="completed", trace=None):
    return SearchResponse(
        status=status, message="Found papers.", cached=False, query_terms=["x"],
        papers=[paper(i) for i in ids], groups=[Group(group_id=0, label="All results", size=len(ids))] if ids else [],
        trace=trace or [TraceEntry(round=1, strategy="exact", query="(ti:\"x\")", total_results=len(ids),
                                   returned=len(ids), decision="accept", reason="A reason.", duration_ms=1500)],
    )


def fake_search(result):
    async def search(terms):
        return result
    return search


# --- Golden topics --------------------------------------------------------------------------------------


def test_golden_topics_match_the_spec_table():
    spec = (ROOT / "specs" / "evaluation-spec.md").read_text(encoding="utf-8")
    table = dict(re.findall(r"^\| ([a-z][a-z ]+[a-z]) \| (\d{4}\.\d{4,5}) \|$", spec, re.M))
    golden = [t for t in load_topics() if t.loop_check is None]
    assert len(golden) == 10
    assert {t.topic: t.expected_ids for t in golden} == {topic: [arxiv_id] for topic, arxiv_id in table.items()}
    assert all(t.note for t in golden)


def test_two_loop_behaviour_cases_are_flagged():
    loops = {t.topic: t.loop_check for t in load_topics() if t.loop_check is not None}
    assert loops == {"zxqv blorptastic": "empty_after_all_rounds", "graph neural networks": "narrowing"}
    assert all(not t.expected_ids for t in load_topics() if t.loop_check)
    assert GOLDEN_PATH.name == "golden_topics.json"


# --- Hit counting ----------------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_hits_and_misses_from_a_fixture_search(arxiv):
    client, log = arxiv({q("exact"): "normal.xml"})

    async def search(terms):
        return await run_search(terms, None, None, 20, client, TODAY)

    golden = GoldenTopic("diffusion models for time series", [NORMAL_FIRST_ID, "9999.99999"], "note")
    result = await evaluate_topic(golden, search)
    assert result.terms == TERMS
    assert list(result.hits) == [NORMAL_FIRST_ID]
    assert 1 <= result.hits[NORMAL_FIRST_ID] <= 12
    assert result.misses == ["9999.99999"]
    assert len(log) == 1


@pytest.mark.anyio
async def test_only_the_top_20_count_and_ranks_are_1_based():
    ids = [f"2401.{n:05d}" for n in range(1, 26)]
    golden = GoldenTopic("some topic", ["2401.00001", "2401.00020", "2401.00021"], "note")
    result = await evaluate_topic(golden, fake_search(response(ids)))
    assert result.hits == {"2401.00001": 1, "2401.00020": 20}
    assert result.misses == ["2401.00021"]


@pytest.mark.anyio
async def test_failed_search_counts_every_expected_id_as_a_miss():
    golden = GoldenTopic("some topic", ["1312.6114"], "note")
    failed = response([], status="failed", trace=[TraceEntry(
        round=1, strategy="exact", query="q", total_results=0, returned=0, decision="failed",
        reason="arXiv did not respond, so the search could not finish.", duration_ms=10000)])
    result = await evaluate_topic(golden, fake_search(failed))
    assert (result.hits, result.misses) == ({}, ["1312.6114"])


# --- Loop-behaviour checks ----------------------------------------------------------------------------


def trace_of(*strategies, decision="accept"):
    return [TraceEntry(round=i, strategy=s, query="q", total_results=0, returned=0,
                       decision="broaden" if i < len(strategies) else decision, reason="r.", duration_ms=1)
            for i, s in enumerate(strategies, 1)]


@pytest.mark.anyio
async def test_empty_after_all_rounds_check():
    golden = GoldenTopic("zxqv blorptastic", [], "note", "empty_after_all_rounds")
    passed = await evaluate_topic(golden, fake_search(response([], "empty", trace_of("exact", "all_words", "any_word"))))
    early = await evaluate_topic(golden, fake_search(response([], "empty", trace_of("exact", "all_words"))))
    found = await evaluate_topic(golden, fake_search(response(["2401.00001"], "partial", trace_of("exact", "all_words", "any_word"))))
    assert [loop_check_passed(r) for r in (passed, early, found)] == [True, False, False]


@pytest.mark.anyio
async def test_narrowing_check_accepts_title_or_date():
    golden = GoldenTopic("graph neural networks", [], "note", "narrowing")
    date = await evaluate_topic(golden, fake_search(response(["2401.00001"], trace=trace_of("exact", "exact+date_narrowed"))))
    title = await evaluate_topic(golden, fake_search(response(["2401.00001"], trace=trace_of("exact", "exact+title_narrowed"))))
    none = await evaluate_topic(golden, fake_search(response(["2401.00001"], trace=trace_of("exact"))))
    assert [loop_check_passed(r) for r in (date, title, none)] == [True, True, False]


# --- results.md ---------------------------------------------------------------------------------------------


async def sample_results():
    hit = await evaluate_topic(GoldenTopic("alpha topic", ["2401.00002"], "Alpha paper"),
                               fake_search(response(["2401.00001", "2401.00002"])))
    miss_trace = trace_of("exact", "exact+date_narrowed")
    miss_trace[-1].reason = "9876 matches in the last 5 years, so I kept these results."
    miss_trace[0].query = '(ti:"beta | pipe") OR x'
    miss = await evaluate_topic(GoldenTopic("beta topic", ["1312.6114"], "Beta paper"),
                                fake_search(response(["2401.00003"], trace=miss_trace)))
    loop = await evaluate_topic(GoldenTopic("zxqv blorptastic", [], "Loop case", "empty_after_all_rounds"),
                                fake_search(response([], "empty", trace_of("exact", "all_words", "any_word"))))
    return [hit, miss, loop]


@pytest.mark.anyio
async def test_results_header_has_utc_run_time_and_commit():
    text = render_results(await sample_results(), RUN_AT, "abc1234-dirty")
    assert text.startswith("# Research Radar evaluation results\n")
    assert "- Run: 2026-10-11 14:05 UTC" in text
    assert "- Commit: `abc1234-dirty`" in text


@pytest.mark.anyio
async def test_results_table_has_one_row_per_golden_topic():
    text = render_results(await sample_results(), RUN_AT, "abc1234")
    assert "| # | Topic | Status | Rounds | Final strategy | Final decision | Final reason | Expected | Found in top 20 (rank) |" in text
    assert "| 1 | alpha topic | completed | 1 | exact | accept | A reason. | 2401.00002 | 2401.00002 (2) |" in text
    assert (
        "| 2 | beta topic | completed | 2 | exact+date_narrowed | accept "
        "| 9876 matches in the last 5 years, so I kept these results. | 1312.6114 | none |"
    ) in text


@pytest.mark.anyio
async def test_totals_are_worded_for_these_topics_and_list_misses():
    text = render_results(await sample_results(), RUN_AT, "abc1234")
    assert "- Topics with at least one hit: 1 of 2, on these 2 topics." in text
    assert "- Expected IDs found in the top 20: 1 of 2, on these 2 topics." in text
    assert "- Misses: beta topic (1312.6114)" in text


@pytest.mark.anyio
async def test_loop_cases_are_reported_separately_and_not_counted_in_totals():
    text = render_results(await sample_results(), RUN_AT, "abc1234")
    assert "| zxqv blorptastic | empty after all rounds | empty | 3 | exact, all_words, any_word | pass |" in text
    assert "on these 2 topics" in text and "on these 3 topics" not in text


@pytest.mark.anyio
async def test_note_ending_in_a_full_stop_is_not_doubled():
    text = render_results(await sample_results(), RUN_AT, "abc1234")
    assert "Loop case. Terms:" in text
    loop = await evaluate_topic(GoldenTopic("zxqv blorptastic", [], "Should end empty.", "empty_after_all_rounds"),
                                fake_search(response([], "empty", trace_of("exact", "all_words", "any_word"))))
    text = render_results([loop], RUN_AT, "abc1234")
    assert "Should end empty. Terms:" in text and ".." not in text


@pytest.mark.anyio
async def test_each_topic_gets_its_trace_table_with_pipes_escaped():
    text = render_results(await sample_results(), RUN_AT, "abc1234")
    assert "### 2. beta topic" in text
    assert "| Round | Strategy | Query | Results found | Returned | Decision | Reason | Time |" in text
    assert r'`(ti:"beta \| pipe") OR x`' in text


# --- Commit hash --------------------------------------------------------------------------------------------


def fake_git(head="abc1234\n", porcelain="", fail=None):
    def run(args, **kwargs):
        if fail is not None:
            raise fail
        output = head if args[1] == "rev-parse" else porcelain
        return subprocess.CompletedProcess(args, 0, stdout=output, stderr="")
    return run


def test_commit_hash_clean():
    assert commit_hash(fake_git()) == "abc1234"


def test_commit_hash_dirty():
    assert commit_hash(fake_git(porcelain=" M app/main.py\n")) == "abc1234-dirty"


def test_commit_hash_unknown_without_git():
    assert commit_hash(fake_git(fail=FileNotFoundError("git"))) == "unknown"


def test_commit_hash_unknown_without_a_commit():
    error = subprocess.CalledProcessError(128, ["git", "rev-parse"], stderr="fatal: ambiguous argument 'HEAD'")
    assert commit_hash(fake_git(fail=error)) == "unknown"


def test_commit_hash_uses_short_hash_and_porcelain():
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="abc1234\n" if "rev-parse" in args else "", stderr="")

    commit_hash(run)
    assert calls == [["git", "rev-parse", "--short", "HEAD"], ["git", "status", "--porcelain"]]


# --- Controlled experiment ------------------------------------------------------------------------------------

import httpx  # noqa: E402

from app import arxiv_client, search_loop  # noqa: E402
from app.arxiv_client import ArxivClient  # noqa: E402
from eval.run_eval import (  # noqa: E402
    CONFIGS,
    ConfigSummary,
    Recorder,
    RequestRecord,
    classify,
    decide,
    percentile,
    render_experiment,
    run_experiment,
    summarise,
    use_config,
)


def test_the_four_configurations():
    assert {name: (c.narrowing, c.max_results) for name, c in CONFIGS.items()} == {
        "baseline": ("date", 50),
        "a": ("title_then_date", 50),
        "b": ("date", 100),
        "ab": ("title_then_date", 100),
    }


def test_use_config_sets_and_restores_the_production_values():
    with use_config(CONFIGS["ab"]):
        assert (search_loop.NARROWING, arxiv_client.MAX_RESULTS) == ("title_then_date", 100)
    assert (search_loop.NARROWING, arxiv_client.MAX_RESULTS) == ("date", 50)
    with pytest.raises(RuntimeError):
        with use_config(CONFIGS["b"]):
            raise RuntimeError("boom")
    assert (search_loop.NARROWING, arxiv_client.MAX_RESULTS) == ("date", 50)


def test_percentile_is_nearest_rank():
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 90) == 9
    assert percentile([5.0], 90) == 5.0
    assert percentile([3, 1, 2], 90) == 3
    assert percentile([], 90) == 0.0


def record(query, ids, seconds=1.0, size=1000):
    return RequestRecord(query=query, seconds=seconds, size=size, ids=ids)


@pytest.mark.anyio
async def test_classify_expected_paper():
    trace = [
        TraceEntry(round=1, strategy="exact", query="q1", total_results=5000, returned=3, decision="narrow",
                   reason="r.", duration_ms=1),
        TraceEntry(round=2, strategy="exact+date_narrowed", query="q2", total_results=300, returned=3,
                   decision="accept", reason="r.", duration_ms=1),
    ]
    golden = GoldenTopic("some topic", ["2401.00001", "1312.6114", "2401.00009", "9999.99999"], "note")
    result = await evaluate_topic(golden, fake_search(response(["2401.00001", "2401.00002"], trace=trace)))
    requests = [record("q1", ["1312.6114", "2401.00001"]), record("q2", ["2401.00001", "2401.00002", "2401.00009"])]
    assert classify("2401.00001", result, requests) == "rank 1"
    assert classify("2401.00009", result, requests) == "in pool (arXiv #3), ranked out"
    assert classify("1312.6114", result, requests) == "excluded by narrowing"
    assert classify("9999.99999", result, requests) == "not in pool"


def summary(name, hits, *, failures=(), search_max=10.0, request_p90=3.0, loops=True):
    return ConfigSummary(
        name=name, hit_topics=list(hits), golden_count=10, requests_mean=2.0, search_median=6.0,
        search_max=search_max, request_p90=request_p90, request_max=request_p90, kb_mean=200.0, kb_max=300.0,
        failed_topics=list(failures), loops_passed=loops,
    )


def test_decision_picks_the_most_hits_among_qualifying_configs():
    choice, why = decide({
        "baseline": summary("baseline", ["cot"]),
        "a": summary("a", ["cot", "gan", "rag"]),
        "b": summary("b", ["cot", "ddpm", "qaoa", "react"]),
        "ab": summary("ab", ["cot", "gan", "rag", "ddpm", "qaoa"]),
    })
    assert choice == "ab"
    assert why["a"] == [] and why["b"] == [] and why["ab"] == []


def test_decision_prefers_a_single_change_on_a_tie_and_a_over_b():
    base = summary("baseline", ["cot"])
    choice, _ = decide({"baseline": base, "a": summary("a", ["cot", "x", "y"]),
                        "b": summary("b", ["cot", "p", "q"]), "ab": summary("ab", ["cot", "x", "y"])})
    assert choice == "a"
    choice, _ = decide({"baseline": base, "a": summary("a", ["cot"]),
                        "b": summary("b", ["cot", "p", "q"]), "ab": summary("ab", ["cot", "p", "q"])})
    assert choice == "b"


def test_decision_lists_every_failed_criterion():
    choice, why = decide({
        "baseline": summary("baseline", ["cot", "adam"]),
        "a": summary("a", ["cot", "gan"]),
        "b": summary("b", ["cot", "adam", "x", "y"], failures=["rag"]),
        "ab": summary("ab", ["cot", "adam", "x", "y"], search_max=41.0, request_p90=7.5, loops=False),
    })
    assert choice is None
    assert why["a"] == ["1. hits 2 < baseline 2 + 2", "2. lost baseline hits: adam"]
    assert why["b"] == ["3. failed searches: rag"]
    assert why["ab"] == ["4. max search time 41.0 s > 40 s", "5. request p90 7.5 s > 7 s", "6. a loop case failed"]


@pytest.mark.anyio
async def test_run_experiment_interleaves_configs_and_records_requests(load_fixture, limiter):
    terms = ["generative", "adversarial", "networks"]
    exact = build_query("exact", terms, None, None, TODAY)
    title = build_query("title", terms, None, None, TODAY)
    dated = build_query("exact", terms, None, None, TODAY, narrowed=True)
    routes = {exact: "broad.xml", title: "normal.xml", dated: "small.xml"}
    sent = []

    def handler(request):
        sent.append((request.url.params["search_query"], request.url.params["max_results"]))
        return httpx.Response(200, content=load_fixture(routes[request.url.params["search_query"]]))

    recorder = Recorder()
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), event_hooks=recorder.hooks)
    client = ArxivClient(http, limiter)
    topics = [GoldenTopic("generative adversarial networks", [NORMAL_FIRST_ID, "1406.2661"], "GAN")]
    configs = [CONFIGS[name] for name in ("baseline", "a", "b", "ab")]
    records = await run_experiment(topics, configs, client, recorder, TODAY, pause=0)

    assert [r.config for r in records] == ["baseline", "a", "b", "ab"]
    assert sent == [
        (exact, "50"), (dated, "50"),
        (exact, "50"), (title, "50"),
        (exact, "100"), (dated, "100"),
        (exact, "100"), (title, "100"),
    ]
    by_config = {r.config: r for r in records}
    assert [len(r.requests) for r in records] == [2, 2, 2, 2]
    assert all(req.size > 0 and req.seconds >= 0 for r in records for req in r.requests)
    assert by_config["a"].result.response.trace[-1].strategy == "exact+title_narrowed"
    assert NORMAL_FIRST_ID in by_config["a"].result.hits
    # Baseline: exact (broad) -> date (small, below 10) -> keeps round 1; normal.xml was never returned.
    assert classify(NORMAL_FIRST_ID, by_config["baseline"].result, by_config["baseline"].requests) == "not in pool"
    assert (search_loop.NARROWING, arxiv_client.MAX_RESULTS) == ("date", 50), "production values restored"


@pytest.mark.anyio
async def test_experiment_report_has_every_section(load_fixture, limiter):
    terms = ["generative", "adversarial", "networks"]
    exact = build_query("exact", terms, None, None, TODAY)
    routes = {exact: "normal.xml"}

    def handler(request):
        return httpx.Response(200, content=load_fixture(routes[request.url.params["search_query"]]))

    recorder = Recorder()
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), event_hooks=recorder.hooks)
    topics = [
        GoldenTopic("generative adversarial networks", [NORMAL_FIRST_ID], "GAN"),
        GoldenTopic("generative adversarial networks", [], "Loop case", "narrowing"),
    ]
    configs = [CONFIGS[name] for name in ("baseline", "a", "b", "ab")]
    records = await run_experiment(topics, configs, ArxivClient(http, limiter), recorder, TODAY, pause=0)
    summaries = summarise(records, configs)
    text = render_experiment(records, configs, summaries, RUN_AT, "abc1234", "golden")

    assert text.startswith("# Experiment: title narrowing and pool size (golden topics)\n")
    assert "- Run: 2026-10-11 14:05 UTC" in text and "- Commit: `abc1234`" in text
    assert "| # | Topic | Expected | baseline | a | b | ab |" in text
    assert f"| 1 | generative adversarial networks | {NORMAL_FIRST_ID} |" in text
    assert "## Search path per configuration" in text
    assert "## Loop-behaviour cases" in text
    assert "| Golden hits |" in text and "| Request time p90 / max (s) |" in text
    assert "## Decision rule applied" in text
    assert "No configuration qualifies" in text  # every config hits the same paper here
    assert "Architect sign-off:" in text


@pytest.mark.anyio
async def test_run_order_alternates_so_cached_requests_are_shared_fairly(load_fixture, limiter):
    def handler(request):
        return httpx.Response(200, content=load_fixture("normal.xml"))

    recorder = Recorder()
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), event_hooks=recorder.hooks)
    topics = [GoldenTopic(f"topic number {n}", [], "note") for n in range(4)]
    configs = [CONFIGS[name] for name in ("baseline", "a", "b", "ab")]
    records = await run_experiment(topics, configs, ArxivClient(http, limiter), recorder, TODAY, pause=0)
    orders = [[r.config for r in records[i:i + 4]] for i in range(0, 16, 4)]
    assert orders == [
        ["baseline", "a", "b", "ab"],
        ["ab", "b", "a", "baseline"],
        ["baseline", "a", "b", "ab"],
        ["ab", "b", "a", "baseline"],
    ]
