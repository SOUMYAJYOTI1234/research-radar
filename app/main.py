"""The FastAPI app: health check, the search API with its inbound limit, and the static page."""

import logging
import sys
import time
from collections import deque
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.arxiv_client import ArxivClient
from app.cache import SEARCH_CACHE, TTLCache, cached_search
from app.models import SearchRequest, SearchResponse
from app.topic import InvalidTopic, normalise

STATIC_DIR = Path(__file__).parent / "static"
SEARCHES_PER_MINUTE = 10
TOO_MANY_SEARCHES = "Too many searches. Please wait a minute."


class ClientAddressFilter(logging.Filter):
    """Replace the client address in uvicorn access log lines with '-'."""

    def filter(self, record: logging.LogRecord) -> bool:
        # uvicorn.access args: (client_addr, method, full_path, http_version, status_code)
        if isinstance(record.args, tuple) and len(record.args) == 5:
            record.args = ("-", *record.args[1:])
        return True


def configure_logging() -> None:
    """Send the app's INFO lines (one per arXiv round) to standard output, and keep IPs out of logs."""
    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.INFO)
    if not app_logger.handlers:
        # sys.__stdout__ rather than sys.stdout, so the handler never holds a stream that is later replaced.
        handler = logging.StreamHandler(sys.__stdout__)
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
        app_logger.addHandler(handler)
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, ClientAddressFilter) for f in access_logger.filters):
        access_logger.addFilter(ClientAddressFilter())


class InboundLimiter:
    """At most `limit` searches per client in any `window` seconds. Rejected requests are not counted."""

    def __init__(
        self,
        limit: int = SEARCHES_PER_MINUTE,
        window: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.limit = limit
        self.window = window
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def allow(self, client: str) -> bool:
        now = self._clock()
        # Forget clients with no counted search inside the window, so memory stays small.
        for key in [key for key, hits in self._hits.items() if now - hits[-1] >= self.window]:
            del self._hits[key]
        hits = self._hits.get(client, deque())
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        self._hits[client] = hits
        return True


def client_key(request: Request) -> str:
    """The first X-Forwarded-For address, else the socket address. Never logged."""
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else "unknown"


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def create_app(
    arxiv_client: ArxivClient | None = None,
    today: Callable[[], date] = utc_today,
    inbound_limiter: InboundLimiter | None = None,
    cache: TTLCache | None = None,
) -> FastAPI:
    """Build the app. Tests pass their own arXiv client, clock, limiter and cache."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.arxiv_client is not None:
            yield
            return
        # The real client: one connection pool for the process, using the shared 3-second limiter.
        async with httpx.AsyncClient() as http:
            app.state.arxiv_client = ArxivClient(http)
            yield

    app = FastAPI(title="Research Radar", lifespan=lifespan)
    app.state.arxiv_client = arxiv_client
    app.state.today = today
    app.state.inbound_limiter = InboundLimiter() if inbound_limiter is None else inbound_limiter
    app.state.cache = SEARCH_CACHE if cache is None else cache
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.middleware("http")
    async def limit_searches(request: Request, call_next):
        # Runs before the body is read or validated, so every POST /api/search counts.
        if request.method == "POST" and request.url.path == "/api/search":
            if not request.app.state.inbound_limiter.allow(client_key(request)):
                return JSONResponse(status_code=429, content={"detail": TOO_MANY_SEARCHES})
        return await call_next(request)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/search", response_model=SearchResponse)
    async def search(body: SearchRequest, request: Request):
        try:
            terms = normalise(body.topic)
        except InvalidTopic as exc:
            return JSONResponse(status_code=422, content={"detail": exc.message})
        state = request.app.state
        return await cached_search(
            terms, body.category, body.from_year, body.max_papers, state.arxiv_client, state.today(), state.cache
        )

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


configure_logging()
app = create_app()
