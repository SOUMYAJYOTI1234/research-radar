import itertools
from datetime import date

import httpx
import pytest

from app.arxiv_client import parse_feed
from app.search_loop import describe_outcome, run_loop
from app.topic import build_query

pytestmark = pytest.mark.anyio

TODAY = date(2026, 10, 11)
TERMS = ["diffusion", "models", "time", "series"]
EMPTY_MESSAGE = "No arXiv papers matched. Try fewer or more general words."
FAILED_MESSAGE = "arXiv could not be reached just now. Please try again in a minute."


def q(strategy, terms=TERMS, category=None, from_year=None, narrowed=False):
    return build_query(strategy, terms, category, from_year, TODAY, narrowed=narrowed)


async def search(arxiv, routes, terms=TERMS, category=None, from_year=None, max_papers=20):
    client, log = arxiv(routes)
    result = await run_loop(terms, category, from_year, max_papers, client, TODAY)
    return result, log


def ids(entries):
    return [entry.arxiv_id for entry in entries]


def fixture_ids(load_fixture, name):
    return ids(parse_feed(load_fixture(name))[1])


def column(result, field):
    return [getattr(row, field) for row in result.trace]


# --- Rule 1 and broadening (AC2) --------------------------------------------------


async def test_rule1_accepts_a_round_with_10_to_1000_results(arxiv, load_fixture):
    result, log = await search(arxiv, {q("exact"): "normal.xml"})
    assert len(log) == 1
    assert result.status == "completed"
    assert result.message == "Found 12 papers in 1 search."
    assert ids(result.entries) == fixture_ids(load_fixture, "normal.xml")
    [row] = result.trace
    assert (row.round, row.strategy, row.query) == (1, "exact", q("exact"))
    assert (row.total_results, row.returned, row.decision) == (245, 12, "accept")


async def test_first_round_below_10_broadens_and_trace_shows_both_rounds(arxiv, load_fixture):
    result, log = await search(arxiv, {q("exact"): "small.xml", q("all_words"): "normal.xml"})
    assert [request.url.params["search_query"] for request in log] == [q("exact"), q("all_words")]
    assert column(result, "strategy") == ["exact", "all_words"]
    assert column(result, "decision") == ["broaden", "accept"]
    assert result.trace[0].reason == "Only 3 matches for the exact phrase, so I searched for all the words separately."
    assert ids(result.entries) == fixture_ids(load_fixture, "normal.xml")
    assert result.message == "Found 12 papers in 2 searches."


async def test_all_words_below_10_broadens_to_any_word(arxiv):
    routes = {q("exact"): "small.xml", q("all_words"): "small.xml", q("any_word"): "normal.xml"}
    result, _ = await search(arxiv, routes)
    assert column(result, "decision") == ["broaden", "broaden", "accept"]
    assert result.trace[1].reason == "Only 3 matches with all the words, so I searched for any of the words."
    assert result.status == "completed"


async def test_reason_uses_singular_for_one_match(arxiv, load_fixture):
    one_match = load_fixture("small.xml").replace(
        b"<opensearch:totalResults>3</opensearch:totalResults>",
        b"<opensearch:totalResults>1</opensearch:totalResults>",
    )
    routes = {q("exact"): httpx.Response(200, content=one_match), q("all_words"): "normal.xml"}
    result, _ = await search(arxiv, routes)
    assert result.trace[0].reason == "Only 1 match for the exact phrase, so I searched for all the words separately."


# --- Request limit (AC3) ----------------------------------------------------------


async def test_exact_below_10_then_all_words_broad_then_narrowed_uses_3_requests(arxiv, load_fixture):
    routes = {
        q("exact"): "small.xml",
        q("all_words"): "broad.xml",
        q("all_words", narrowed=True): "normal.xml",
    }
    result, log = await search(arxiv, routes)
    assert len(log) == 3
    assert log[2].url.params["search_query"] == q("all_words", narrowed=True)
    assert column(result, "strategy") == ["exact", "all_words", "all_words+date_narrowed"]
    assert column(result, "decision") == ["broaden", "narrow", "accept"]
    assert "last 5 years" in result.trace[1].reason
    assert ids(result.entries) == fixture_ids(load_fixture, "normal.xml")


