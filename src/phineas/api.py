"""HTTP adapter over Phineas application services."""

from typing import Literal
from datetime import datetime

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from fastapi.responses import JSONResponse
from starlette.requests import Request

from phineas.application import IngestionSummary
from phineas.analysis import AnalysisResult
from phineas.samples import list_sample_ids, summarize_sample
from phineas.sessions import InMemorySessionStore, SessionService, SessionStore, SessionUnavailable


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


def create_app(store: SessionStore | None = None) -> FastAPI:
    app = FastAPI(title="Phineas", version="0.1.0")
    sessions = SessionService(store if store is not None else InMemorySessionStore())

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
        sessions.purge(session_id)
        return Response(status_code=204)

    @app.get("/sessions/{session_id}/analysis", response_model=AnalysisResult)
    def session_analysis(session_id: str) -> AnalysisResult:
        return sessions.analysis(session_id)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @app.get("/samples", response_model=list[str])
    def samples() -> list[str]:
        return list(list_sample_ids())

    @app.post("/analyses/sample-summary", response_model=IngestionSummary)
    def sample_summary(request: SampleSummaryRequest, response: Response) -> IngestionSummary:
        response.headers["Cache-Control"] = "no-store"
        # Allowlist membership is checked before any processing. No uploaded
        # contents, filenames, model overrides, or arbitrary paths are accepted.
        if request.sample_id not in list_sample_ids():
            raise HTTPException(status_code=404, detail="unknown_sample")
        return summarize_sample(request.sample_id)

    return app


app = create_app()
