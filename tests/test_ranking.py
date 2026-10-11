from datetime import date

import numpy as np
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.arxiv_client import parse_feed
from app.ranking import group, make_label, order_clusters, rank, recency
from app.topic import normalise

TODAY = date(2026, 10, 11)
TERMS = ["diffusion", "models", "time", "series"]


def entries_from(load_fixture, *names):
    return [entry for name in names for entry in parse_feed(load_fixture(name))[1]]


def ids(entries):
    return [entry.arxiv_id for entry in entries]


# --- Scoring -------------------------------------------------------------------------


def test_score_is_relevance_and_recency_weighted_and_rounded(load_fixture):
    entries = entries_from(load_fixture, "normal.xml")
    ranking = rank(entries, TERMS, 30, TODAY)

    # Independent computation straight from the spec: title counted twice, these TF-IDF settings,
    # cosine similarity against the joined terms, min-max normalised over the round,
    # recency over 10 years, weights 0.8 / 0.2.
    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
    matrix = vectorizer.fit_transform([f"{e.title} {e.title} {e.abstract}" for e in entries])
    relevance = cosine_similarity(vectorizer.transform([" ".join(TERMS)]), matrix)[0]
    normalised = (relevance - relevance.min()) / (relevance.max() - relevance.min())
    expected = {
        e.arxiv_id: round(0.8 * r + 0.2 * max(0.0, 1 - (2026 - int(e.published[:4])) / 10), 3)
        for e, r in zip(entries, normalised)
    }
    assert dict(zip(ids(ranking.entries), ranking.scores)) == expected


def test_scores_have_at_most_3_decimals(load_fixture):
    ranking = rank(entries_from(load_fixture, "normal.xml", "broad.xml"), TERMS, 30, TODAY)
    assert all(score == round(score, 3) for score in ranking.scores)
    assert any(score != round(score, 2) for score in ranking.scores), "scores are not cut to 2 decimals"


def test_equal_relevance_gives_every_paper_1(make_entry):
    # None of the papers mentions the topic, so all relevances are equal (0) and normalise to 1.
    entries = [
        make_entry("2101.00001", title="Graph Networks", abstract="Message passing.", published="2021-01-05"),
        make_entry("2601.00001", title="Graph Networks", abstract="Message passing.", published="2026-01-05"),
        make_entry("1001.0001", title="Graph Networks", abstract="Message passing.", published="2010-01-05"),
    ]
    ranking = rank(entries, ["quantum"], 30, TODAY)
    assert dict(zip(ids(ranking.entries), ranking.scores)) == {
        "2601.00001": 1.0,
        "2101.00001": 0.9,
        "1001.0001": 0.8,
    }


def test_relevance_is_min_max_normalised_over_the_round(make_entry):
    published = "2026-01-05"  # recency 1 for every paper
    entries = [
        make_entry("2601.00001", title="Quantum Error Mitigation", abstract="Quantum noise in quantum devices.",
                   published=published),
        make_entry("2601.00002", title="Noise in Devices", abstract="A short note on quantum noise.",
                   published=published),
        make_entry("2601.00003", title="Graph Networks", abstract="Message passing on graphs.", published=published),
    ]
    ranking = rank(entries, ["quantum"], 30, TODAY)
    scores = dict(zip(ids(ranking.entries), ranking.scores))
    assert scores["2601.00001"] == 1.0, "the most relevant paper gets normalised relevance 1"
    assert scores["2601.00003"] == 0.2, "the least relevant paper gets normalised relevance 0"
    assert 0.2 < scores["2601.00002"] < 1.0


def test_normalisation_uses_the_whole_round_not_only_the_kept_papers(make_entry):
    published = "2026-01-05"
    entries = [
        make_entry("2601.00001", title="Quantum Error Mitigation", abstract="Quantum noise.", published=published),
        make_entry("2601.00002", title="Noise in Devices", abstract="On quantum noise.", published=published),
        make_entry("2601.00003", title="Graph Networks", abstract="Message passing.", published=published),
    ]
    full = rank(entries, ["quantum"], 30, TODAY)
    top2 = rank(entries, ["quantum"], 2, TODAY)
    assert top2.scores == full.scores[:2]
    assert top2.scores[1] < 1.0, "the second paper is not stretched to 1 by cutting the third"