@pytest.mark.parametrize("terms", [TERMS, ["transformers"]], ids=["four-terms", "one-term"])
async def test_no_combination_of_round_outcomes_makes_more_than_3_requests(arxiv, terms):
    outcomes = ["normal.xml", "broad.xml", "small.xml", "empty.xml", 500]
    strategies = ["exact", "all_words", "any_word"][: 3 if len(terms) > 1 else 2]
    for base in itertools.product(outcomes, repeat=len(strategies)):
        for narrowed_outcome in outcomes:
            routes = {}
            for strategy, outcome in zip(strategies, base):
                routes[q(strategy, terms)] = outcome
                routes[q(strategy, terms, narrowed=True)] = narrowed_outcome
            result, log = await search(arxiv, routes, terms=terms)
            case = f"{base} narrowed={narrowed_outcome}"
            assert 1 <= len(log) <= 3, case
            assert len(result.trace) == len(log), case
            assert column(result, "round") == list(range(1, len(log) + 1)), case
            assert result.trace[-1].decision in ("accept", "failed"), case
            assert all(row.decision in ("broaden", "narrow") for row in result.trace[:-1]), case
            assert result.status in ("completed", "partial", "empty", "failed"), case


# --- Empty (AC5) ------------------------------------------------------------------


async def test_zero_results_through_all_rounds_is_empty_with_rephrase_message(arxiv):
    terms = ["zxqv", "blorptastic"]
    routes = {q(strategy, terms): "empty.xml" for strategy in ("exact", "all_words", "any_word")}
    result, log = await search(arxiv, routes, terms=terms)
    assert len(log) == 3
    assert result.status == "empty"
    assert result.message == EMPTY_MESSAGE
    assert result.entries == []
    assert column(result, "decision") == ["broaden", "broaden", "accept"]


# --- Rule 2: date narrowing -------------------------------------------------------


async def test_rule2_narrowed_total_of_10_or_more_is_accepted(arxiv, load_fixture):
    routes = {q("exact"): "broad.xml", q("exact", narrowed=True): "normal.xml"}
    result, log = await search(arxiv, routes)
    assert len(log) == 2
    assert column(result, "strategy") == ["exact", "exact+date_narrowed"]
    assert column(result, "decision") == ["narrow", "accept"]
    assert result.trace[0].total_results == 54000
    assert ids(result.entries) == fixture_ids(load_fixture, "normal.xml")
    assert result.status == "completed"


async def test_rule2_narrowed_total_below_10_keeps_the_unnarrowed_round(arxiv, load_fixture):
    routes = {q("exact"): "broad.xml", q("exact", narrowed=True): "small.xml"}
    result, _ = await search(arxiv, routes)
    assert column(result, "decision") == ["narrow", "accept"]
    assert result.trace[1].reason == "Only 3 matches in the last 5 years, so I kept the round-1 results."
    assert ids(result.entries) == fixture_ids(load_fixture, "broad.xml")
    assert result.status == "completed"


async def test_rule2_fallback_names_the_round_that_was_narrowed(arxiv, load_fixture):
    routes = {
        q("exact"): "empty.xml",
        q("all_words"): "broad.xml",
        q("all_words", narrowed=True): "small.xml",
    }
    result, _ = await search(arxiv, routes)
    assert result.trace[2].reason == "Only 3 matches in the last 5 years, so I kept the round-2 results."
    assert ids(result.entries) == fixture_ids(load_fixture, "broad.xml")


# --- Rule 3: broad topic, narrowing not available --------------------------------------


async def test_rule3_with_from_year_and_no_category(arxiv):
    result, log = await search(arxiv, {q("exact", from_year=2020): "broad.xml"}, from_year=2020)
    assert len(log) == 1
    [row] = result.trace
    assert (row.decision, row.reason) == ("accept", "Broad topic; adding a category may help.")
    assert result.status == "completed"


