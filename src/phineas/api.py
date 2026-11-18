"""HTTP adapter over Phineas application services."""

from typing import Literal
from datetime import datetime
import os
from uuid import UUID

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from fastapi.responses import JSONResponse
from starlette.requests import Request

from phineas.application import IngestionSummary
from phineas.admission import DailyJobLimitExceeded, DemoAdmissionsPaused
from phineas.analysis import AnalysisResult
from phineas.bedrock import AgentCoreNarrativeProvider
from phineas.dynamodb_sessions import DynamoDBSessionStore
from phineas.dynamodb_jobs import DynamoDBJobStore
from phineas.narratives import FactCard, NarrativeProvider, NarrativeResult, build_fact_cards, generate_highlights
from phineas.questions import QuestionRequest, QuestionResponse, SUGGESTED_QUESTIONS, answer_question
from phineas.jobs import JobConflict, JobLimitExceeded, JobUnavailable, JobView, QueueUnavailable, QuestionJobService, SubmitQuestion, WorkerRetry
from phineas.sqs_jobs import SqsJobQueue
from phineas.samples import SamplePreview, list_sample_ids, preview_sample, summarize_sample
from phineas.sessions import InMemorySessionStore, SessionService, SessionStore, SessionUnavailable, SessionStoreError, SessionCapacityExceeded


class SampleSummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_id: str


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class SessionCreated(BaseModel):
    session_id: str
    created_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime


class SessionReport(BaseModel):
    analysis: AnalysisResult
    facts: tuple[FactCard, ...]


