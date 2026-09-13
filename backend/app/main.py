from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.routes import create_router
from .config import get_settings
from .schemas import HealthResponse


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="表析 Agent", version="0.1.0")

    origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
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
    return app


app = create_app()