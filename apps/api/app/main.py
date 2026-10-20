from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse

from app import auth, events, jobs, members, readiness, scoring_runs, uploads

router = APIRouter(prefix="/api")


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# Unlike /health, this reaches out to every dependency: call it on demand, never from a poller.
@router.get("/ready")
async def ready() -> JSONResponse:
    failed = await readiness.failed_dependencies()
    if failed:
        return JSONResponse({"status": "unavailable", "failed": failed}, status_code=503)
    return JSONResponse({"status": "ok"})


app = FastAPI(title="Smart ATS API")
app.include_router(router)
app.include_router(auth.router)
app.include_router(events.router)
app.include_router(jobs.router)
app.include_router(uploads.router)
app.include_router(scoring_runs.router)
app.include_router(members.router)
