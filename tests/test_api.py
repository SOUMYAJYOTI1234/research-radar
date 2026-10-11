"""POST /api/search: AC1 (completed, sorted, at most max_papers), AC4 (failure is a readable 200),
AC9 (invalid input is a 422 with no arXiv request), and the inbound limit."""

import json
import logging
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.cache import TTLCache
from app.main import ClientAddressFilter, InboundLimiter, create_app
from app.topic import build_query

TODAY = date(2026, 10, 11)
TOPIC = "Diffusion models for time series"
TERMS = ["diffusion", "models", "time", "series"]
TOO_MANY = {"detail": "Too many searches. Please wait a minute."}
NO_MEANINGFUL_WORD = {"detail": "Topic needs at least one meaningful word."}
FAILED_MESSAGE = "arXiv could not be reached just now. Please try again in a minute."
CONTRACT = Path(__file__).resolve().parents[1] / "specs" / "api-contract-spec.md"
CURRENT_YEAR = datetime.now(timezone.utc).year


def q(strategy, terms=TERMS, category=None, from_year=None, narrowed=False):
    return build_query(strategy, terms, category, from_year, TODAY, narrowed=narrowed)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def api(arxiv):
    """api(routes) -> (TestClient, arXiv request log, inbound-limit clock), all private to one test app."""

    def build(routes):
        arxiv_client, log = arxiv(routes)
        clock = Clock()
        app = create_app(
            arxiv_client=arxiv_client,
            today=lambda: TODAY,
            inbound_limiter=InboundLimiter(clock=clock),
            cache=TTLCache(),
        )
        return TestClient(app), log, clock

    return build


def contract_example(heading):
    """The JSON code block that follows `heading` in the API contract."""
    text = CONTRACT.read_text(encoding="utf-8")
    match = re.search(re.escape(heading) + r"\s*```json\n(.*?)\n```", text, re.DOTALL)
    return json.loads(match.group(1))


# --- A valid search (AC1) ------------------------------------------------------------------


def test_valid_search_returns_every_contract_field_with_the_right_types(api):
    client, log, _ = api({q("exact"): "normal.xml"})
    response = client.post("/api/search", json={"topic": TOPIC})
    assert response.status_code == 200
    body = response.json()
    assert len(log) == 1

    assert body["status"] == "completed"
    assert body["message"] == "Found 12 papers in 1 search."
    assert body["cached"] is False
    assert body["query_terms"] == TERMS
    assert 1 <= len(body["papers"]) <= 20
    scores = [paper["score"] for paper in body["papers"]]
    assert scores == sorted(scores, reverse=True)

    paper_types = {
        "arxiv_id": str, "title": str, "authors": list, "published": str, "updated": str,
        "primary_category": str, "abstract": str, "abs_url": str, "pdf_url": str,
        "score": float, "group_id": int, "bibtex": str,
    }
    for paper in body["papers"]:
        assert set(paper) == set(paper_types)
        for field, kind in paper_types.items():
            assert type(paper[field]) is kind, field
        assert all(isinstance(name, str) for name in paper["authors"])
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", paper["published"])
    for group in body["groups"]:
        assert {k: type(v) for k, v in group.items()} == {"group_id": int, "label": str, "size": int}
    trace_types = {
        "round": int, "strategy": str, "query": str, "total_results": int, "returned": int,
        "decision": str, "reason": str, "duration_ms": int,
    }
    for row in body["trace"]:
        assert {k: type(v) for k, v in row.items()} == trace_types


def test_response_keys_match_the_contract_example(api):
    example = contract_example("200 response:")
    request_example = contract_example("Request body:")
    query = q("exact", category=request_example["category"], from_year=request_example["from_year"])
    client, _, _ = api({query: "normal.xml"})
    body = client.post("/api/search", json=request_example).json()

    assert set(body) == set(example)
    assert set(body["papers"][0]) == set(example["papers"][0])
    assert set(body["groups"][0]) == set(example["groups"][0])
    assert set(body["trace"][0]) == set(example["trace"][0])
    assert list(body) == list(example), "same field order as the contract"


def test_max_papers_caps_the_list(api):
    client, _, _ = api({q("exact"): "normal.xml"})
    body = client.post("/api/search", json={"topic": TOPIC, "max_papers": 5}).json()
    assert len(body["papers"]) == 5
    assert body["message"] == "Found 5 papers in 1 search."


# --- Every status through the API ------------------------------------------------------------


