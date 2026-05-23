from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from .config import app_config, settings
from .jobs import ClientContext, JobManager
from .schemas import GenerationRequest, JobResponse, ProjectionRequest, PublicConfig, ShareCreateRequest, ShareResponse
from .storage import Storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S %z",
)

settings.ensure_dirs()
storage = Storage(settings)
jobs = JobManager(settings, storage)

app = FastAPI(title="ZWMP API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/config", response_model=PublicConfig)
async def public_config() -> PublicConfig:
    return PublicConfig(site=app_config.site.model_dump())


@app.post("/api/generation-jobs", response_model=JobResponse)
async def create_generation_job(request: GenerationRequest, http_request: Request, response: Response) -> JobResponse:
    device_id = http_request.cookies.get("zwmp_device_id") or str(uuid.uuid4())
    response.set_cookie(
        "zwmp_device_id",
        device_id,
        max_age=60 * 60 * 24 * 365,
        secure=False,
        httponly=False,
        samesite="lax",
    )
    client_ip = http_request.client.host if http_request.client else "unknown"
    return jobs.create_generation_job(request, ClientContext(ip=client_ip, device_id=device_id))


@app.get("/api/generation-jobs/{job_id}", response_model=JobResponse)
async def get_generation_job(job_id: str) -> JobResponse:
    job = jobs.get(job_id)
    if not job or job.type != "generation":
        raise HTTPException(status_code=404, detail="generation job not found")
    return job


@app.post("/api/projection-jobs", response_model=JobResponse)
async def create_projection_job(request: ProjectionRequest) -> JobResponse:
    return jobs.create_projection_job(request)


@app.get("/api/projection-jobs/{job_id}", response_model=JobResponse)
async def get_projection_job(job_id: str) -> JobResponse:
    job = jobs.get(job_id)
    if not job or job.type != "projection":
        raise HTTPException(status_code=404, detail="projection job not found")
    return job


@app.post("/api/jobs/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(job_id: str) -> JobResponse:
    job = jobs.cancel(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.post("/api/shares", response_model=ShareResponse)
async def create_share(request: ShareCreateRequest) -> ShareResponse:
    return storage.create_share(
        request.rule_text,
        request.projection,
        request.site_profile,
        request.runtime_notices,
        request.warnings,
    )


@app.get("/api/shares/{share_id}", response_model=ShareResponse)
async def get_share(share_id: str) -> ShareResponse:
    share = storage.get_share(share_id)
    if not share:
        raise HTTPException(status_code=404, detail="share not found")
    return share
