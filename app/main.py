import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pymongo.errors import PyMongoError

from app.config import get_settings
from app.db import mongodb
from app.routes import dashboard, pages, practice, sessions
from app.services.ai.base import AIError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app")
ROOT = Path(__file__).resolve().parent.parent

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
}


async def _ensure_indexes(db) -> None:
    try:
        await mongodb.ensure_indexes(db)
    except PyMongoError as exc:
        logger.error("MongoDB unavailable at startup: %s", type(exc).__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.secret_key == "dev-only-change-me":
        logger.warning("SECRET_KEY is not set; using an insecure development default.")
    owns_client = not hasattr(app.state, "db")
    if owns_client:
        app.state.client, app.state.db = mongodb.connect(settings)
        # Never block startup on MongoDB: the port must open quickly or the host's deploy times out.
        index_task = asyncio.create_task(_ensure_indexes(app.state.db))
    yield
    if owns_client:
        index_task.cancel()
        await app.state.client.close()


def create_app() -> FastAPI:
    app = FastAPI(title="English Practice Assistant", lifespan=lifespan)
    app.state.byok = {}
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    for module in (pages, sessions, practice, dashboard):
        app.include_router(module.router)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    @app.exception_handler(AIError)
    async def ai_error(request: Request, exc: AIError):
        logger.warning("AI error on %s: %s", request.url.path, type(exc).__name__)
        return JSONResponse({"detail": exc.message}, status_code=exc.status_code)

    @app.exception_handler(PyMongoError)
    async def db_error(request: Request, exc: PyMongoError):
        logger.error("Database error on %s: %s", request.url.path, type(exc).__name__)
        return JSONResponse(
            {"detail": "Your learning history is temporarily unavailable. Please try again."},
            status_code=503,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        message = exc.errors()[0].get("msg", "Invalid request.").removeprefix("Value error, ")
        if exc.errors()[0].get("type") == "string_too_long":
            message = "That message is too long. Please keep it under 2,000 characters."
        logger.info("Validation failed on %s", request.url.path)
        return JSONResponse({"detail": message}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s", request.url.path)
        return JSONResponse(
            {"detail": "Something went wrong on our side. Please try again."}, status_code=500
        )

    return app


app = create_app()
