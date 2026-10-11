"""AC8: every paper has a BibTeX entry containing its arXiv ID, title, authors and year."""

import re

from app.arxiv_client import parse_feed
from app.bibtex import make_entries, make_key


def keys(entries):
    return [re.match(r"@misc\{([^,]*),", entry).group(1) for entry in entries]


def title_of(title, make_entry):
    [entry] = make_entries([make_entry(title=title)])
    return re.search(r"title=\{(.*)\}, author=", entry).group(1)


# --- Entry contents (AC8) ------------------------------------------------------------


def test_every_entry_has_id_title_all_authors_and_year(load_fixture):
    papers = parse_feed(load_fixture("normal.xml"))[1] + parse_feed(load_fixture("old_style_id.xml"))[1]
    entries = make_entries(papers)
    assert len(entries) == len(papers)
    for paper, entry in zip(papers, entries):
        # These titles have balanced braces and special characters only inside $...$, so they are kept as is.
        assert f"eprint={{{paper.arxiv_id}}}" in entry
        assert f"title={{{paper.title}}}" in entry
        assert f"author={{{' and '.join(paper.authors)}}}" in entry
        assert f"year={{{paper.published[:4]}}}" in entry


def test_entry_format(make_entry):
    paper = make_entry(
        "1706.03762",
        title="Attention Is All You Need",
        authors=("Ashish Vaswani", "Noam Shazeer", "Niki Parmar"),
        published="2017-06-12",
        primary_category="cs.CL",
    )
    assert make_entries([paper]) == [
        "@misc{vaswani2017attention, title={Attention Is All You Need}, "
        "author={Ashish Vaswani and Noam Shazeer and Niki Parmar}, year={2017}, eprint={1706.03762}, "
        "archivePrefix={arXiv}, primaryClass={cs.CL}, url={https://arxiv.org/abs/1706.03762}}"
    ]


# --- Titles: braces, math and escaping ---------------------------------------------------


def test_balanced_braces_are_kept(make_entry):
    assert title_of(r"A {GPU} Study of {{Sparse}} Graphs", make_entry) == r"A {GPU} Study of {{Sparse}} Graphs"


def test_unbalanced_braces_are_all_removed(make_entry):
    assert title_of(r"A {GPU Study}} of {Graphs}", make_entry) == r"A GPU Study of Graphs"
    assert title_of(r"A }GPU{ Study", make_entry) == r"A GPU Study"
    assert title_of(r"An {Open Brace", make_entry) == r"An Open Brace"


def test_math_segment_is_left_unchanged(make_entry):
    title = r"Generating Synthetic Financial Time Series with $\mathcal{O}(T)$ Diffusion Sampling"
    assert title_of(title, make_entry) == title


def test_ampersand_outside_math_is_escaped(make_entry):
    assert title_of("R&D for Graph Neural Networks", make_entry) == r"R\&D for Graph Neural Networks"


def test_special_characters_escaped_outside_math_only(make_entry):
    assert title_of(r"R&D with $O(n_1)$ cost & 5% loss on #2", make_entry) == (
        r"R\&D with $O(n_1)$ cost \& 5\% loss on \#2"
    )
    assert title_of(r"$a_1$ & $b_{2}$ graph_nets", make_entry) == r"$a_1$ \& $b_{2}$ graph\_nets"


def test_unpaired_dollar_is_escaped_as_text(make_entry):
    assert title_of("R&D at 100% for #1 graph_nets under $5", make_entry) == (
        r"R\&D at 100\% for \#1 graph\_nets under \$5"
    )


def test_escaped_dollar_is_not_a_math_delimiter(make_entry):
    assert title_of(r"\$5 GPUs and $x_1$ & more", make_entry) == r"\$5 GPUs and $x_1$ \& more"


def test_already_escaped_characters_are_not_escaped_twice(make_entry):
    assert title_of(r"R\&D and Q&A", make_entry) == r"R\&D and Q\&A"


def test_escaping_does_not_change_the_key(make_entry):
    paper = make_entry(authors=("Ada Lovelace",), published="2024-01-01", title="R&D_Graphs for #GNNs")
    assert make_key(paper) == "lovelace2024rdgraphs"


