import asyncio
import re

import httpx
import pytest

from app import arxiv_client
from app.arxiv_client import ArxivClient, ArxivEntry, ArxivUnavailable, parse_feed

QUERY = '(ti:"diffusion models time series" OR abs:"diffusion models time series")'
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def entries_by_id(entries):
    return {entry.arxiv_id: entry for entry in entries}


# --- Parsing -----------------------------------------------------------------


def test_normal_feed_total_and_entry_count(load_fixture):
    total, entries = parse_feed(load_fixture("normal.xml"))
    assert total == 245
    assert len(entries) == 12


def test_normal_feed_first_entry_every_field(load_fixture):
    _, entries = parse_feed(load_fixture("normal.xml"))
    assert entries[0] == ArxivEntry(
        arxiv_id="2301.01234",
        title="Conditional Diffusion Models for Probabilistic Time Series Forecasting",
        abstract=(
            "We study conditional denoising diffusion models for probabilistic forecasting of "
            "multivariate time series. The model learns to reverse a gradual noising process "
            "while conditioning on the observed history, and produces calibrated forecast "
            "distributions on six public benchmarks."
        ),
        authors=["Anika Sharma", "Tomás Herrera", "Lena Vogel"],
        published="2023-01-03",
        updated="2023-02-10",
        primary_category="cs.LG",
        abs_url="https://arxiv.org/abs/2301.01234",
        pdf_url="https://arxiv.org/pdf/2301.01234v2",
    )


def test_normal_feed_rules_hold_for_every_entry(load_fixture):
    _, entries = parse_feed(load_fixture("normal.xml"))
    for entry in entries:
        assert re.fullmatch(r"\d{4}\.\d{4,5}", entry.arxiv_id), "version suffix not removed"
        assert DATE.fullmatch(entry.published)
        assert DATE.fullmatch(entry.updated)
        assert entry.abs_url == f"https://arxiv.org/abs/{entry.arxiv_id}"
        assert entry.pdf_url.startswith("https://arxiv.org/pdf/")
        assert entry.primary_category
        assert entry.authors
        for text in (entry.title, entry.abstract, *entry.authors):
            assert text == text.strip()
            assert "  " not in text and "\n" not in text and "\t" not in text


def test_authors_kept_in_order(load_fixture):
    _, entries = parse_feed(load_fixture("normal.xml"))
    entry = entries_by_id(entries)["2402.05517"]
    assert entry.authors == [
        "Rahul Iyer",
        "Sofia Marquez",
        "Jonas Berg",
        "Mei Lin",
        "Daniel Okafor",
        "Hanna Kowalski",
    ]


def test_primary_category_read_from_arxiv_namespace(load_fixture):
    _, entries = parse_feed(load_fixture("normal.xml"))
    by_id = entries_by_id(entries)
    assert by_id["2210.04021"].primary_category == "eess.SP"
    assert by_id["2105.09977"].primary_category == "stat.ML"
    assert by_id["2603.04418"].primary_category == "physics.comp-ph"


def test_escaped_characters_and_latex_braces_survive(load_fixture):
    _, entries = parse_feed(load_fixture("normal.xml"))
    entry = entries_by_id(entries)["2311.02290"]
    assert entry.title == r"Generating Synthetic Financial Time Series with $\mathcal{O}(T)$ Diffusion Sampling"
    assert "<5%" in entry.abstract
    assert "R&D" in entry.abstract


def test_missing_pdf_link_falls_back_to_built_url(load_fixture):
    _, entries = parse_feed(load_fixture("normal.xml"))
    assert entries_by_id(entries)["2603.04418"].pdf_url == "https://arxiv.org/pdf/2603.04418"


def test_old_style_ids_kept_whole(load_fixture):
    _, entries = parse_feed(load_fixture("old_style_id.xml"))
    assert [entry.arxiv_id for entry in entries] == [
        "hep-th/9901001",
        "math/0601004",
        "cond-mat/0207155",
    ]
    assert entries[0].abs_url == "https://arxiv.org/abs/hep-th/9901001"