@pytest.mark.parametrize(
    ("published", "expected"),
    [("2026-03-01", 1.0), ("2021-12-31", 0.5), ("2017-01-01", 0.1), ("2016-06-01", 0.0), ("2009-01-01", 0.0)],
)
def test_recency_falls_to_0_at_10_years(published, expected):
    assert recency(published, TODAY) == pytest.approx(expected)


def test_title_counts_twice(make_entry):
    # With the title counted twice, one mention in the title beats two in the abstract;
    # with the title counted once, the order flips.
    in_title = make_entry("2401.00001", title="Quantum", abstract="alpha beta gamma delta")
    in_abstract = make_entry("2401.00002", title="Alpha", abstract="quantum quantum beta gamma delta")
    ranking = rank([in_abstract, in_title], ["quantum"], 30, TODAY)
    assert ids(ranking.entries) == ["2401.00001", "2401.00002"]


# --- Ordering and the max_papers cut ---------------------------------------------------


def test_sorted_by_score_then_newest_published_then_lowest_id(make_entry):
    same = dict(title="Graph Networks", abstract="Message passing on graphs.")
    entries = [
        make_entry("2405.00002", published="2024-05-01", **same),
        make_entry("2403.00009", published="2024-03-01", **same),
        make_entry("2405.00001", published="2024-05-01", **same),
        make_entry("2406.00005", published="2024-06-01", **same),
        make_entry("2402.00001", title="Quantum Error Mitigation", abstract="Quantum noise.", published="2024-02-01"),
    ]
    ranking = rank(entries, ["quantum"], 30, TODAY)
    assert ids(ranking.entries) == ["2402.00001", "2406.00005", "2405.00001", "2405.00002", "2403.00009"]
    assert ranking.scores[0] > ranking.scores[1] == ranking.scores[4]


def test_scores_never_increase_down_the_list(load_fixture):
    ranking = rank(entries_from(load_fixture, "normal.xml", "broad.xml"), TERMS, 30, TODAY)
    assert ranking.scores == sorted(ranking.scores, reverse=True)


def test_keeps_the_top_max_papers(load_fixture):
    entries = entries_from(load_fixture, "normal.xml")
    full = rank(entries, TERMS, 30, TODAY)
    top5 = rank(entries, TERMS, 5, TODAY)
    assert len(full.entries) == 12
    assert ids(top5.entries) == ids(full.entries)[:5]
    assert top5.scores == full.scores[:5]
    assert top5.vectors.shape[0] == 5


def test_same_terms_from_different_phrasing_rank_the_same(load_fixture):
    entries = entries_from(load_fixture, "normal.xml")
    first = normalise("Diffusion Models for Time Series")
    second = normalise("  diffusion, models;  time   SERIES ")
    assert first == second
    assert ids(rank(entries, first, 20, TODAY).entries) == ids(rank(entries, second, 20, TODAY).entries)


def test_no_entries_gives_an_empty_ranking():
    ranking = rank([], TERMS, 20, TODAY)
    assert ranking.entries == [] and ranking.scores == []
    assert group(ranking) == ([], [])


# --- Grouping --------------------------------------------------------------------------


def test_fewer_than_8_papers_give_one_all_results_group(load_fixture):
    ranking = rank(entries_from(load_fixture, "normal.xml"), TERMS, 7, TODAY)
    group_ids, groups = group(ranking)
    assert group_ids == [0] * 7
    assert [(g.group_id, g.label, g.size) for g in groups] == [(0, "All results", 7)]


@pytest.mark.parametrize(("n", "k"), [(8, 2), (12, 3), (15, 3), (16, 4), (20, 4)])
def test_8_or_more_papers_give_k_groups_numbered_by_size(load_fixture, n, k):
    ranking = rank(entries_from(load_fixture, "normal.xml", "broad.xml"), TERMS, n, TODAY)
    group_ids, groups = group(ranking)
    assert len(group_ids) == n
    assert [g.group_id for g in groups] == list(range(k))
    sizes = [g.size for g in groups]
    assert sum(sizes) == n
    assert sizes == sorted(sizes, reverse=True), "group 0 is the largest"
    assert sizes == [group_ids.count(g.group_id) for g in groups]


