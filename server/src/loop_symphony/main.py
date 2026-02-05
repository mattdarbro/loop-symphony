"""FastAPI application entry point for Loop Symphony."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from loop_symphony import __version__
from loop_symphony.api.routes import router
from loop_symphony.config import get_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info(f"Starting Loop Symphony Server v{__version__}")
    settings = get_settings()
    logger.info(f"Debug mode: {settings.debug}")
    yield
    # Shutdown
    logger.info("Shutting down Loop Symphony Server")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Loop Symphony",
        description="Autonomous cognitive loop orchestration server",
        version=__version__,
        lifespan=lifespan,
        debug=settings.debug,
    )

    # CORS middleware for iOS app
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routes
    app.include_router(router)

    return app


# Create app instance for uvicorn
app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "loop_symphony.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
