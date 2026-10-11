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
    assert loops == {"zxqv blorptastic": "empty_after_all_rounds", "graph neural networks": "date_narrowing"}
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
async def test_date_narrowing_check():
    golden = GoldenTopic("graph neural networks", [], "note", "date_narrowing")
    narrowed = await evaluate_topic(golden, fake_search(response(["2401.00001"], trace=trace_of("exact", "exact+date_narrowed"))))
    not_narrowed = await evaluate_topic(golden, fake_search(response(["2401.00001"], trace=trace_of("exact"))))
    assert (loop_check_passed(narrowed), loop_check_passed(not_narrowed)) == (True, False)


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
