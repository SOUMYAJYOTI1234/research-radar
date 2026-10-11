"""The static page: what is served, what it contains, and that app.js never parses API text as HTML.

There is no JavaScript test runner (it would be a new dependency), so page behaviour is checked by
hand with the P6 browser checklist; these tests check the files themselves.
"""

import re
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import get_args

import httpx
from fastapi.testclient import TestClient

from app.cache import TTLCache
from app.main import InboundLimiter, app, create_app
from app.models import Category
from app.topic import build_query

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
STYLES = (STATIC / "styles.css").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
FRONTEND_SPEC = (ROOT / "specs" / "frontend-spec.md").read_text(encoding="utf-8")
REPO_URL = "https://github.com/SOUMYAJYOTI1234/research-radar"

client = TestClient(app)


class Page(HTMLParser):
    """Collects every element with its attributes and its own text."""

    def __init__(self, html):
        super().__init__()
        self.elements = []
        self._open = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        element = {"tag": tag, "attrs": dict(attrs), "text": ""}
        self.elements.append(element)
        if tag not in ("input", "meta", "link", "br"):
            self._open.append(element)

    def handle_endtag(self, tag):
        while self._open:
            if self._open.pop()["tag"] == tag:
                break

    def handle_data(self, data):
        for element in self._open:
            element["text"] += data

    def find(self, tag=None, **attrs):
        return [
            e for e in self.elements
            if (tag is None or e["tag"] == tag) and all(e["attrs"].get(k) == v for k, v in attrs.items())
        ]

    def one(self, tag=None, **attrs):
        [element] = self.find(tag, **attrs)
        return element


def text(element):
    return " ".join(element["text"].split())


PAGE = Page(client.get("/").text)


# --- Served files ------------------------------------------------------------------------


def test_index_app_js_and_styles_are_served():
    index = client.get("/")
    assert index.status_code == 200 and index.headers["content-type"].startswith("text/html")
    script = client.get("/static/app.js")
    assert script.status_code == 200 and "javascript" in script.headers["content-type"]
    styles = client.get("/static/styles.css")
    assert styles.status_code == 200 and styles.headers["content-type"].startswith("text/css")


def test_page_loads_only_its_own_script_and_stylesheet():
    assert [e["attrs"].get("src") for e in PAGE.find("script")] == ["/static/app.js"]
    assert [e["attrs"]["href"] for e in PAGE.find("link", rel="stylesheet")] == ["/static/styles.css"]


def test_no_external_resources_or_cdn():
    for name, source in (("index.html", INDEX), ("styles.css", STYLES)):
        assert not re.search(r"https?://", source), name
    assert re.findall(r"https?://[^\s\"'`)]+", APP_JS) == [REPO_URL], "the repository link is the only URL"
    assert "@import" not in STYLES and "url(" not in STYLES


# --- Elements ------------------------------------------------------------------------------


def test_header():
    assert text(PAGE.one("h1")) == "Research Radar"
    assert "Type a research topic. Get a ranked arXiv reading list." in text(PAGE.one("header"))


def test_form_fields_have_labels_and_the_spec_attributes():
    topic = PAGE.one("input", id="topic")
    assert topic["attrs"]["placeholder"] == "e.g. diffusion models for time series"
    assert "required" in topic["attrs"]
    assert PAGE.one("input", id="from-year")["attrs"]["type"] == "number"
    for field in PAGE.find("input") + PAGE.find("select"):
        labels = PAGE.find("label", **{"for": field["attrs"]["id"]})
        assert len(labels) == 1 and text(labels[0]), f"#{field['attrs']['id']} has no label"
    assert "From year" in text(PAGE.one("label", **{"for": "from-year"}))
    assert text(PAGE.one("button", type="submit")) == "Search"


def test_category_dropdown_lists_the_contract_codes_with_arxiv_names():
    options = [(e["attrs"]["value"], text(e)) for e in PAGE.find("option")]
    assert options[0] == ("", "Any category")
    assert [value for value, _ in options[1:]] == list(get_args(Category))
    for value, label in options[1:]:
        assert label.startswith(value + " ")
        assert label in FRONTEND_SPEC, f"{label!r} is not the spec's label"


def test_trace_panel_is_collapsed_with_the_spec_columns():
    panel = PAGE.one("details", id="trace-panel")
    assert "open" not in panel["attrs"]
    assert text(PAGE.one("summary")) == "How Research Radar searched"
    assert [text(e) for e in PAGE.find("th")] == [
        "Round", "Strategy", "Query", "Results found", "Decision", "Reason", "Time",
    ]


