"""Requests and results for job discovery."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.models.detailed import ResumeDraft


class JobSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft: ResumeDraft
    query: str = Field(default="", max_length=120)
    location: str = Field(default="Sorocaba, SP", max_length=120)
    work_mode: Literal["all", "remote", "local"] = "all"


class JobListing(BaseModel):
    source: str
    title: str
    company: str
    location: str
    remote: bool
    url: str
    description: str
    published_at: str = ""
    match_score: int = Field(ge=0, le=100)
    matched_terms: list[str]


class JobSearchResult(BaseModel):
    jobs: list[JobListing]
    query_used: str
    sources: list[str]
    notices: list[str]