async def test_rule3_with_from_year_and_a_category(arxiv):
    routes = {q("exact", category="cs.LG", from_year=2020): "broad.xml"}
    result, log = await search(arxiv, routes, category="cs.LG", from_year=2020)
    assert len(log) == 1
    [row] = result.trace
    assert (row.decision, row.reason) == (
        "accept",
        "Broad topic; adding more specific words or a from year may help.",
    )


async def test_request_cap_counts_as_narrowing_not_available(arxiv, load_fixture):
    routes = {q("exact"): "small.xml", q("all_words"): "small.xml", q("any_word"): "broad.xml"}
    result, log = await search(arxiv, routes)
    assert len(log) == 3
    assert column(result, "decision") == ["broaden", "broaden", "accept"]
    assert result.trace[2].reason == "Broad topic; adding a category may help."
    assert ids(result.entries) == fixture_ids(load_fixture, "broad.xml")


# --- Rules 4 and 5, and the hard limit ----------------------------------------------


async def test_one_term_topic_skips_any_word_and_accepts_round_2(arxiv, load_fixture):
    terms = ["transformers"]
    routes = {q("exact", terms): "small.xml", q("all_words", terms): "small.xml"}
    result, log = await search(arxiv, routes, terms=terms)
    assert len(log) == 2
    assert column(result, "strategy") == ["exact", "all_words"]
    assert column(result, "decision") == ["broaden", "accept"]
    assert result.trace[1].reason == "Only 3 matches, and no broader search is left, so I kept these results."
    assert result.status == "partial"
    assert result.message == "Found 3 papers in 2 searches."


async def test_hard_limit_keeps_the_best_earlier_round(arxiv, load_fixture):
    routes = {q("exact"): "small.xml", q("all_words"): "empty.xml", q("any_word"): "empty.xml"}
    result, _ = await search(arxiv, routes)
    assert result.trace[2].decision == "accept"
    assert result.trace[2].reason == "Only 0 matches, so I kept the round-1 results."
    assert ids(result.entries) == fixture_ids(load_fixture, "small.xml")
    assert result.status == "partial"
    assert result.message == "Found 3 papers in 3 searches."


async def test_hard_limit_tie_goes_to_the_later_round(arxiv):
    routes = {q("exact"): "small.xml", q("all_words"): "small.xml", q("any_word"): "empty.xml"}
    result, _ = await search(arxiv, routes)
    assert result.trace[2].reason == "Only 0 matches, so I kept the round-2 results."


async def test_hard_limit_keeps_round_3_when_it_has_the_most_papers(arxiv, load_fixture):
    routes = {q("exact"): "empty.xml", q("all_words"): "empty.xml", q("any_word"): "small.xml"}
    result, _ = await search(arxiv, routes)
    assert result.trace[2].reason == "Only 3 matches, and no broader search is left, so I kept these results."
    assert ids(result.entries) == fixture_ids(load_fixture, "small.xml")


# --- Failures -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "failure",
    [500, httpx.ReadTimeout, httpx.ConnectError, "error.xml", "malformed.xml"],
    ids=["http-500", "timeout", "connect-error", "error-feed", "malformed-xml"],
)
async def test_first_request_failing_gives_failed(arxiv, failure):
    result, log = await search(arxiv, {q("exact"): failure})
    assert len(log) == 1
    assert result.status == "failed"
    assert result.message == FAILED_MESSAGE
    assert result.entries == []
    [row] = result.trace
    assert (row.decision, row.total_results, row.returned) == ("failed", 0, 0)
    assert row.reason == "arXiv did not respond, so the search could not finish."


async def test_zero_results_then_failure_gives_failed(arxiv):
    result, _ = await search(arxiv, {q("exact"): "empty.xml", q("all_words"): 500})
    assert result.status == "failed"
    assert result.message == FAILED_MESSAGE
    assert column(result, "decision") == ["broaden", "failed"]


