"""Pydantic response models, field for field from specs/api-contract-spec.md."""

from typing import Literal

from pydantic import BaseModel


class Paper(BaseModel):
    arxiv_id: str
    title: str
    authors: list[str]
    published: str
    updated: str
    primary_category: str
    abstract: str
    abs_url: str
    pdf_url: str
    score: float
    group_id: int
    bibtex: str


class Group(BaseModel):
    group_id: int
    label: str
    size: int


class TraceEntry(BaseModel):
    round: int
    strategy: str
    query: str
    total_results: int
    returned: int
    decision: Literal["accept", "broaden", "narrow", "failed"]
    reason: str
    duration_ms: int


class SearchResponse(BaseModel):
    status: Literal["completed", "partial", "empty", "failed"]
    message: str
    cached: bool
    query_terms: list[str]
    papers: list[Paper]
    groups: list[Group]
    trace: list[TraceEntry]