def test_footer_acknowledges_arxiv_and_links_the_repository():
    assert "Data from the arXiv API. Thank you to arXiv for use of its open access interoperability." in text(
        PAGE.one("footer")
    )
    assert PAGE.find("a", id="repo-link")
    assert f'const REPO_URL = "{REPO_URL}";' in APP_JS


def test_idle_state_offers_example_topics():
    topics = [e["attrs"]["data-topic"] for e in PAGE.find("button") if "data-topic" in e["attrs"]]
    assert topics == ["graph neural networks", "retrieval augmented generation", "quantum error mitigation"]


def test_results_area_announces_changes():
    assert PAGE.one(id="results")["attrs"].get("aria-live") == "polite"


# --- Spec wording ------------------------------------------------------------------------------

SPEC_TEXTS = [
    "Searching arXiv. This can take up to 40 seconds because arXiv asks apps to wait between requests.",
    " (from a recent identical search)",
    "Only a few papers matched. Try a broader topic.",
    "arXiv stopped responding partway, so these results may be incomplete.",
    "Research Radar could not be reached. If the app was asleep, wait a minute and try again.",
    "Too many searches. Please wait a minute.",
    "Topic must be 3 to 100 characters.",
    "Try again",
    "Show abstract",
    "Copy BibTeX",
    "Copied",
    "Copy failed",
    "Download .bib",
    "Copy Markdown list",
    "et al.",
    "score ",
    "research-radar-",
]


def test_every_user_visible_spec_text_is_on_the_page():
    for wording in SPEC_TEXTS:
        assert wording in FRONTEND_SPEC, f"{wording!r} is not in the spec"
        assert wording in APP_JS or wording in INDEX, f"{wording!r} is missing from the page"


def test_page_never_sends_max_papers_and_only_calls_its_own_api():
    assert "max_papers" not in APP_JS
    assert re.findall(r"fetch\(([^,)]+)", APP_JS) == ["SEARCH_URL"]
    assert 'const SEARCH_URL = "/api/search";' in APP_JS


def test_unreachable_after_60_seconds():
    assert "const TIMEOUT_MS = 60000;" in APP_JS
    assert "AbortController" in APP_JS


# --- Security: API text is never parsed as HTML ----------------------------------------------------


def test_app_js_never_uses_an_html_parsing_sink():
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "createContextualFragment",
                 "DOMParser", "eval(", "new Function", "setTimeout(\"", "srcdoc"):
        assert sink not in APP_JS, sink
    assert not re.search(r"setAttribute\(\s*[\"']on", APP_JS), "no inline event handler attributes"


def test_app_js_writes_text_with_textcontent_and_checks_link_urls():
    assert "textContent" in APP_JS
    assert "function safeUrl" in APP_JS
    # Every href taken from API data goes through safeUrl().
    for match in re.finditer(r"href:\s*([^,}]+)", APP_JS):
        value = match.group(1).strip()
        assert value.startswith("safeUrl(") or value in ("url", "REPO_URL"), value


def test_title_with_script_tag_and_ampersand_reaches_the_page_as_plain_text(arxiv, load_fixture):
    # The API must hand the browser the title exactly as written; app.js then sets it with
    # textContent (checked above), so it displays as text instead of running.
    unsafe = "<script>alert('x')</script> R&D for <b>graphs</b>"
    feed = load_fixture("normal.xml").replace(
        b"<title>Conditional Diffusion Models for Probabilistic Time Series Forecasting</title>",
        b"<title>&lt;script&gt;alert('x')&lt;/script&gt; R&amp;D for &lt;b&gt;graphs&lt;/b&gt;</title>",
    )
    today = date(2026, 10, 11)
    query = build_query("exact", ["diffusion", "models", "time", "series"], None, None, today)
    arxiv_client, _ = arxiv({query: httpx.Response(200, content=feed)})
    page_api = TestClient(
        create_app(arxiv_client=arxiv_client, today=lambda: today, inbound_limiter=InboundLimiter(), cache=TTLCache())
    )
    response = page_api.post("/api/search", json={"topic": "diffusion models for time series"})
    assert response.headers["content-type"] == "application/json"
    titles = [paper["title"] for paper in response.json()["papers"]]
    assert unsafe in titles
    assert "&lt;" not in response.text, "the API does not pre-escape; the page treats the title as text"
    assert "R\\\\&D for" in response.text, "BibTeX escapes & in the title (JSON doubles the backslash)"