@pytest.mark.parametrize(
    ("routes", "status", "message", "papers"),
    [
        ({q("exact"): "normal.xml"}, "completed", "Found 12 papers in 1 search.", 12),
        (
            {q("exact"): "small.xml", q("all_words"): "small.xml", q("any_word"): "small.xml"},
            "partial",
            "Found 3 papers in 3 searches.",
            3,
        ),
        (
            {q(s): "empty.xml" for s in ("exact", "all_words", "any_word")},
            "empty",
            "No arXiv papers matched. Try fewer or more general words.",
            0,
        ),
        ({q("exact"): 500}, "failed", FAILED_MESSAGE, 0),
    ],
    ids=["completed", "partial", "empty", "failed"],
)
def test_each_status_is_a_200_with_its_message(api, routes, status, message, papers):
    client, _, _ = api(routes)
    response = client.post("/api/search", json={"topic": TOPIC})
    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["message"], len(body["papers"])) == (status, message, papers)
    assert body["trace"], "every status carries the trace"
    if papers == 0:
        assert body["groups"] == []


@pytest.mark.parametrize(
    "failure", [httpx.ReadTimeout, 500, "error.xml"], ids=["timeout", "http-500", "error-feed"]
)
def test_arxiv_failure_gives_a_readable_200_without_a_traceback(api, failure):
    client, _, _ = api({q("exact"): failure})
    response = client.post("/api/search", json={"topic": TOPIC})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["message"] == FAILED_MESSAGE
    assert (body["papers"], body["groups"]) == ([], [])
    assert [row["decision"] for row in body["trace"]] == ["failed"]
    for marker in ("Traceback", "ArxivUnavailable", "Exception", "HTTP 500", "File \""):
        assert marker not in response.text


# --- Invalid input (AC9) ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"topic": "ab"}, "topic"),
        ({"topic": "   ab   "}, "topic"),
        ({"topic": "x" * 101}, "topic"),
        ({}, "topic"),
        ({"topic": TOPIC, "category": "cs.XX"}, "category"),
        ({"topic": TOPIC, "category": "cs.lg"}, "category"),
        ({"topic": TOPIC, "from_year": 1999}, "from_year"),
        ({"topic": TOPIC, "from_year": CURRENT_YEAR + 1}, "from_year"),
        ({"topic": TOPIC, "max_papers": 4}, "max_papers"),
        ({"topic": TOPIC, "max_papers": 31}, "max_papers"),
    ],
    ids=[
        "topic-too-short", "topic-short-after-trim", "topic-too-long", "topic-missing", "unknown-category",
        "category-wrong-case", "from-year-1999", "from-year-next-year", "max-papers-4", "max-papers-31",
    ],
)
def test_invalid_input_is_a_422_naming_the_field_and_makes_no_arxiv_request(api, body, field):
    client, log, _ = api({})
    response = client.post("/api/search", json=body)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert any(error["loc"][-1] == field for error in detail)
    assert log == []


def test_topic_with_no_meaningful_word_is_a_422_and_makes_no_arxiv_request(api):
    client, log, _ = api({})
    response = client.post("/api/search", json={"topic": "the of and"})
    assert (response.status_code, response.json()) == (422, NO_MEANINGFUL_WORD)
    assert log == []