def create_app(store: SessionStore | None = None, narrative_provider: NarrativeProvider | None = None,
               job_service: QuestionJobService | None = None) -> FastAPI:
    app = FastAPI(title="Phineas", version="0.1.0")
    sessions = SessionService(store if store is not None else InMemorySessionStore())

    @app.exception_handler(DailyJobLimitExceeded)
    async def daily_limit(request: Request, error: DailyJobLimitExceeded) -> JSONResponse:
        return JSONResponse(status_code=429, content={"detail": "demo_daily_job_limit_reached"})

    @app.exception_handler(DemoAdmissionsPaused)
    async def admissions_paused(request: Request, error: DemoAdmissionsPaused) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "demo_admissions_paused"})

    @app.exception_handler(JobLimitExceeded)
    async def job_limit(request: Request, error: JobLimitExceeded) -> JSONResponse:
        return JSONResponse(status_code=429, content={"detail": "question_job_limit_reached"})

    @app.exception_handler(WorkerRetry)
    async def job_busy(request: Request, error: WorkerRetry) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "job_store_busy"})

    @app.exception_handler(JobUnavailable)
    async def job_unavailable(request: Request, error: JobUnavailable) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "job_unavailable"})

    @app.exception_handler(JobConflict)
    async def job_conflict(request: Request, error: JobConflict) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": "request_id_conflict"})

    @app.exception_handler(QueueUnavailable)
    async def queue_unavailable(request: Request, error: QueueUnavailable) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "job_queue_unavailable"})

    @app.post("/sessions/{session_id}/question-jobs", response_model=JobView, status_code=202)
    def submit_question_job(session_id: str, request: SubmitQuestion) -> JobView:
        if job_service is None:
            raise HTTPException(status_code=503, detail="async_questions_not_configured")
        return job_service.submit(session_id, request)

    @app.get("/sessions/{session_id}/jobs/{job_id}", response_model=JobView)
    def get_question_job(session_id: str, job_id: UUID) -> JobView:
        if job_service is None:
            raise HTTPException(status_code=503, detail="async_questions_not_configured")
        return job_service.poll(session_id, job_id)

    @app.exception_handler(SessionStoreError)
    async def store_unavailable(request: Request, error: SessionStoreError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "session_store_unavailable"})

    @app.exception_handler(SessionCapacityExceeded)
    async def capacity_exceeded(request: Request, error: SessionCapacityExceeded) -> JSONResponse:
        return JSONResponse(status_code=413, content={"detail": "statement_capacity_exceeded"})

    @app.get("/questions/suggestions", response_model=list[str])
    def suggested_questions() -> list[str]:
        return list(SUGGESTED_QUESTIONS)

    @app.post("/sessions/{session_id}/questions", response_model=QuestionResponse)
    def question(session_id: str, request: QuestionRequest) -> QuestionResponse:
        if job_service is not None:
            raise HTTPException(status_code=409, detail="async_questions_required")
        result = answer_question(sessions.analysis(session_id), request.question, narrative_provider)
        sessions.summary(session_id)
        return result

    @app.post("/sessions/{session_id}/narrative", response_model=NarrativeResult)
    def narrative(session_id: str) -> NarrativeResult:
        if job_service is not None:
            raise HTTPException(status_code=409, detail="async_questions_required")
        analysis = sessions.analysis(session_id)
        result = generate_highlights(analysis, narrative_provider)
        # Do not return financial results if the session was purged or expired
        # while a remote invocation was in flight.
        sessions.summary(session_id)
        return result

    @app.middleware("http")
    async def prevent_caching(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(SessionUnavailable)
    async def unavailable(request: Request, error: SessionUnavailable) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "session_unavailable"})

    @app.post("/sessions", response_model=SessionCreated, status_code=201)
    def create_session(request: SampleSummaryRequest) -> SessionCreated:
        if request.sample_id not in list_sample_ids():
            raise HTTPException(status_code=404, detail="unknown_sample")
        record = sessions.create(request.sample_id)
        return SessionCreated(session_id=record.session_id, created_at=record.created_at,
            idle_expires_at=record.idle_expires_at, absolute_expires_at=record.absolute_expires_at)

    @app.get("/sessions/{session_id}/summary", response_model=IngestionSummary)
    def session_summary(session_id: str) -> IngestionSummary:
        return sessions.summary(session_id)

    @app.delete("/sessions/{session_id}", status_code=204)
    def purge_session(session_id: str) -> Response:
        if job_service is not None:
            job_service.purge(session_id)
        else:
            sessions.purge(session_id)
        return Response(status_code=204)

    @app.get("/sessions/{session_id}/analysis", response_model=AnalysisResult)
    def session_analysis(session_id: str) -> AnalysisResult:
        return sessions.analysis(session_id)

    @app.get("/sessions/{session_id}/report", response_model=SessionReport)
    def session_report(session_id: str) -> SessionReport:
        analysis = sessions.analysis(session_id)
        return SessionReport(analysis=analysis, facts=build_fact_cards(analysis))

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @app.get("/samples", response_model=list[str])
    def samples() -> list[str]:
        return list(list_sample_ids())

    @app.get("/samples/{sample_id}/preview", response_model=SamplePreview)
    def sample_preview(sample_id: str) -> SamplePreview:
        if sample_id not in list_sample_ids():
            raise HTTPException(status_code=404, detail="unknown_sample")
        return preview_sample(sample_id)

    @app.post("/analyses/sample-summary", response_model=IngestionSummary)
    def sample_summary(request: SampleSummaryRequest, response: Response) -> IngestionSummary:
        response.headers["Cache-Control"] = "no-store"
        # Allowlist membership is checked before any processing. No uploaded
        # contents, filenames, model overrides, or arbitrary paths are accepted.
        if request.sample_id not in list_sample_ids():
            raise HTTPException(status_code=404, detail="unknown_sample")
        return summarize_sample(request.sample_id)

    return app


def create_configured_app() -> FastAPI:
    arn = os.environ.get("PHINEAS_HARNESS_ARN")
    provider = AgentCoreNarrativeProvider(arn, os.environ.get("AWS_REGION", "us-east-2")) if arn else None
    table_name = os.environ.get("PHINEAS_SESSIONS_TABLE")
    store = DynamoDBSessionStore(table_name, os.environ.get("AWS_REGION", "us-east-2")) if table_name else None
    queue_url = os.environ.get("PHINEAS_QUESTION_QUEUE_URL")
    job_service = None
    if queue_url:
        if store is None:
            raise ValueError("async_questions_require_dynamodb")
        job_service = QuestionJobService(store, DynamoDBJobStore(store),
            SqsJobQueue(queue_url, os.environ.get("AWS_REGION", "us-east-2")))
    return create_app(store=store, narrative_provider=provider, job_service=job_service)


app = create_configured_app()
