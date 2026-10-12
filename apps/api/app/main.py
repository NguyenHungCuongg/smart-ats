import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app import auth, readiness

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


# Demo stream for #12: events must reach the client one per second, not all at the end.
@router.get("/demo/sse", response_class=EventSourceResponse)
async def demo_sse() -> AsyncIterator[ServerSentEvent]:
    for i in range(1, 6):
        yield ServerSentEvent(data={"tick": i}, event="tick", id=str(i))
        await asyncio.sleep(1)


app = FastAPI(title="Smart ATS API")
app.include_router(router)
app.include_router(auth.router)
