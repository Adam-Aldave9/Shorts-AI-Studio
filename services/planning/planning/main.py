"""FastAPI surface for the planning tier (spec §4, §9.2 Submit screen).

Accepts a brief, runs the script -> breakdown -> prompts -> validator chain, and
persists the validated package into the shared store the scheduler already serves —
so its existing GET/PUT/approve endpoints see the package the instant planning
finishes (the package is the API; no bespoke planning->scheduler handoff). The
Pydantic-derived JSON schema is served so the frontend's Monaco editor can validate
edits at the checkpoint.
"""

from __future__ import annotations

import os

import state
from auth import auth_router, current_user_id, install_auth
from auth.config import AUTH_ALLOWED_ORIGINS
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from schema import ProductionPackage

from planning.graph import run_planning
from planning.validator import ValidationReport, validate_package

app = FastAPI(title="AI Film Pipeline — Planning Service", version="1.0.0")

# Auth: same shared layer as the scheduler. ``/schema`` is public (non-sensitive
# static JSON schema for the Monaco editor); briefs require a session so the resulting
# package can be stamped with an owner. CORS is added last so it stays outermost.
app.include_router(auth_router)
install_auth(
    app,
    public_paths={"/health", "/schema", "/auth/login", "/auth/register", "/auth/csrf"},
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=AUTH_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Brief(BaseModel):
    premise: str
    target_duration_s: float = 90
    style: str | None = None
    narration_voice_id: str | None = None


class BriefAccepted(BaseModel):
    """The planning result handed back to the Submit screen, which routes the
    browser to ``/checkpoint/{project_id}`` (served by the scheduler)."""

    project_id: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mock": os.environ.get("MOCK", "false")}


@app.get("/schema")
def package_schema() -> dict:
    """JSON schema for the production package — consumed by Monaco at the checkpoint."""
    return ProductionPackage.model_json_schema()


@app.post("/briefs", status_code=201, response_model=BriefAccepted)
async def create_brief(
    brief: Brief, user_id: str = Depends(current_user_id)
) -> BriefAccepted:
    package = await run_planning(brief.model_dump())
    report: ValidationReport = validate_package(package)
    if not report.ok:
        raise HTTPException(status_code=422, detail=report.errors)
    # Persist into the store the scheduler serves, stamping the authenticated caller
    # as owner — this is the brief->package handoff where identity enters the run, so
    # the scheduler's ownership checks (and scoped History) apply from creation.
    await state.save_package(package, owner_id=user_id)
    return BriefAccepted(project_id=package.project_id)
