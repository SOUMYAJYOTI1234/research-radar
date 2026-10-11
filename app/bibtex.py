"""BibTeX keys and @misc entries for arXiv papers."""

import unicodedata

from app.arxiv_client import ArxivEntry

MIN_TITLE_WORD = 4  # "longer than 3 letters"


def _ascii_letters(text: str) -> str:
    """Accents removed, lowercased, only a-z kept: 'Müller' -> 'muller'."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return "".join(ch for ch in without_marks.lower() if "a" <= ch <= "z")


def make_key(paper: ArxivEntry) -> str:
    """Surname of the first author + year + first title word longer than 3 letters."""
    name_words = paper.authors[0].split() if paper.authors else []
    surname = _ascii_letters(name_words[-1]) if name_words else ""
    title_word = next(
        (word for word in map(_ascii_letters, paper.title.split()) if len(word) >= MIN_TITLE_WORD),
        "",
    )
    return f"{surname or 'anon'}{paper.published[:4]}{title_word}"


def _suffix(repeat: int) -> str:
    """0 -> '', 1 -> 'a', 2 -> 'b', ..., 26 -> 'z', 27 -> 'aa'."""
    letters = ""
    while repeat > 0:
        repeat, remainder = divmod(repeat - 1, 26)
        letters = chr(ord("a") + remainder) + letters
    return letters


def make_entries(papers: list[ArxivEntry]) -> list[str]:
    """One @misc entry per paper, in order; repeated keys get suffixes a, b, ..."""
    seen: dict[str, int] = {}
    entries = []
    for paper in papers:
        base = make_key(paper)
        key = base + _suffix(seen.get(base, 0))
        seen[base] = seen.get(base, 0) + 1
        title = paper.title.replace("{", "").replace("}", "")
        entries.append(
            f"@misc{{{key}, title={{{title}}}, author={{{' and '.join(paper.authors)}}}, "
            f"year={{{paper.published[:4]}}}, eprint={{{paper.arxiv_id}}}, archivePrefix={{arXiv}}, "
            f"primaryClass={{{paper.primary_category}}}, url={{{paper.abs_url}}}}}"
        )
    return entries
