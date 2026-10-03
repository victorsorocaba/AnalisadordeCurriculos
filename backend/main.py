"""FastAPI application and routing for the resume-analyzer-latex backend.

This module defines the FastAPI ``app`` instance and registers the single
asynchronous ``POST /api/analyze`` route (Requirements 1.1, 10.1). The route
handler enforces a precedence-ordered validation pipeline and then orchestrates
the call sequence ``validate -> extract_text -> analyze_resume -> return`` so
that invalid requests fail fast and cheaply before any extraction or paid AI
call occurs.

Validation pipeline (executed in this exact order to honor Requirement 1.8):

    1. Missing resume                       -> 422 (Req 1.5, 1.8)
    2. Missing/whitespace-only job desc.    -> 422 (Req 1.6)
    3. Job description > 20,000 chars       -> 422 (Req 1.7)
    4. Unsupported content type             -> 415 (Req 2.2)
    5. File > 10 MB                         -> 413 (Req 2.4)
    6. Empty file (0 bytes)                 -> 422 (Req 2.3)
    7. Extraction/decode error              -> 422 (Req 3.5, 3.6)
    8. API key missing                      -> 500 (Req 4.5)
    9. AI error/timeout                     -> 502 (Req 4.6)
   10. AI output fails validation           -> 502 (Req 5.5)

The optional access code and per-process rate limits protect paid endpoints in
local operation. Public deployment requires persistent shared rate limiting.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from starlette.concurrency import run_in_threadpool

from backend.models.schemas import AnalysisResult
from backend.storage import router as storage_router
from backend.accounts import router as account_router
from backend.models.detailed import DetailedAnalysis, RenderedResume, ResumeDraft, TailorRequest
from backend.models.jobs import JobSearchRequest, JobSearchResult
from backend.services.detailed_service import analyze_detailed
from backend.services.resume_renderer import RenderError, render_resume
from backend.services.job_search import search_jobs
from backend.services.certifications import CATALOG as CERTIFICATION_CATALOG, recommend_certifications
from backend.services.application_materials import MaterialsRequest, MaterialsResult, generate_materials
from backend.services.job_import import ImportRequest, import_job
from backend.services.ai_service import (
    AICallError,
    AIKeyMissingError,
    AIValidationError,
    analyze_resume,
)
from backend.services.text_extractor import ExtractionError, extract_text

# Load environment variables (e.g. AI_PROVIDER, OPENAI_API_KEY) at import time so
# the AI service can read its configuration from the environment (Requirement 4.3).
load_dotenv()

# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------

#: Maximum allowed job description length in characters (Requirements 1.2, 1.7).
MAX_JOB_DESCRIPTION_CHARS = 20_000
MAX_PROJECTS_CHARS = 20_000

#: Maximum allowed resume file size in bytes: 10 megabytes (Requirement 2.4).
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024

#: Content types accepted for the uploaded resume document (Requirements 2.1, 2.2).
SUPPORTED_CONTENT_TYPES = ("application/pdf", "text/plain")


app = FastAPI(title="Resume Analyzer + LaTeX Generator")
app.include_router(storage_router)
app.include_router(account_router)
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")
_rate_lock = threading.Lock()
_rate_events: dict[tuple[str, str], list[float]] = {}


@app.middleware("http")
async def protect_paid_endpoints(request: Request, call_next):
    if request.method == "POST" and request.url.path == "/api/jobs/import":
        key = (request.client.host if request.client else "unknown", "import")
        now = time.monotonic()
        with _rate_lock:
            recent = [stamp for stamp in _rate_events.get(key, []) if now - stamp < 3600]
            if len(recent) >= 30:
                return JSONResponse({"detail": "Limite de importações atingido. Tente mais tarde."}, status_code=429)
            recent.append(now)
            _rate_events[key] = recent
    if request.method == "POST" and request.url.path in {"/api/account/login", "/api/account/register"}:
        key = (request.client.host if request.client else "unknown", "account")
        now = time.monotonic()
        with _rate_lock:
            recent = [stamp for stamp in _rate_events.get(key, []) if now - stamp < 900]
            if len(recent) >= 10:
                return JSONResponse({"detail": "Muitas tentativas de acesso. Aguarde 15 minutos."}, status_code=429)
            recent.append(now)
            _rate_events[key] = recent
    if request.method == "POST" and request.url.path in {"/api/analyze", "/api/analyze/detailed", "/api/tailor", "/api/render", "/api/jobs/search", "/api/jobs/import", "/api/certifications/recommend", "/api/applications/materials"}:
        access_token = os.getenv("APP_ACCESS_TOKEN", "").strip()
        if access_token:
            supplied = request.headers.get("X-Access-Token", "")
            if not secrets.compare_digest(supplied, access_token):
                return JSONResponse({"detail": "Código de acesso inválido ou ausente."}, status_code=401)
            kind = "certs" if request.url.path == "/api/certifications/recommend" else "jobs" if request.url.path in {"/api/jobs/search", "/api/jobs/import"} else "render" if request.url.path == "/api/render" else "analysis"
            limit = {"analysis": 10, "render": 60, "jobs": 30, "certs": 30}[kind]
            key = (request.client.host if request.client else "unknown", kind)
            now = time.monotonic()
            with _rate_lock:
                recent = [stamp for stamp in _rate_events.get(key, []) if now - stamp < 3600]
                if len(recent) >= limit:
                    return JSONResponse({"detail": "Limite de uso atingido. Tente novamente em até uma hora."}, status_code=429)
                recent.append(now)
                _rate_events[key] = recent
    return await call_next(request)


@app.get("/api/config", include_in_schema=False)
async def public_config() -> dict[str, bool]:
    return {"auth_required": bool(os.getenv("APP_ACCESS_TOKEN", "").strip())}


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/rotas-estudo", include_in_schema=False)
async def study_roadmaps() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "roadmaps.html")


@app.get("/rotas-estudo/{roadmap_id}", include_in_schema=False)
async def study_roadmap_detail(roadmap_id: str) -> FileResponse:
    from backend.storage import _valid_topics

    if roadmap_id not in _valid_topics():
        raise HTTPException(404, "Rota de estudo não encontrada.")
    return FileResponse(FRONTEND_DIR / "roadmap-detail.html")


@app.get("/certificacoes", include_in_schema=False)
async def certifications_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "certifications.html")


@app.get("/candidaturas", include_in_schema=False)
async def applications_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "applications.html")


@app.get("/conta", include_in_schema=False)
async def account_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "account.html")


@app.post("/api/certifications/recommend")
async def certification_recommendations(
    resume: UploadFile | None = File(default=None),
    profile_text: str = Form(default=""),
    goal: str = Form(default=""),
) -> dict:
    if len(profile_text) > 12_000 or len(goal) > 200:
        raise HTTPException(422, "O perfil ou objetivo é longo demais.")
    source = "Perfil do currículo"
    if resume is not None:
        if resume.content_type not in SUPPORTED_CONTENT_TYPES:
            raise HTTPException(415, "Envie um currículo em PDF ou TXT.")
        data = await resume.read(MAX_FILE_SIZE_BYTES + 1)
        if len(data) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(413, "O currículo deve ter no máximo 10 MB.")
        if not data:
            raise HTTPException(422, "O currículo está vazio.")
        try:
            extracted = await run_in_threadpool(extract_text, data, resume.content_type)
        except ExtractionError as exc:
            raise HTTPException(422, "Não foi possível ler o currículo.") from exc
        if not extracted:
            raise HTTPException(422, "O currículo não contém texto legível.")
        profile_text = f"{profile_text}\n{extracted}"
        source = "Currículo enviado"
    elif not profile_text.strip():
        source = "Objetivo profissional"
    if not profile_text.strip() and not goal.strip():
        raise HTTPException(422, "Envie um currículo ou informe seu objetivo profissional.")
    recommendations = recommend_certifications(profile_text, goal)
    return {
        "source": source,
        "catalog_size": len(CERTIFICATION_CATALOG),
        "recommendations": recommendations,
    }


@app.post("/api/analyze", response_model=AnalysisResult)
async def analyze(
    resume: UploadFile | None = File(default=None),
    job_description: str | None = Form(default=None),
    projects: str | None = Form(default=None),
) -> AnalysisResult:
    """Analyze a resume against a job description and return a structured result.

    Accepts a multipart request containing exactly one uploaded resume file part
    and one ``job_description`` text field (Requirements 1.2, 1.3). The request
    is validated in precedence order (Requirement 1.8); on success the resume
    text is extracted and sent to the AI service, and the validated
    :class:`AnalysisResult` is returned with HTTP 200 (Requirement 1.4).

    Raises:
        HTTPException: With the appropriate status code for each failure mode,
            carrying a descriptive ``detail`` message.
    """
    # Step 1: Missing resume file part -> 422 (Requirements 1.5, 1.8).
    # Checked first so it takes precedence over an empty job description.
    if resume is None:
        raise HTTPException(
            status_code=422,
            detail="A resume file is required but was not provided.",
        )

    # Step 2: Missing or whitespace-only job description -> 422 (Requirement 1.6).
    if job_description is None or job_description.strip() == "":
        raise HTTPException(
            status_code=422,
            detail="A job description is required but was empty or missing.",
        )

    # Step 3: Job description exceeds the maximum length -> 422 (Requirement 1.7).
    if len(job_description) > MAX_JOB_DESCRIPTION_CHARS:
        raise HTTPException(
            status_code=422,
            detail=(
                "The job description is too long: it must be at most "
                f"{MAX_JOB_DESCRIPTION_CHARS} characters, but it has "
                f"{len(job_description)} characters."
            ),
        )

    if projects is not None and len(projects) > MAX_PROJECTS_CHARS:
        raise HTTPException(status_code=422, detail="The projects field is too long.")

    # Step 4: Unsupported content type -> 415 (Requirement 2.2).
    # Validated before reading the bytes to honor the precedence order.
    if resume.content_type not in SUPPORTED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=(
                "Unsupported resume content type "
                f"{resume.content_type!r}. Supported types are: "
                f"{', '.join(SUPPORTED_CONTENT_TYPES)}."
            ),
        )

    # Read the uploaded file bytes exactly once; size and emptiness checks below
    # operate on these bytes.
    data = await resume.read(MAX_FILE_SIZE_BYTES + 1)

    # Step 5: File exceeds the maximum size -> 413 (Requirement 2.4).
    if len(data) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="The resume file is too large: the maximum allowed size is 10 MB.",
        )

    # Step 6: Empty file (zero readable bytes) -> 422 (Requirement 2.3).
    if len(data) == 0:
        raise HTTPException(
            status_code=422,
            detail="The resume file is empty: it contains zero readable bytes.",
        )

    # Step 7: Extraction/decode error -> 422 (Requirements 3.5, 3.6).
    # On failure the document is never forwarded to the AI service.
    try:
        resume_text = extract_text(data, resume.content_type)
    except ExtractionError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Failed to extract text from the resume: {exc}",
        ) from exc

    if not resume_text:
        raise HTTPException(
            status_code=422,
            detail="The resume contains no readable text.",
        )

    # Steps 8-10: orchestrate the AI call, mapping each typed AI service error to
    # its HTTP status code. AIKeyMissingError (500) is caught before the 502
    # errors because it is a more specific configuration failure.
    try:
        return await analyze_resume(resume_text, job_description, projects or "")
    except AIKeyMissingError as exc:
        # Step 8: API key missing -> 500 (Requirement 4.5).
        raise HTTPException(
            status_code=500,
            detail="The AI provider API key is not configured.",
        ) from exc
    except AICallError as exc:
        # Step 9: AI error or timeout -> 502 (Requirement 4.6).
        raise HTTPException(
            status_code=502,
            detail=f"The AI model call did not complete successfully: {exc}",
        ) from exc
    except AIValidationError as exc:
        # Step 10: AI output fails validation -> 502 (Requirement 5.5).
        raise HTTPException(
            status_code=502,
            detail=f"The AI model returned output that failed validation: {exc}",
        ) from exc


@app.post("/api/analyze/detailed", response_model=DetailedAnalysis)
async def analyze_detailed_endpoint(
    resume: UploadFile | None = File(default=None),
    job_description: str | None = Form(default=None),
    projects: str | None = Form(default=None),
) -> DetailedAnalysis:
    if resume is None:
        raise HTTPException(422, "Envie um currículo em PDF ou TXT.")
    if not job_description or not job_description.strip():
        raise HTTPException(422, "Informe a descrição da vaga.")
    if len(job_description) > MAX_JOB_DESCRIPTION_CHARS or len(projects or "") > MAX_PROJECTS_CHARS:
        raise HTTPException(422, "O texto informado ultrapassa 20.000 caracteres.")
    if resume.content_type not in SUPPORTED_CONTENT_TYPES:
        raise HTTPException(415, "O currículo deve ser PDF ou TXT.")
    data = await resume.read(MAX_FILE_SIZE_BYTES + 1)
    if len(data) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(413, "O currículo deve ter no máximo 10 MB.")
    if not data:
        raise HTTPException(422, "O currículo está vazio.")
    try:
        resume_text = extract_text(data, resume.content_type)
    except ExtractionError as exc:
        raise HTTPException(422, "Não foi possível ler o currículo.") from exc
    if not resume_text:
        raise HTTPException(422, "O currículo não contém texto legível.")
    try:
        return await analyze_detailed(resume_text, job_description, projects or "")
    except AIKeyMissingError as exc:
        raise HTTPException(500, "Configure a chave de API do provedor de IA.") from exc
    except AICallError as exc:
        raise HTTPException(502, "O provedor de IA não concluiu a análise.") from exc
    except AIValidationError as exc:
        raise HTTPException(502, "A resposta da IA não passou na validação.") from exc


@app.post("/api/render", response_model=RenderedResume)
async def render_endpoint(draft: ResumeDraft) -> RenderedResume:
    try:
        return await run_in_threadpool(render_resume, draft)
    except RenderError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/tailor", response_model=DetailedAnalysis)
async def tailor_endpoint(request: TailorRequest) -> DetailedAnalysis:
    if not request.job_description.strip():
        raise HTTPException(422, "Informe a descrição da vaga.")
    draft = request.draft
    if not any((draft.summary.strip(), draft.experience.strip(), draft.projects.strip(), draft.skills.strip())):
        raise HTTPException(422, "Preencha o currículo antes de prepará-lo para a vaga.")
    source = "\n".join(
        f"{label}: {getattr(draft, field)}"
        for field, label in (
            ("name", "Nome"), ("contact", "Contato"), ("headline", "Título"),
            ("summary", "Resumo"), ("experience", "Experiência"),
            ("education", "Formação"), ("skills", "Habilidades"),
            ("projects", "Projetos"),
        )
    )
    try:
        result = await analyze_detailed(source, request.job_description, tailor_mode=True)
    except AIKeyMissingError as exc:
        raise HTTPException(500, "Configure a chave de API do provedor de IA.") from exc
    except AICallError as exc:
        raise HTTPException(502, "O provedor de IA não concluiu a preparação.") from exc
    except AIValidationError as exc:
        raise HTTPException(502, "A resposta da IA não passou na validação.") from exc
    for field in ("name", "contact", "education", "skills"):
        setattr(result.draft, field, getattr(draft, field))
    for field in ("experience", "projects"):
        if not getattr(draft, field).strip():
            setattr(result.draft, field, "")
    return result


@app.post("/api/jobs/search", response_model=JobSearchResult)
async def jobs_search_endpoint(request: JobSearchRequest) -> JobSearchResult:
    return await search_jobs(request)


@app.post("/api/jobs/import")
async def jobs_import_endpoint(request: ImportRequest) -> dict:
    return await import_job(request.url)


@app.post("/api/applications/materials", response_model=MaterialsResult)
async def application_materials_endpoint(request: MaterialsRequest) -> MaterialsResult:
    try:
        return await generate_materials(request)
    except AIKeyMissingError as exc:
        raise HTTPException(500, "Configure a chave de API do provedor de IA.") from exc
    except AICallError as exc:
        raise HTTPException(502, "O provedor de IA não concluiu a preparação.") from exc
    except AIValidationError as exc:
        raise HTTPException(502, "A resposta da IA não passou na validação.") from exc