def test_group_label_is_the_top_3_centroid_terms(load_fixture):
    ranking = rank(entries_from(load_fixture, "normal.xml", "broad.xml"), TERMS, 20, TODAY)
    group_ids, groups = group(ranking)
    vectors = ranking.vectors.toarray()
    for g in groups:
        # A converged KMeans centroid is the mean of its members' vectors; the label rules
        # themselves are tested on make_label below.
        centroid = vectors[[i for i, gid in enumerate(group_ids) if gid == g.group_id]].mean(axis=0)
        assert g.label == make_label(centroid, ranking.feature_names, TERMS)
        assert len(set(g.label.split(", "))) == 3


def test_labels_leave_out_query_terms_in_real_groups(load_fixture):
    terms = ["graph", "neural", "networks"]
    ranking = rank(entries_from(load_fixture, "normal.xml", "broad.xml"), terms, 20, TODAY)
    _, groups = group(ranking)
    for g in groups:
        for term in g.label.split(", "):
            assert not any(word.startswith(t) for word in term.split() for t in terms), g.label


# --- Labels ----------------------------------------------------------------------------

NAMES = ["attention", "graph", "graph neural", "graphs", "message passing", "neural networks", "pooling", "subgraph"]


def weights(**by_name):
    return np.array([by_name.get(name.replace(" ", "_"), 0.0) for name in NAMES])


def test_label_leaves_out_query_terms_plurals_and_phrases_but_keeps_subgraph():
    centroid = weights(graph=0.9, graphs=0.8, graph_neural=0.7, neural_networks=0.6, subgraph=0.5, pooling=0.4,
                       message_passing=0.3, attention=0.2)
    assert make_label(centroid, NAMES, ["graph", "neural", "networks"]) == "subgraph, pooling, message passing"


def test_label_with_fewer_than_3_terms_left_uses_what_remains():
    centroid = weights(graph=0.9, graphs=0.8, subgraph=0.5)  # every other term has weight 0
    assert make_label(centroid, NAMES, ["graph", "neural"]) == "subgraph"


def test_label_with_no_terms_left_is_other():
    centroid = weights(graph=0.9, graphs=0.8, graph_neural=0.4)
    assert make_label(centroid, NAMES, ["graph", "neural"]) == "Other"


def test_label_splits_hyphenated_query_terms_like_tfidf():
    names = ["contrastive", "self", "selfish", "supervised learning"]
    centroid = np.array([0.1, 0.9, 0.8, 0.7])
    assert make_label(centroid, names, ["self-supervised"]) == "contrastive"


def test_longer_term_replaces_a_chosen_term_it_contains():
    names = ["enhanced", "node", "node classification", "pooling"]
    centroid = np.array([0.8, 0.9, 0.7, 0.6])  # by weight: node, enhanced, node classification, pooling
    assert make_label(centroid, names, ["graph"]) == "node classification, enhanced, pooling"


def test_term_whose_words_are_all_in_a_chosen_term_is_skipped():
    names = ["classification", "enhanced", "node", "node classification", "pooling"]
    centroid = np.array([0.7, 0.5, 0.8, 0.9, 0.6])  # node classification first, then node, classification
    assert make_label(centroid, names, ["graph"]) == "node classification, pooling, enhanced"


def test_longer_term_covering_two_chosen_terms_replaces_both():
    names = ["attention", "message", "message passing", "passing", "pooling"]
    centroid = np.array([0.5, 0.9, 0.7, 0.8, 0.6])  # message, passing, message passing, pooling, attention
    assert make_label(centroid, names, ["graph"]) == "message passing, pooling, attention"


def test_label_orders_equal_weights_alphabetically():
    centroid = weights(pooling=0.5, attention=0.5, subgraph=0.5, message_passing=0.5)
    assert make_label(centroid, NAMES, ["graph"]) == "attention, message passing, pooling"


def test_size_ties_go_to_the_lowest_original_cluster():
    # Clusters 0 and 2 both have 2 members, cluster 1 has one.
    assert order_clusters(np.array([2, 2, 0, 0, 1]), 3) == [0, 2, 1]


def test_same_output_on_repeated_runs(load_fixture):
    entries = entries_from(load_fixture, "normal.xml", "broad.xml")
    runs = []
    for _ in range(3):
        ranking = rank(entries, TERMS, 20, TODAY)
        group_ids, groups = group(ranking)
        runs.append((ids(ranking.entries), ranking.scores, group_ids, [(g.group_id, g.label, g.size) for g in groups]))
    assert runs[0] == runs[1] == runs[2]
