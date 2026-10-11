# Research Radar: project instructions for Claude Code

## What this project is
A web app: the user types a research topic, the backend searches arXiv through its free public API (no API key), ranks and groups the papers, and returns a reading list with links, BibTeX and a visible trace of the search steps.

## Source of truth
- The specs in `specs/` are the source of truth. Read all of them before planning.
- If a spec is unclear or two specs disagree, stop and ask me. Do not resolve it silently.
- If I approve a behaviour change, update the spec first, then the code and tests.
- Do not add features that are not in the specs. Record ideas under "Open questions" in the relevant spec instead.

## Stack (do not change without asking)
- Python 3.12, FastAPI, Uvicorn, httpx, scikit-learn, numpy. Parse Atom XML with the standard library (`xml.etree.ElementTree`).
- Frontend: one static page in `app/static/` (HTML, CSS, vanilla JavaScript), served by FastAPI. No React, no build step.
- No database. No user accounts. No LLM or paid API.
- Tests: pytest. Use `httpx.MockTransport` with recorded Atom fixtures in `tests/fixtures/`.
- Deployment: one Docker container on Render (free web service).

## Commands
- Install: `pip install -r requirements.txt`
- Run locally: `uvicorn app.main:app --reload --port 8000`
- Tests: `pytest -q`
- Evaluation (live, slow, calls arXiv): `python eval/run_eval.py`

## Authorship
- Soumyajyoti Chatterjee is the sole author and only contributor of this project. Do not add yourself as a co-author or contributor anywhere: no Co-Authored-By lines, no "Generated with Claude Code" lines, and no attribution in commits, pull requests, README, code comments or file headers.

## Rules
- - Git: at the end of every phase, only if all tests pass, run git add, git commit with the message "P<n>: <short description>", and git push. Before pushing, show me the output of `git log -1 --format=full`. Use my existing git identity (Soumyajyoti Chatterjee). Never change git config, never force-push, and never add Co-Authored-By or any other attribution line. If tests fail, do not commit; tell me instead.
- Unit and integration tests must never call the real arXiv API.
- Keep at least 3 seconds between outbound arXiv requests (one shared limiter for the whole process).
- Never add a dependency without asking me first.
- Work one phase at a time. After each phase, run the tests and show me the result before continuing.
- When you report completion, state what you ran and what you did not verify.
