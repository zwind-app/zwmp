from __future__ import annotations

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .config import settings
from .jobs import JobManager
from .schemas import GenerationRequest, JobResponse, ProjectionRequest
from .storage import Storage

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


@app.post("/api/generation-jobs", response_model=JobResponse)
async def create_generation_job(request: GenerationRequest) -> JobResponse:
    return jobs.create_generation_job(request)


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


@app.get("/api/rules")
async def list_rules() -> dict:
    return {"rules": [rule.model_dump() for rule in storage.list_rules()]}


@app.get("/api/rules/{rule_id}")
async def get_rule(rule_id: str) -> dict:
    text = storage.get_rule_text(rule_id)
    if text is None:
        raise HTTPException(status_code=404, detail="rule not found")
    return {"id": rule_id, "rule_text": text}


@app.get("/api/proxy/{session_id}/{media_id}")
async def proxy_media(session_id: str, media_id: str, request: Request) -> StreamingResponse:
    target = jobs.proxy_target(session_id, media_id)
    if not target:
        raise HTTPException(status_code=404, detail="proxy target not found or expired")
    headers = {}
    if range_header := request.headers.get("range"):
        headers["Range"] = range_header
    for key in ("Referer", "Origin", "User-Agent", "Cookie"):
        if value := target.get(key):
            headers[key] = value
    client = httpx.AsyncClient(timeout=None, follow_redirects=True)
    upstream = await client.stream("GET", target["url"], headers=headers).__aenter__()

    async def body():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    response_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() in {"content-type", "content-length", "content-range", "accept-ranges"}
    }
    return StreamingResponse(body(), status_code=upstream.status_code, headers=response_headers)

