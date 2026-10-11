"""Pydantic request and response models, field for field from specs/api-contract-spec.md."""

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator

Category = Literal[
    "cs.AI", "cs.LG", "cs.CL", "cs.CV", "cs.RO", "cs.IR",
    "stat.ML", "quant-ph", "physics.comp-ph", "math.OC", "eess.SP", "q-bio.QM",
]


class SearchRequest(BaseModel):
    topic: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=100)]
    category: Category | None = None
    from_year: int | None = None
    max_papers: int = Field(default=20, ge=5, le=30)

    @field_validator("from_year")
    @classmethod
    def from_year_in_range(cls, value: int | None) -> int | None:
        current_year = datetime.now(timezone.utc).year
        if value is not None and not 2000 <= value <= current_year:
            raise ValueError(f"from_year must be from 2000 to {current_year}")
        return value


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
