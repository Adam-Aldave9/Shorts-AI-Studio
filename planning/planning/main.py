"""FastAPI surface for the planning tier (spec §4, §9.2 Submit screen).

Accepts a brief, runs the script -> breakdown -> prompts -> validator chain, and
persists the validated package. The Pydantic-derived JSON schema is served so the
frontend's Monaco editor can validate edits at the checkpoint.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from schema import ProductionPackage

from planning.graph import run_planning
from planning.validator import ValidationReport, validate_package

app = FastAPI(title="AI Film Pipeline — Planning Service", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Brief(BaseModel):
    premise: str
    target_duration_s: float = 90
    style: str | None = None
    narration_voice_id: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mock": os.environ.get("MOCK", "false")}


@app.get("/schema")
def package_schema() -> dict:
    """JSON schema for the production package — consumed by Monaco at the checkpoint."""
    return ProductionPackage.model_json_schema()


@app.post("/briefs", response_model=ProductionPackage)
async def create_brief(brief: Brief) -> ProductionPackage:
    package = await run_planning(brief.model_dump())
    report: ValidationReport = validate_package(package)
    if not report.ok:
        raise HTTPException(status_code=422, detail=report.errors)
    # TODO(week3): persist to Postgres keyed by project_id.
    return package
