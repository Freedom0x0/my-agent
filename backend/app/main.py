from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.chat import create_chat_router
from .api.middleware import RequestLogMiddleware
from .api.routes import create_router
from .config import get_settings
from .logging_setup import setup_logging
from .schemas import HealthResponse


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Configured at startup rather than at import: importing this module (as the
        # tests do) must not claim the real log directory. Without it the root logger
        # has no handlers, so every INFO line is dropped by `logging.lastResort`.
        setup_logging(Path(settings.APP_DATA_DIR).resolve() / "logs")
        yield

    app = FastAPI(title="表析 Agent", version="0.1.0", lifespan=lifespan)

    origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
    # Added before CORS so CORS ends up outermost — error responses from a
    # middleware-level failure still need their CORS headers.
    app.add_middleware(RequestLogMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", mode=settings.APP_MODE)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_, exc: HTTPException):
        if isinstance(exc.detail, dict):
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"message": str(exc.detail)})

    app.include_router(create_router())
    app.include_router(create_chat_router())
    return app


app = create_app()