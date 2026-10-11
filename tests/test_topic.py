from datetime import date

import pytest

from app.topic import InvalidTopic, build_query, normalise, strategies_for

TODAY = date(2026, 10, 11)
TERMS = ["diffusion", "models", "time", "series"]


# --- normalise -----------------------------------------------------------------


def test_trims_lowercases_and_collapses_whitespace():
    assert normalise("   Diffusion   MODELS\tfor\n time  series  ") == TERMS


@pytest.mark.parametrize("topic", ["ab", "  ab  ", "a" * 101, "  " + "a" * 101 + "  "])
def test_length_outside_3_to_100_after_trimming_is_rejected(topic):
    with pytest.raises(InvalidTopic) as info:
        normalise(topic)
    assert info.value.message == "Topic must be 3 to 100 characters."


@pytest.mark.parametrize("topic", ["gan", "  gan  ", "a" * 100])
def test_length_3_and_100_after_trimming_are_accepted(topic):
    assert normalise(topic)


def test_splits_on_punctuation_but_keeps_hyphens():
    assert normalise("Self-supervised learning, graphs/GNNs: (survey)!") == [
        "self-supervised",
        "learning",
        "graphs",
        "gnns",
        "survey",
    ]


def test_keeps_digits_and_non_ascii_letters():
    assert normalise("GPT-4 für Übersetzung") == ["gpt-4", "für", "übersetzung"]


def test_drops_stop_words_and_one_character_terms():
    topic = "a survey of the use of x and y in graphs for vision using attention via transformers"
    assert normalise(topic) == ["survey", "use", "graphs", "vision", "attention", "transformers"]


def test_keeps_at_most_six_terms():
    assert normalise("one two three four five six seven eight") == [
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
    ]


@pytest.mark.parametrize("topic", ["the of and", "a b c d", "for ... with !!! by"])
def test_no_meaningful_word_is_rejected(topic):
    with pytest.raises(InvalidTopic) as info:
        normalise(topic)
    assert info.value.message == "Topic needs at least one meaningful word."


# --- strategies ------------------------------------------------------------------


def test_any_word_only_exists_with_two_or_more_terms():
    assert strategies_for(["transformers"]) == ["exact", "all_words"]
    assert strategies_for(["graph", "networks"]) == ["exact", "all_words", "any_word"]


# --- build_query -----------------------------------------------------------------


def test_exact_query():
    assert build_query("exact", TERMS, None, None, TODAY) == (
        '(ti:"diffusion models time series" OR abs:"diffusion models time series")'
    )


def test_all_words_query():
    assert build_query("all_words", TERMS, None, None, TODAY) == (
        "(all:diffusion AND all:models AND all:time AND all:series)"
    )


def test_any_word_query():
    assert build_query("any_word", TERMS, None, None, TODAY) == (
        "(all:diffusion OR all:models OR all:time OR all:series)"
    )


def test_single_term_all_words_query():
    assert build_query("all_words", ["transformers"], None, None, TODAY) == "(all:transformers)"


def test_category_filter():
    assert build_query("all_words", ["graph", "networks"], "cs.LG", None, TODAY) == (
        "(all:graph AND all:networks) AND cat:cs.LG"
    )


def test_from_year_filter_runs_to_today_utc():
    assert build_query("all_words", ["graph", "networks"], None, 2020, TODAY) == (
        "(all:graph AND all:networks) AND submittedDate:[202001010000 TO 202610112359]"
    )


def test_category_and_from_year_together_match_the_contract_example():
    assert build_query("exact", TERMS, "cs.LG", 2020, date(2026, 10, 10)) == (
        '(ti:"diffusion models time series" OR abs:"diffusion models time series")'
        " AND cat:cs.LG AND submittedDate:[202001010000 TO 202610102359]"
    )


def test_narrowed_query_covers_the_last_five_years():
    assert build_query("exact", TERMS, None, None, TODAY, narrowed=True) == (
        '(ti:"diffusion models time series" OR abs:"diffusion models time series")'
        " AND submittedDate:[202201010000 TO 202610112359]"
    )


def test_narrowed_bounds_follow_the_injected_today():
    assert build_query("all_words", ["qubit"], "quant-ph", None, date(2031, 1, 5), narrowed=True) == (
        "(all:qubit) AND cat:quant-ph AND submittedDate:[202701010000 TO 203101052359]"
    )


def test_title_query_is_the_phrase_in_titles_with_the_same_filters():
    assert build_query("title", TERMS, None, None, TODAY) == 'ti:"diffusion models time series"'
    assert build_query("title", TERMS, "cs.LG", 2020, TODAY) == (
        'ti:"diffusion models time series" AND cat:cs.LG AND submittedDate:[202001010000 TO 202610112359]'
    )
