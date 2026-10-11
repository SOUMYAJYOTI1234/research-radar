"""Scoring papers against the topic and grouping them into themes."""

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.arxiv_client import ArxivEntry

RELEVANCE_WEIGHT = 0.8
RECENCY_WEIGHT = 0.2
RECENCY_YEARS = 10
MIN_PAPERS_TO_GROUP = 8
MAX_GROUPS = 4
LABEL_TERMS = 3
ALL_RESULTS = "All results"
OTHER = "Other"

# TfidfVectorizer's default token pattern, used to split query terms the way documents are split.
_TOKEN = re.compile(r"(?u)\b\w\w+\b")


@dataclass
class Ranking:
    entries: list[ArxivEntry]  # the kept papers, best first
    scores: list[float]
    vectors: Any  # sparse TF-IDF rows for `entries`, in the same order
    feature_names: list[str]
    query_terms: list[str]


@dataclass
class GroupInfo:
    group_id: int
    label: str
    size: int


def recency(published: str, today: date) -> float:
    return max(0.0, 1 - (today.year - int(published[:4])) / RECENCY_YEARS)


def rank(entries: list[ArxivEntry], query_terms: list[str], max_papers: int, today: date) -> Ranking:
    """Score every entry and keep the top `max_papers`."""
    if not entries:
        return Ranking([], [], None, [], list(query_terms))
    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
    matrix = vectorizer.fit_transform([f"{e.title} {e.title} {e.abstract}" for e in entries])
    relevance = cosine_similarity(vectorizer.transform([" ".join(query_terms)]), matrix)[0]
    # Min-max normalise over the whole accepted round, before the max_papers cut.
    lowest, highest = relevance.min(), relevance.max()
    if highest > lowest:
        normalised = (relevance - lowest) / (highest - lowest)
    else:
        normalised = np.ones_like(relevance)
    scores = [
        round(RELEVANCE_WEIGHT * float(r) + RECENCY_WEIGHT * recency(e.published, today), 3)
        for e, r in zip(entries, normalised)
    ]

    # Stable sorts, last key first: score desc, then published desc, then arxiv_id asc.
    order = sorted(range(len(entries)), key=lambda i: entries[i].arxiv_id)
    order.sort(key=lambda i: entries[i].published, reverse=True)
    order.sort(key=lambda i: scores[i], reverse=True)
    order = order[:max_papers]

    return Ranking(
        entries=[entries[i] for i in order],
        scores=[scores[i] for i in order],
        vectors=matrix[order],
        feature_names=vectorizer.get_feature_names_out().tolist(),
        query_terms=list(query_terms),
    )


def order_clusters(labels: np.ndarray, k: int) -> list[int]:
    """Cluster indices, largest first; equal sizes keep the lower cluster index first. Empty clusters are left out."""
    sizes = np.bincount(labels, minlength=k)
    return sorted((c for c in range(k) if sizes[c] > 0), key=lambda c: (-sizes[c], c))


def group(ranking: Ranking) -> tuple[list[int], list[GroupInfo]]:
    """Return the group id of each kept paper, and the groups numbered by size."""
    n = len(ranking.entries)
    if n == 0:
        return [], []
    if n < MIN_PAPERS_TO_GROUP:
        return [0] * n, [GroupInfo(0, ALL_RESULTS, n)]

    k = min(MAX_GROUPS, n // 4)
    kmeans = KMeans(n_clusters=k, random_state=42, n_init=10).fit(ranking.vectors)
    order = order_clusters(kmeans.labels_, k)
    new_id = {cluster: i for i, cluster in enumerate(order)}
    sizes = np.bincount(kmeans.labels_, minlength=k)
    groups = [
        GroupInfo(
            new_id[c],
            make_label(kmeans.cluster_centers_[c], ranking.feature_names, ranking.query_terms),
            int(sizes[c]),
        )
        for c in order
    ]
    return [new_id[c] for c in kmeans.labels_], groups


def make_label(centroid: np.ndarray, feature_names: list[str], query_terms: list[str]) -> str:
    """The top centroid terms that do not repeat the query, or "Other" if none are left.

    A term is left out when any of its words starts with a query term (so "graphs" and
    "graph learning" go for the query term "graph", but "subgraph" stays). Equal weights are
    ordered alphabetically so labels are stable.
    """
    query_words = [word for term in query_terms for word in _TOKEN.findall(term.lower())]
    allowed = [
        j
        for j, name in enumerate(feature_names)
        if centroid[j] > 0 and not any(word.startswith(q) for word in name.split() for q in query_words)
    ]
    top = sorted(allowed, key=lambda j: (-centroid[j], feature_names[j]))[:LABEL_TERMS]
    return ", ".join(feature_names[j] for j in top) or OTHER
