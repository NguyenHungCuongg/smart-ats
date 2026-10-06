import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, FastAPI
from fastapi.sse import EventSourceResponse, ServerSentEvent

router = APIRouter(prefix="/api")


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# Demo stream for #12: events must reach the client one per second, not all at the end.
@router.get("/demo/sse", response_class=EventSourceResponse)
async def demo_sse() -> AsyncIterator[ServerSentEvent]:
    for i in range(1, 6):
        yield ServerSentEvent(data={"tick": i}, event="tick", id=str(i))
        await asyncio.sleep(1)


app = FastAPI(title="Smart ATS API")
app.include_router(router)
