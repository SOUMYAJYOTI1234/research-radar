# Research Radar -- Frontend Specification

## Page
One page, `app/static/index.html` with `app.js` and `styles.css`. No framework, no build step. Readable at 360 px width.

## Elements
1. Header: "Research Radar" and one line: "Type a research topic. Get a ranked arXiv reading list."
2. Search form:
   - Topic text box (placeholder "e.g. diffusion models for time series"), required.
   - Category dropdown: "Any category" plus the categories listed in the API contract, shown with readable names (for example "cs.LG Machine Learning"). Labels use arXiv's official names: cs.AI Artificial Intelligence, cs.LG Machine Learning, cs.CL Computation and Language, cs.CV Computer Vision and Pattern Recognition, cs.RO Robotics, cs.IR Information Retrieval, stat.ML Machine Learning (Statistics), quant-ph Quantum Physics, physics.comp-ph Computational Physics, math.OC Optimization and Control, eess.SP Signal Processing, q-bio.QM Quantitative Methods.
   - "From year" number box, optional.
   - Search button.
   - The page does not send `max_papers`; the API default of 20 applies.
3. Results area (states below).
4. "How Research Radar searched" panel, collapsed by default, showing the trace as a table: round, strategy, query, results found, decision, reason, time. "Results found" is `total_results`; "time" is `duration_ms` shown in seconds with 1 decimal (for example "1.8 s"). The panel is shown whenever the response has a trace, including the empty and failed states.
5. Footer: "Data from the arXiv API. Thank you to arXiv for use of its open access interoperability." and a link to the GitHub repository (one `REPO_URL` constant in `app.js`; a placeholder until the repository exists).

## States
- Idle: short example topics the user can click (for example "graph neural networks", "retrieval augmented generation", "quantum error mitigation"). A click fills the topic box and starts a search.
- Loading: Search button disabled; message "Searching arXiv. This can take up to 40 seconds because arXiv asks apps to wait between requests." Starting a search clears the previous results, chips, notice and trace panel.
- Completed: summary line from `message`; group chips ("All" plus one chip per group with its label and size) that filter the list; paper cards. When there is only one group, the chip row is hidden.
- Cached: when `cached` is true, the shown `message` ends with " (from a recent identical search)". This applies to every state that shows a cached response's `message` (completed, partial and empty).
- Partial: same as completed, with a notice. Fewer than 10 papers: "Only a few papers matched. Try a broader topic." 10 or more papers: "arXiv stopped responding partway, so these results may be incomplete."
- Empty: the `message` text and the example topics again.
- Failed: the `message` text and a "Try again" button. Never show raw error text or stack traces.
- Unreachable (network error, any status other than 200, 422 or 429, a response that is not JSON, or no response within 60 seconds): "Research Radar could not be reached. If the app was asleep, wait a minute and try again." and a "Try again" button.
- 422: before sending, the page checks the same rules as the API (topic 3 to 100 characters after trimming, from_year 2000 to the current UTC year, category from the list) and shows each message next to its own field. If a 422 still arrives: a string `detail` is shown as-is next to the topic box; a list `detail` is mapped by field (`loc`) to a fixed message (for example "Topic must be 3 to 100 characters.") shown next to that field. Raw FastAPI error text is never shown.
- 429: "Too many searches. Please wait a minute."

## Paper card
- Title linked to `abs_url` (opens in a new tab).
- Authors: first 3 names, then "et al." if more.
- Published date, primary category, score shown with 2 decimals, for example "score 0.73".
- Abstract: first 2 lines with a "Show abstract" toggle.
- Buttons: "PDF" (link to `pdf_url`), "Copy BibTeX" (copies `bibtex`; shows "Copied" for 2 seconds).

## Export (applies to the papers currently shown after group filtering)
- "Download .bib": a file `research-radar-<topic-slug>.bib` with all BibTeX entries. Slug: the searched topic in lowercase, each run of characters that are not letters or digits replaced by "-", leading and trailing "-" removed, at most 50 characters; "search" if empty.
- "Copy Markdown list": numbered lines `1. [Title](abs_url) - First Author et al., YYYY`. "et al." is added only when the paper has 2 or more authors (one author: `- Jane Doe, 2023`). Shows "Copied" for 2 seconds.
- Copy failure (either copy button): the button shows "Copy failed" for 2 seconds and the text appears in a read-only, pre-selected text box so the user can copy it by hand.

## Behaviour rules
- One search at a time. While loading, the Search button, the Enter key and "Try again" do nothing, and clicking an example topic only fills the box.
- "Try again" re-sends the exact inputs of the search that failed.
- If the user starts a new search, results from an older request must not replace the newer one (track a request counter and drop stale responses). The counter stays as a safety net even though searches are blocked while loading.
- Escape all text from the API before inserting it into the page (titles and abstracts can contain `<` and `&`).
