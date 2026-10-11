// Research Radar page: plain JavaScript, no framework and no build step.
// Every piece of text from the API is inserted with textContent (through el() below), never parsed as HTML.
"use strict";

(() => {
  const REPO_URL = "https://github.com/SOUMYAJYOTI1234/research-radar";
  const SEARCH_URL = "/api/search";
  const TIMEOUT_MS = 60000;
  const FEEDBACK_MS = 2000;
  const CATEGORIES = [
    "cs.AI", "cs.LG", "cs.CL", "cs.CV", "cs.RO", "cs.IR",
    "stat.ML", "quant-ph", "physics.comp-ph", "math.OC", "eess.SP", "q-bio.QM",
  ];
  const STATUSES = ["completed", "partial", "empty", "failed"];

  const TEXT = {
    loading: "Searching arXiv. This can take up to 40 seconds because arXiv asks apps to wait between requests.",
    cachedSuffix: " (from a recent identical search)",
    fewPapers: "Only a few papers matched. Try a broader topic.",
    incomplete: "arXiv stopped responding partway, so these results may be incomplete.",
    unreachable: "Research Radar could not be reached. If the app was asleep, wait a minute and try again.",
    tooMany: "Too many searches. Please wait a minute.",
    topicLength: "Topic must be 3 to 100 characters.",
    category: "Choose a category from the list.",
    checkSearch: "Please check this search and try again.",
    showAbstract: "Show abstract",
    hideAbstract: "Hide abstract",
    copied: "Copied",
    copyFailed: "Copy failed",
  };
  const fromYearMessage = (maxYear) => `From year must be a whole year from 2000 to ${maxYear}.`;

  const ui = {
    form: document.getElementById("search-form"),
    topic: document.getElementById("topic"),
    category: document.getElementById("category"),
    fromYear: document.getElementById("from-year"),
    searchButton: document.getElementById("search-button"),
    status: document.getElementById("status"),
    notice: document.getElementById("notice"),
    examples: document.getElementById("examples"),
    tryAgainRow: document.getElementById("try-again-row"),
    tryAgain: document.getElementById("try-again"),
    chips: document.getElementById("chips"),
    exportBar: document.getElementById("export-bar"),
    downloadBib: document.getElementById("download-bib"),
    copyMarkdown: document.getElementById("copy-markdown"),
    exportFallback: document.getElementById("export-fallback"),
    papers: document.getElementById("papers"),
    tracePanel: document.getElementById("trace-panel"),
    traceBody: document.getElementById("trace-body"),
    repoLink: document.getElementById("repo-link"),
  };

  const fieldErrors = {
    topic: [ui.topic, document.getElementById("topic-error")],
    category: [ui.category, document.getElementById("category-error")],
    from_year: [ui.fromYear, document.getElementById("from-year-error")],
  };

  const state = {
    loading: false,
    requestId: 0, // only the newest request may change the page
    lastSearch: null, // the exact inputs "Try again" re-sends
    topic: "",
    papers: [],
    groups: [],
    groupId: null, // null shows all groups
  };
  let abstractCount = 0;

  // --- Small helpers -------------------------------------------------------------------------

  /** Create an element. Text always goes in through textContent, so it is never parsed as HTML. */
  function el(tag, { className, text, attrs } = {}, children = []) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    if (attrs) {
      for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
    }
    for (const child of children) node.append(child);
    return node;
  }

  /** Only http(s) links from the API become real links; anything else becomes "#". */
  function safeUrl(value) {
    try {
      const url = new URL(String(value), window.location.href);
      return url.protocol === "https:" || url.protocol === "http:" ? url.href : "#";
    } catch {
      return "#";
    }
  }

  const currentUtcYear = () => new Date().getUTCFullYear();

  /** Show `text` on a button for 2 seconds, then put its label back. */
  function flash(button, text) {
    const label = button.dataset.label || button.textContent;
    button.dataset.label = label;
    clearTimeout(Number(button.dataset.timer));
    button.textContent = text;
    button.dataset.timer = String(setTimeout(() => { button.textContent = label; }, FEEDBACK_MS));
  }

  /** Copy text; if the browser refuses, show it in a read-only, pre-selected box instead. */
  async function copyText(text, button, fallback) {
    let copied = false;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        copied = true;
      }
    } catch {
      copied = false;
    }
    if (copied) {
      fallback.replaceChildren();
      fallback.hidden = true;
    } else {
      const box = el("textarea", { attrs: { readonly: "", rows: "6", "aria-label": "Text to copy by hand" } });
      box.value = text;
      fallback.replaceChildren(box);
      fallback.hidden = false;
      box.focus();
      box.select();
    }
    flash(button, copied ? TEXT.copied : TEXT.copyFailed);
  }

  function downloadText(filename, text) {
    const url = URL.createObjectURL(new Blob([text], { type: "application/x-bibtex;charset=utf-8" }));
    const link = el("a", { attrs: { href: url, download: filename } });
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  /** Lowercase; each run of non-letters/digits becomes "-"; no "-" at either end; at most 50 characters. */
  function topicSlug(topic) {
    const slug = topic
      .toLowerCase()
      .replace(/[^\p{L}\p{N}]+/gu, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 50)
      .replace(/-+$/, "");
    return slug || "search";
  }

  function authorLine(authors) {
    return authors.length > 3 ? `${authors.slice(0, 3).join(", ")} et al.` : authors.join(", ");
  }

  function markdownList(papers) {
    return papers
      .map((paper, index) => {
        const first = paper.authors[0] || "Unknown author";
        const etAl = paper.authors.length >= 2 ? " et al." : "";
        return `${index + 1}. [${paper.title}](${paper.abs_url}) - ${first}${etAl}, ${paper.published.slice(0, 4)}`;
      })
      .join("\n");
  }

  // --- Form checks (the same rules as the API) ---------------------------------------------------

  function readForm() {
    const maxYear = currentUtcYear();
    const errors = {};
    const topic = ui.topic.value.trim();
    if (topic.length < 3 || topic.length > 100) errors.topic = TEXT.topicLength;

    const category = ui.category.value;
    if (category !== "" && !CATEGORIES.includes(category)) errors.category = TEXT.category;

    let fromYear = null;
    const yearText = ui.fromYear.value.trim();
    if (ui.fromYear.validity.badInput) {
      errors.from_year = fromYearMessage(maxYear);
    } else if (yearText !== "") {
      const year = Number(yearText);
      if (!Number.isInteger(year) || year < 2000 || year > maxYear) errors.from_year = fromYearMessage(maxYear);
      else fromYear = year;
    }
    return { errors, body: { topic, category: category || null, from_year: fromYear } };
  }

  function showFieldErrors(errors) {
    for (const [field, [input, message]] of Object.entries(fieldErrors)) {
      const text = errors[field];
      message.textContent = text || "";
      message.hidden = !text;
      if (text) input.setAttribute("aria-invalid", "true");
      else input.removeAttribute("aria-invalid");
    }
  }

  /** A 422 from the API: a string detail is shown as-is next to the topic; a list is mapped by field. */
  function errorsFromDetail(detail) {
    if (typeof detail === "string") return { topic: detail };
    const errors = {};
    for (const item of Array.isArray(detail) ? detail : []) {
      const loc = item && Array.isArray(item.loc) ? item.loc : [];
      if (loc.includes("topic")) errors.topic = TEXT.topicLength;
      else if (loc.includes("category")) errors.category = TEXT.category;
      else if (loc.includes("from_year")) errors.from_year = fromYearMessage(currentUtcYear());
    }
    if (Object.keys(errors).length === 0) errors.topic = TEXT.checkSearch;
    return errors;
  }

  // --- Page states ---------------------------------------------------------------------------------

  function setLoading(loading) {
    state.loading = loading;
    ui.searchButton.disabled = loading;
    ui.tryAgain.disabled = loading;
    ui.form.setAttribute("aria-busy", String(loading));
  }

  function showStatus(kind, text) {
    ui.status.className = `status status--${kind}`;
    ui.status.textContent = text;
    ui.status.hidden = false;
  }

  /** Remove everything a previous search put on the page. */
  function clearResults() {
    ui.status.hidden = true;
    ui.status.textContent = "";
    ui.notice.hidden = true;
    ui.notice.textContent = "";
    ui.examples.hidden = true;
    ui.tryAgainRow.hidden = true;
    ui.chips.hidden = true;
    ui.chips.replaceChildren();
    ui.exportBar.hidden = true;
    ui.exportFallback.hidden = true;
    ui.exportFallback.replaceChildren();
    ui.papers.replaceChildren();
    ui.tracePanel.hidden = true;
    ui.tracePanel.open = false;
    ui.traceBody.replaceChildren();
    state.papers = [];
    state.groups = [];
    state.groupId = null;
  }

  function visiblePapers() {
    return state.groupId === null ? state.papers : state.papers.filter((p) => p.group_id === state.groupId);
  }

  function renderChips() {
    if (state.groups.length <= 1) {
      ui.chips.hidden = true;
      return;
    }
    const chip = (text, groupId) => {
      const button = el("button", {
        className: "chip",
        text,
        attrs: { type: "button", "aria-pressed": String(state.groupId === groupId) },
      });
      button.addEventListener("click", () => {
        state.groupId = groupId;
        renderChips();
        renderPapers();
      });
      return button;
    };
    ui.chips.replaceChildren(
      chip("All", null),
      ...state.groups.map((group) => chip(`${group.label} (${group.size})`, group.group_id)),
    );
    ui.chips.hidden = false;
  }

  function paperCard(paper) {
    const abstractId = `abstract-${++abstractCount}`;
    const abstract = el("p", { className: "paper-abstract is-clamped", text: paper.abstract, attrs: { id: abstractId } });
    const toggle = el("button", {
      className: "link-button paper-toggle",
      text: TEXT.showAbstract,
      attrs: { type: "button", "aria-expanded": "false", "aria-controls": abstractId },
    });
    toggle.addEventListener("click", () => {
      const open = toggle.getAttribute("aria-expanded") !== "true";
      toggle.setAttribute("aria-expanded", String(open));
      abstract.classList.toggle("is-clamped", !open);
      toggle.textContent = open ? TEXT.hideAbstract : TEXT.showAbstract;
    });

    const fallback = el("div", { className: "copy-fallback" });
    fallback.hidden = true;
    const copyBibtex = el("button", { className: "button", text: "Copy BibTeX", attrs: { type: "button" } });
    copyBibtex.addEventListener("click", () => copyText(paper.bibtex, copyBibtex, fallback));

    const score = Number(paper.score).toFixed(2);
    return el("li", { className: "paper" }, [
      el("h3", { className: "paper-title" }, [
        el("a", {
          text: paper.title,
          attrs: { href: safeUrl(paper.abs_url), target: "_blank", rel: "noopener noreferrer" },
        }),
      ]),
      el("p", { className: "paper-authors", text: authorLine(paper.authors) }),
      el("p", { className: "paper-meta", text: `${paper.published} · ${paper.primary_category} · score ${score}` }),
      abstract,
      toggle,
      el("div", { className: "paper-actions" }, [
        el("a", {
          className: "button",
          text: "PDF",
          attrs: { href: safeUrl(paper.pdf_url), target: "_blank", rel: "noopener noreferrer" },
        }),
        copyBibtex,
      ]),
      fallback,
    ]);
  }

  function renderPapers() {
    ui.papers.replaceChildren(...visiblePapers().map(paperCard));
    ui.exportFallback.hidden = true;
    ui.exportFallback.replaceChildren();
  }

  function renderTrace(trace) {
    ui.traceBody.replaceChildren(
      ...trace.map((row) =>
        el("tr", {}, [
          el("td", { text: String(row.round) }),
          el("td", { text: row.strategy }),
          el("td", {}, [el("code", { text: row.query })]),
          el("td", { text: String(row.total_results) }),
          el("td", { text: row.decision }),
          el("td", { text: row.reason }),
          el("td", { text: `${(Number(row.duration_ms) / 1000).toFixed(1)} s` }),
        ]),
      ),
    );
    ui.tracePanel.open = false;
    ui.tracePanel.hidden = trace.length === 0;
  }

  /** Show one 200 response from the API. */
  function renderResponse(data, topic) {
    clearResults();
    state.topic = topic;
    state.papers = data.papers;
    state.groups = data.groups;
    const message = data.cached ? data.message + TEXT.cachedSuffix : data.message;

    if (data.status === "failed") {
      showStatus("failed", data.message);
      ui.tryAgainRow.hidden = false;
    } else if (data.status === "empty") {
      showStatus("empty", message);
      ui.examples.hidden = false;
    } else {
      showStatus(data.status, message);
      if (data.status === "partial") {
        ui.notice.textContent = data.papers.length < 10 ? TEXT.fewPapers : TEXT.incomplete;
        ui.notice.hidden = false;
      }
      renderChips();
      renderPapers();
      ui.exportBar.hidden = false;
    }
    renderTrace(data.trace);
  }

  function isSearchResponse(data) {
    return (
      data !== null &&
      typeof data === "object" &&
      STATUSES.includes(data.status) &&
      typeof data.message === "string" &&
      typeof data.cached === "boolean" &&
      Array.isArray(data.papers) &&
      Array.isArray(data.groups) &&
      Array.isArray(data.trace)
    );
  }

  /** Turn an HTTP response into one of: result, invalid (422), tooMany (429) or unreachable. */
  async function readOutcome(response) {
    if (response.status === 429) return { kind: "tooMany" };
    if (response.status !== 200 && response.status !== 422) return { kind: "unreachable" };
    let data;
    try {
      data = await response.json();
    } catch {
      return { kind: "unreachable" };
    }
    if (response.status === 422) return { kind: "invalid", detail: data && data.detail };
    return isSearchResponse(data) ? { kind: "result", data } : { kind: "unreachable" };
  }

  function showOutcome(outcome, search) {
    if (outcome.kind === "result") {
      renderResponse(outcome.data, search.topic);
    } else if (outcome.kind === "invalid") {
      showFieldErrors(errorsFromDetail(outcome.detail));
    } else if (outcome.kind === "tooMany") {
      showStatus("limit", TEXT.tooMany);
    } else {
      showStatus("unreachable", TEXT.unreachable);
      ui.tryAgainRow.hidden = false;
    }
  }

  // --- Searching -----------------------------------------------------------------------------------

  async function runSearch(search) {
    if (state.loading) return; // one search at a time
    const requestId = ++state.requestId;
    state.lastSearch = search;
    clearResults();
    showFieldErrors({});
    setLoading(true);
    showStatus("loading", TEXT.loading);

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    let outcome;
    try {
      const response = await fetch(SEARCH_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(search),
        signal: controller.signal,
      });
      outcome = await readOutcome(response);
    } catch {
      outcome = { kind: "unreachable" }; // network error or the 60-second timeout
    } finally {
      clearTimeout(timer);
    }

    if (requestId !== state.requestId) return; // a newer search owns the page now
    setLoading(false);
    clearResults();
    showOutcome(outcome, search);
  }

  function submitSearch() {
    if (state.loading) return;
    const { errors, body } = readForm();
    showFieldErrors(errors);
    const firstInvalid = ["topic", "category", "from_year"].find((field) => errors[field]);
    if (firstInvalid) {
      fieldErrors[firstInvalid][0].focus();
      return;
    }
    runSearch(body);
  }

  // --- Wiring ----------------------------------------------------------------------------------------

  ui.repoLink.href = REPO_URL;
  ui.fromYear.max = String(currentUtcYear());

  ui.form.addEventListener("submit", (event) => {
    event.preventDefault();
    submitSearch();
  });

  for (const button of ui.examples.querySelectorAll("button[data-topic]")) {
    button.addEventListener("click", () => {
      ui.topic.value = button.dataset.topic;
      if (!state.loading) submitSearch(); // while loading, an example only fills the box
    });
  }

  ui.tryAgain.addEventListener("click", () => {
    if (!state.loading && state.lastSearch) runSearch(state.lastSearch);
  });

  ui.downloadBib.addEventListener("click", () => {
    const entries = visiblePapers().map((paper) => paper.bibtex);
    downloadText(`research-radar-${topicSlug(state.topic)}.bib`, `${entries.join("\n\n")}\n`);
  });

  ui.copyMarkdown.addEventListener("click", () => {
    copyText(markdownList(visiblePapers()), ui.copyMarkdown, ui.exportFallback);
  });

  // For manual checks from the browser console only, e.g. rendering a title that contains <script>.
  window.ResearchRadar = Object.freeze({ render: (data, topic = "manual check") => renderResponse(data, topic) });
})();