def test_duplicate_id_removed_keeping_first(load_fixture):
    total, entries = parse_feed(load_fixture("old_style_id.xml"))
    assert total == 4
    assert len(entries) == 3
    first = entries_by_id(entries)["hep-th/9901001"]
    # The first copy (v2) is kept, not the later v1 copy.
    assert first.pdf_url == "https://arxiv.org/pdf/hep-th/9901001v2"
    assert first.updated == "1999-03-15"


def test_http_pdf_link_changed_to_https(load_fixture):
    _, entries = parse_feed(load_fixture("old_style_id.xml"))
    assert entries_by_id(entries)["math/0601004"].pdf_url == "https://arxiv.org/pdf/math/0601004v1"


GOOD_ENTRY = """
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <updated>2024-01-02T10:00:00Z</updated>
    <published>2024-01-02T10:00:00Z</published>
    <title>A Complete Entry</title>
    <summary>Every required field is present.</summary>
    <author><name>Ada Example</name></author>
    <arxiv:primary_category term="cs.LG" scheme="http://arxiv.org/schemas/atom"/>
  </entry>"""


def feed_with(*entries: str) -> bytes:
    return (
        '<feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/" '
        'xmlns:arxiv="http://arxiv.org/schemas/atom">'
        "<opensearch:totalResults>2</opensearch:totalResults>" + "".join(entries) + "</feed>"
    ).encode()


def test_whitespace_collapsed_in_wrapped_title_and_abstract():
    # Live arXiv sends one-line titles today, but older responses wrapped them.
    wrapped = GOOD_ENTRY.replace(
        "<title>A Complete Entry</title>", "<title>A Complete\n   Entry  with\tGaps</title>"
    ).replace(
        "<summary>Every required field is present.</summary>",
        "<summary>  Every required\nfield is\n\n present.\n</summary>",
    )
    _, entries = parse_feed(feed_with(wrapped))
    assert entries[0].title == "A Complete Entry with Gaps"
    assert entries[0].abstract == "Every required field is present."


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("<id>http://arxiv.org/abs/2401.00001v1</id>", ""),
        ("<id>http://arxiv.org/abs/2401.00001v1</id>", "<id>http://arxiv.org/listing/2401</id>"),
        ("<title>A Complete Entry</title>", ""),
        ("<summary>Every required field is present.</summary>", ""),
        ("<published>2024-01-02T10:00:00Z</published>", ""),
        ("<published>2024-01-02T10:00:00Z</published>", "<published>soon</published>"),
        ("<updated>2024-01-02T10:00:00Z</updated>", ""),
        ('<arxiv:primary_category term="cs.LG" scheme="http://arxiv.org/schemas/atom"/>', ""),
        ('term="cs.LG"', ""),
    ],
    ids=[
        "no-id",
        "id-without-abs",
        "no-title",
        "no-summary",
        "no-published",
        "unreadable-published",
        "no-updated",
        "no-primary-category",
        "primary-category-without-term",
    ],
)
def test_entry_missing_required_field_is_skipped_and_logged(caplog, old, new):
    bad_entry = GOOD_ENTRY.replace(old, new).replace("2401.00001", "2401.00002")
    with caplog.at_level("WARNING", logger="app.arxiv_client"):
        total, entries = parse_feed(feed_with(GOOD_ENTRY, bad_entry))
    assert total == 2, "total_results is still what arXiv reported"
    assert [entry.arxiv_id for entry in entries] == ["2401.00001"]
    skipped = [record for record in caplog.records if record.name == "app.arxiv_client"]
    assert len(skipped) == 1
    assert "skipped" in skipped[0].getMessage().lower()


def test_complete_feed_logs_nothing(load_fixture, caplog):
    with caplog.at_level("DEBUG", logger="app.arxiv_client"):
        parse_feed(load_fixture("normal.xml"))
    assert not [record for record in caplog.records if record.name == "app.arxiv_client"]


def test_broad_feed_total_results(load_fixture):
    total, entries = parse_feed(load_fixture("broad.xml"))
    assert total == 54000
    assert len(entries) == 12


def test_small_feed(load_fixture):
    total, entries = parse_feed(load_fixture("small.xml"))
    assert total == 3
    assert len(entries) == 3


def test_empty_feed_gives_no_entries(load_fixture):
    assert parse_feed(load_fixture("empty.xml")) == (0, [])


