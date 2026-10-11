"""BibTeX keys and @misc entries for arXiv papers."""

import re
import unicodedata

from app.arxiv_client import ArxivEntry

MIN_TITLE_WORD = 4  # "longer than 3 letters"

# A LaTeX special character that is not already escaped.
_LATEX_SPECIAL = re.compile(r"(?<!\\)([&%#_$])")


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


def _braces_balanced(text: str) -> bool:
    """True if every '}' closes an earlier '{' and none is left open."""
    depth = 0
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _math_delimiters(text: str) -> list[int]:
    """Positions of the '$' signs that open and close math, paired left to right.

    A '$' after a backslash is not a delimiter, and a final unpaired '$' is ordinary text.
    """
    positions = [i for i, ch in enumerate(text) if ch == "$" and (i == 0 or text[i - 1] != "\\")]
    return positions[: len(positions) - len(positions) % 2]


def _format_title(title: str) -> str:
    """Keep balanced braces and $...$ math; escape LaTeX special characters elsewhere."""
    if not _braces_balanced(title):
        title = title.replace("{", "").replace("}", "")
    delimiters = _math_delimiters(title)
    parts, start = [], 0
    for opening, closing in zip(delimiters[::2], delimiters[1::2]):
        parts.append(_LATEX_SPECIAL.sub(r"\\\1", title[start:opening]))
        parts.append(title[opening : closing + 1])
        start = closing + 1
    parts.append(_LATEX_SPECIAL.sub(r"\\\1", title[start:]))
    return "".join(parts)


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
        title = _format_title(paper.title)
        entries.append(
            f"@misc{{{key}, title={{{title}}}, author={{{' and '.join(paper.authors)}}}, "
            f"year={{{paper.published[:4]}}}, eprint={{{paper.arxiv_id}}}, archivePrefix={{arXiv}}, "
            f"primaryClass={{{paper.primary_category}}}, url={{{paper.abs_url}}}}}"
        )
    return entries
