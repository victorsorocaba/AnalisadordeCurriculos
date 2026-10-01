"""Structured analysis and editable resume data for the modern interface."""

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(StrictModel):
    requirement: str = Field(min_length=1, max_length=300)
    excerpt: str = Field(min_length=1, max_length=300)


class ResumeDraft(StrictModel):
    name: str = Field(max_length=200)
    contact: str = Field(max_length=500)
    headline: str = Field(max_length=300)
    summary: str = Field(max_length=3000)
    experience: str = Field(max_length=10000)
    education: str = Field(max_length=5000)
    skills: str = Field(max_length=5000)
    projects: str = Field(max_length=5000)


class TailorRequest(StrictModel):
    draft: ResumeDraft
    job_description: str = Field(max_length=20000)


class DetailedAnalysis(StrictModel):
    percentage: int = Field(ge=0, le=100, strict=True)
    improvements: list[str] = Field(max_length=15)
    matches: list[Evidence] = Field(max_length=15)
    gaps: list[str] = Field(max_length=15)
    draft: ResumeDraft


class RenderedResume(StrictModel):
    latex_code: str
    pdf_base64: str
    preview_pages: list[str]