def test_malformed_xml_raises(load_fixture):
    with pytest.raises(ArxivUnavailable):
        parse_feed(load_fixture("malformed.xml"))


def test_error_feed_raises_with_arxiv_message(load_fixture):
    with pytest.raises(ArxivUnavailable) as info:
        parse_feed(load_fixture("error.xml"))
    assert "unbalanced parentheses" in info.value.reason


def test_document_that_is_not_an_atom_feed_raises():
    with pytest.raises(ArxivUnavailable):
        parse_feed(b"<html><body>Service temporarily unavailable</body></html>")


# --- HTTP request --------------------------------------------------------------


@pytest.mark.anyio
async def test_fetch_returns_parsed_feed(mock_arxiv):
    client, log = mock_arxiv({QUERY: "normal.xml"})
    total, entries = await ArxivClient(client).fetch(QUERY)
    assert total == 245
    assert len(entries) == 12
    assert len(log) == 1


@pytest.mark.anyio
async def test_fetch_sends_endpoint_params_and_timeout(mock_arxiv, monkeypatch):
    monkeypatch.delenv("CONTACT_EMAIL", raising=False)
    client, log = mock_arxiv({QUERY: "normal.xml"})
    await ArxivClient(client).fetch(QUERY)

    request = log[0]
    assert request.method == "GET"
    assert (request.url.scheme, request.url.host, request.url.path) == (
        "https",
        "export.arxiv.org",
        "/api/query",
    )
    assert dict(request.url.params) == {
        "search_query": QUERY,
        "start": "0",
        "max_results": "50",
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    assert request.extensions["timeout"] == {
        "connect": 10.0,
        "read": 10.0,
        "write": 10.0,
        "pool": 10.0,
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("contact_email", "expected"),
    [
        (None, "ResearchRadar/1.0 (course project)"),
        ("", "ResearchRadar/1.0 (course project)"),
        ("someone@example.org", "ResearchRadar/1.0 (course project; contact: someone@example.org)"),
    ],
    ids=["unset", "blank", "set"],
)
async def test_user_agent_with_and_without_contact_email(mock_arxiv, monkeypatch, contact_email, expected):
    if contact_email is None:
        monkeypatch.delenv("CONTACT_EMAIL", raising=False)
    else:
        monkeypatch.setenv("CONTACT_EMAIL", contact_email)
    client, log = mock_arxiv({QUERY: "normal.xml"})
    await ArxivClient(client).fetch(QUERY)
    assert log[0].headers["User-Agent"] == expected


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("reply", "reason_part"),
    [
        ("error.xml", "error"),
        ("malformed.xml", "XML"),
        (500, "HTTP 500"),
        (httpx.TimeoutException, "timed out"),
        (httpx.ConnectError, "connect"),
    ],
    ids=["error-feed", "malformed-xml", "http-500", "timeout", "connect-error"],
)
async def test_upstream_failures_raise_arxiv_unavailable_without_retry(mock_arxiv, reply, reason_part):
    client, log = mock_arxiv({QUERY: reply})
    with pytest.raises(ArxivUnavailable) as info:
        await ArxivClient(client).fetch(QUERY)
    assert reason_part in info.value.reason
    assert len(log) == 1, "the client must not retry"


@pytest.mark.anyio
async def test_error_feed_with_http_400_raises(mock_arxiv, load_fixture):
    # Real arXiv sends its error feed with status 400.
    client, log = mock_arxiv({QUERY: httpx.Response(400, content=load_fixture("error.xml"))})
    with pytest.raises(ArxivUnavailable):
        await ArxivClient(client).fetch(QUERY)
    assert len(log) == 1


@pytest.mark.anyio
async def test_whole_request_is_capped_by_the_timeout(monkeypatch):
    # httpx times each phase separately; a slow trickle must still stop at the overall limit.
    monkeypatch.setattr(arxiv_client, "TIMEOUT_SECONDS", 0.05)

    async def slow_handler(request):
        await asyncio.sleep(5)
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(slow_handler))
    with pytest.raises(ArxivUnavailable) as info:
        await ArxivClient(client).fetch(QUERY)
    assert "timed out" in info.value.reason
