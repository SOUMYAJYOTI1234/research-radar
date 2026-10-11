"""Topic normalisation and arXiv query building."""

from datetime import date

STOP_WORDS = frozenset(
    {"for", "of", "the", "and", "in", "on", "a", "an", "to", "with", "using", "via", "by", "from", "at", "is", "are"}
)
MAX_TERMS = 6
NARROWED_YEARS = 5

STRATEGIES = ("exact", "all_words", "any_word")


class InvalidTopic(ValueError):
    """The topic cannot be searched; `message` is shown to the user."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def normalise(topic: str) -> list[str]:
    """Return the search terms for a topic, or raise InvalidTopic."""
    trimmed = topic.strip()
    if not 3 <= len(trimmed) <= 100:
        raise InvalidTopic("Topic must be 3 to 100 characters.")
    text = " ".join(trimmed.lower().split())
    # Split on any character that is not a letter, digit or hyphen.
    words = "".join(ch if ch.isalnum() or ch == "-" else " " for ch in text).split()
    terms = [word for word in words if len(word) >= 2 and word not in STOP_WORDS][:MAX_TERMS]
    if not terms:
        raise InvalidTopic("Topic needs at least one meaningful word.")
    return terms


def strategies_for(terms: list[str]) -> list[str]:
    """Rounds from narrow to broad; any_word only exists with at least 2 terms."""
    return list(STRATEGIES) if len(terms) >= 2 else list(STRATEGIES[:2])


def build_query(
    strategy: str,
    terms: list[str],
    category: str | None,
    from_year: int | None,
    today: date,
    narrowed: bool = False,
) -> str:
    """Build the exact arXiv search_query string for one round."""
    if strategy == "exact":
        phrase = " ".join(terms)
        query = f'(ti:"{phrase}" OR abs:"{phrase}")'
    elif strategy == "all_words":
        query = "(" + " AND ".join(f"all:{term}" for term in terms) + ")"
    elif strategy == "any_word":
        query = "(" + " OR ".join(f"all:{term}" for term in terms) + ")"
    else:
        raise ValueError(f"unknown strategy {strategy!r}")

    if category:
        query += f" AND cat:{category}"
    if narrowed:
        if from_year is not None:
            raise ValueError("narrowing is only used when no from_year is given")
        from_year = today.year - (NARROWED_YEARS - 1)
    if from_year is not None:
        query += f" AND submittedDate:[{from_year}01010000 TO {today:%Y%m%d}2359]"
    return query