async def test_three_papers_then_failure_gives_partial(arxiv, load_fixture):
    result, _ = await search(arxiv, {q("exact"): "small.xml", q("all_words"): httpx.ConnectError})
    assert result.status == "partial"
    assert result.message == "Found 3 papers in 2 searches."
    assert ids(result.entries) == fixture_ids(load_fixture, "small.xml")
    assert column(result, "decision") == ["broaden", "failed"]
    assert result.trace[1].reason == "arXiv did not respond, so I kept the results from round 1."


async def test_failure_keeps_the_earlier_round_with_the_most_papers(arxiv, load_fixture):
    routes = {q("exact"): "small.xml", q("all_words"): "empty.xml", q("any_word"): 500}
    result, _ = await search(arxiv, routes)
    assert result.trace[2].reason == "arXiv did not respond, so I kept the results from round 1."
    assert ids(result.entries) == fixture_ids(load_fixture, "small.xml")


async def test_failure_after_many_papers_is_still_partial(arxiv, load_fixture):
    result, _ = await search(arxiv, {q("exact"): "broad.xml", q("exact", narrowed=True): 500})
    assert column(result, "decision") == ["narrow", "failed"]
    assert result.trace[1].reason == "arXiv did not respond, so I kept the results from round 1."
    assert ids(result.entries) == fixture_ids(load_fixture, "broad.xml")
    assert result.status == "partial"
    assert result.message == "Found 12 papers in 2 searches."


# --- Status, messages, trace and logging ---------------------------------------------


async def test_status_target_is_min_of_10_and_max_papers(arxiv):
    result, _ = await search(arxiv, {q("exact"): "normal.xml"}, max_papers=5)
    assert (result.status, result.message) == ("completed", "Found 5 papers in 1 search.")


@pytest.mark.parametrize(
    ("papers", "requests", "max_papers", "expected"),
    [
        (1, 1, 20, ("partial", "Found 1 paper in 1 search.")),
        (1, 2, 20, ("partial", "Found 1 paper in 2 searches.")),
        (9, 3, 20, ("partial", "Found 9 papers in 3 searches.")),
        (10, 1, 20, ("completed", "Found 10 papers in 1 search.")),
        (5, 2, 5, ("completed", "Found 5 papers in 2 searches.")),
        (0, 3, 20, ("empty", EMPTY_MESSAGE)),
    ],
)
def test_status_and_message_with_plurals(papers, requests, max_papers, expected):
    assert describe_outcome(papers, requests, max_papers) == expected


def test_kept_round_after_failure_is_partial_even_with_many_papers():
    assert describe_outcome(20, 2, 20, kept_after_failure=True) == ("partial", "Found 20 papers in 2 searches.")


def test_failed_outcome():
    assert describe_outcome(0, 1, 20, failed=True) == ("failed", FAILED_MESSAGE)


async def test_trace_rows_record_every_request(arxiv):
    result, log = await search(arxiv, {q("exact"): "small.xml", q("all_words"): "normal.xml"})
    assert column(result, "round") == [1, 2]
    assert column(result, "query") == [request.url.params["search_query"] for request in log]
    assert column(result, "total_results") == [3, 245]
    assert column(result, "returned") == [3, 12]
    for row in result.trace:
        assert isinstance(row.duration_ms, int) and row.duration_ms >= 0
        assert row.reason.endswith(".")


async def test_one_log_line_per_round(arxiv, caplog):
    with caplog.at_level("INFO", logger="app.search_loop"):
        result, _ = await search(arxiv, {q("exact"): "small.xml", q("all_words"): 500})
    lines = [record.getMessage() for record in caplog.records if record.name == "app.search_loop"]
    assert len(lines) == len(result.trace) == 2
    assert "exact" in lines[0] and "total_results=3" in lines[0] and "duration_ms=" in lines[0]
    assert "all_words" in lines[1] and "failed" in lines[1]