def test_malformed_json_is_a_422_and_makes_no_arxiv_request(api):
    client, log, _ = api({})
    response = client.post("/api/search", content=b"{not json", headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert log == []


@pytest.mark.parametrize(
    "extra",
    [{"from_year": 2000}, {"from_year": CURRENT_YEAR}, {"max_papers": 5}, {"max_papers": 30}],
    ids=["from-year-2000", "from-year-this-year", "max-papers-5", "max-papers-30"],
)
def test_boundary_values_are_accepted(api, extra):
    query = q("exact", from_year=extra.get("from_year"))
    client, _, _ = api({query: "normal.xml"})
    assert client.post("/api/search", json={"topic": TOPIC, **extra}).status_code == 200


# --- Cache ---------------------------------------------------------------------------------------


def test_identical_search_is_served_from_cache(api):
    client, log, _ = api({q("exact"): "normal.xml"})
    first = client.post("/api/search", json={"topic": TOPIC}).json()
    second = client.post("/api/search", json={"topic": "  diffusion MODELS, time series "}).json()
    assert (first["cached"], second["cached"]) == (False, True)
    assert len(log) == 1
    assert second["message"] == first["message"]
    assert second["trace"] == first["trace"]
    assert second["papers"] == first["papers"]


def test_different_max_papers_is_not_served_from_cache(api):
    client, log, _ = api({q("exact"): "normal.xml"})
    client.post("/api/search", json={"topic": TOPIC})
    assert client.post("/api/search", json={"topic": TOPIC, "max_papers": 10}).json()["cached"] is False
    assert len(log) == 2


# --- Inbound limit ----------------------------------------------------------------------------------


def test_11th_search_in_a_minute_gets_429_and_cache_hits_count(api):
    client, log, _ = api({q("exact"): "normal.xml"})
    for _ in range(10):
        assert client.post("/api/search", json={"topic": TOPIC}).status_code == 200
    assert len(log) == 1, "searches 2-10 were cache hits, and they still counted"
    response = client.post("/api/search", json={"topic": TOPIC})
    assert (response.status_code, response.json()) == (429, TOO_MANY)
    assert len(log) == 1


def test_422s_count_toward_the_limit(api):
    client, log, _ = api({q("exact"): "normal.xml"})
    for _ in range(10):
        assert client.post("/api/search", json={"topic": "ab"}).status_code == 422
    response = client.post("/api/search", json={"topic": TOPIC})
    assert (response.status_code, response.json()) == (429, TOO_MANY)
    assert log == []


def test_limit_is_checked_before_validation(api):
    client, _, _ = api({q("exact"): "normal.xml"})
    for _ in range(10):
        client.post("/api/search", json={"topic": TOPIC})
    for invalid in ({"topic": "ab"}, {"topic": TOPIC, "category": "cs.XX"}):
        response = client.post("/api/search", json=invalid)
        assert (response.status_code, response.json()) == (429, TOO_MANY)
    response = client.post("/api/search", content=b"{not json", headers={"Content-Type": "application/json"})
    assert response.status_code == 429


def test_window_slides_and_429s_do_not_count(api):
    client, _, clock = api({q("exact"): "normal.xml"})
    for second in range(10):
        clock.now = float(second)
        assert client.post("/api/search", json={"topic": TOPIC}).status_code == 200
    for retry_at in (30.0, 45.0, 59.9):
        clock.now = retry_at
        assert client.post("/api/search", json={"topic": TOPIC}).status_code == 429
    clock.now = 60.0  # the search at t=0 has left the window; the 429 retries never counted
    assert client.post("/api/search", json={"topic": TOPIC}).status_code == 200
    assert client.post("/api/search", json={"topic": TOPIC}).status_code == 429


def test_other_endpoints_do_not_count(api):
    client, _, _ = api({q("exact"): "normal.xml"})
    for _ in range(20):
        assert client.get("/api/health").status_code == 200
    assert client.post("/api/search", json={"topic": TOPIC}).status_code == 200


# --- X-Forwarded-For ------------------------------------------------------------------------------------


def test_each_forwarded_client_has_its_own_limit(api):
    client, _, _ = api({q("exact"): "normal.xml"})
    for _ in range(10):
        client.post("/api/search", json={"topic": TOPIC}, headers={"X-Forwarded-For": "203.0.113.1"})
    other = client.post("/api/search", json={"topic": TOPIC}, headers={"X-Forwarded-For": "203.0.113.2"})
    assert other.status_code == 200
    same = client.post("/api/search", json={"topic": TOPIC}, headers={"X-Forwarded-For": "203.0.113.1"})
    assert same.status_code == 429


def test_only_the_first_forwarded_address_is_used(api):
    client, _, _ = api({q("exact"): "normal.xml"})
    for proxy in range(10):
        headers = {"X-Forwarded-For": f" 203.0.113.1 , 10.0.0.{proxy}"}
        assert client.post("/api/search", json={"topic": TOPIC}, headers=headers).status_code == 200
    headers = {"X-Forwarded-For": "203.0.113.1, 10.0.0.99, 10.0.0.100"}
    assert client.post("/api/search", json={"topic": TOPIC}, headers=headers).status_code == 429


def test_without_the_header_the_socket_address_is_used(api):
    client, _, _ = api({q("exact"): "normal.xml"})
    for _ in range(10):
        assert client.post("/api/search", json={"topic": TOPIC}).status_code == 200
    assert client.post("/api/search", json={"topic": TOPIC}).status_code == 429
    forwarded = client.post("/api/search", json={"topic": TOPIC}, headers={"X-Forwarded-For": "203.0.113.5"})
    assert forwarded.status_code == 200


# --- Logging --------------------------------------------------------------------------------------------


def test_app_logs_at_info_to_standard_output():
    app_logger = logging.getLogger("app")
    assert app_logger.getEffectiveLevel() == logging.INFO
    assert any(getattr(handler, "stream", None) is sys.__stdout__ for handler in app_logger.handlers)


def test_round_lines_are_logged_without_the_client_address(api, caplog):
    client, _, _ = api({q("exact"): "small.xml", q("all_words"): "normal.xml"})
    with caplog.at_level(logging.INFO):
        client.post("/api/search", json={"topic": TOPIC}, headers={"X-Forwarded-For": "203.0.113.77"})
    rounds = [r.getMessage() for r in caplog.records if r.name == "app.search_loop"]
    assert len(rounds) == 2
    assert "strategy=exact" in rounds[0] and "total_results=3" in rounds[0] and "duration_ms=" in rounds[0]
    for record in caplog.records:
        assert "203.0.113.77" not in record.getMessage()
        assert "testclient" not in record.getMessage()


def test_access_log_lines_have_the_client_address_removed():
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("203.0.113.77:51234", "POST", "/api/search", "1.1", 200), None,
    )
    assert ClientAddressFilter().filter(record) is True
    assert record.getMessage() == '- - "POST /api/search HTTP/1.1" 200'
    assert any(isinstance(f, ClientAddressFilter) for f in logging.getLogger("uvicorn.access").filters)