def test_old_style_id_in_eprint(load_fixture):
    paper = parse_feed(load_fixture("old_style_id.xml"))[1][0]
    [entry] = make_entries([paper])
    assert "eprint={hep-th/9901001}" in entry
    assert "url={https://arxiv.org/abs/hep-th/9901001}" in entry


# --- Key rules -------------------------------------------------------------------------


def test_key_is_surname_year_and_first_long_title_word(make_entry):
    paper = make_entry(title="Attention Is All You Need", authors=("Ashish Vaswani",), published="2017-06-12")
    assert make_key(paper) == "vaswani2017attention"


def test_surname_is_the_last_word_of_the_first_author(make_entry):
    paper = make_entry(authors=("Ludwig van Beethoven", "Ada Lovelace"), published="2020-01-01", title="Symphony")
    assert make_key(paper) == "beethoven2020symphony"


def test_accents_removed_from_surname(make_entry):
    assert make_key(make_entry(authors=("Lukas Müller",), published="2023-06-20", title="Graphs")) == (
        "muller2023graphs"
    )
    assert make_key(make_entry(authors=("Diego Fernández",), published="2025-09-12", title="Graphs")) == (
        "fernandez2025graphs"
    )


def test_only_a_to_z_kept_in_surname(make_entry):
    assert make_key(make_entry(authors=("Sinéad O'Connor-Smith",), published="2022-01-01", title="Graphs")) == (
        "oconnorsmith2022graphs"
    )


def test_non_latin_surname_gives_anon(make_entry):
    assert make_key(make_entry(authors=("王小明",), published="2024-01-01", title="Graphs")) == "anon2024graphs"


def test_no_authors_gives_anon(make_entry):
    assert make_key(make_entry(authors=(), published="2024-01-01", title="Graphs")) == "anon2024graphs"


def test_title_word_skips_words_of_3_letters_or_fewer(make_entry):
    paper = make_entry(authors=("Ada Lovelace",), published="2024-01-01", title="On a New GAN for Graphs")
    assert make_key(paper) == "lovelace2024graphs"


def test_title_word_is_letters_only_lowercased_and_accent_stripped(make_entry):
    assert make_key(make_entry(published="2024-01-01", title="Self-Supervised Graphs")) == (
        "lovelace2024selfsupervised"
    )
    assert make_key(make_entry(published="2024-01-01", title="Über Graphen")) == "lovelace2024uber"
    # "3-GAN" has 5 characters but only 3 letters, so it is skipped.
    assert make_key(make_entry(published="2024-01-01", title="3-GAN Models")) == "lovelace2024models"


def test_no_title_word_longer_than_3_letters_leaves_that_part_out(make_entry):
    assert make_key(make_entry(published="2019-01-01", title="On a GAN")) == "lovelace2019"
    assert make_key(make_entry(published="2019-01-01", title="图神经网络")) == "lovelace2019"


def test_title_word_length_is_counted_on_a_to_z_letters(make_entry):
    # A non-Latin word has no a-z letters, so the next word that has more than 3 is used.
    assert make_key(make_entry(published="2019-01-01", title="图神经网络 Graphs")) == "lovelace2019graphs"


def test_year_comes_from_published(make_entry):
    paper = make_entry(published="1999-01-04", title="Branes")
    paper.updated = "2003-02-11"
    assert make_key(paper) == "lovelace1999branes"


def test_repeated_keys_get_a_then_b_in_response_order(make_entry):
    same = dict(authors=("Ashish Vaswani",), published="2017-06-12", title="Attention Is All You Need")
    papers = [
        make_entry("1706.00001", **same),
        make_entry("1706.00002", authors=("Ada Lovelace",), published="2017-01-01", title="Engines"),
        make_entry("1706.00003", **same),
        make_entry("1706.00004", **same),
    ]
    assert keys(make_entries(papers)) == [
        "vaswani2017attention",
        "lovelace2017engines",
        "vaswani2017attentiona",
        "vaswani2017attentionb",
    ]


def test_keys_unique_in_a_real_feed(load_fixture):
    papers = parse_feed(load_fixture("normal.xml"))[1] + parse_feed(load_fixture("broad.xml"))[1]
    found = keys(make_entries(papers))
    assert len(set(found)) == len(found)
