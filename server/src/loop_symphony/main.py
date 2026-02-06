"""FastAPI application entry point for Loop Symphony."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from loop_symphony import __version__
from loop_symphony.api.routes import (
    router,
    get_heartbeat_worker,
    get_conductor,
    get_db_client,
)
from loop_symphony.config import get_settings
from loop_symphony.models.health import HealthStatus, SystemHealth

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Background task handle
_autonomic_task: asyncio.Task | None = None

# Global system health state (for autonomic monitoring)
_system_health: SystemHealth | None = None
_start_time: float | None = None


def get_system_health() -> SystemHealth:
    """Get the current system health state."""
    global _system_health
    if _system_health is None:
        _system_health = SystemHealth()
    return _system_health


async def autonomic_loop():
    """Background autonomic process loop.

    Runs periodic tasks:
    - Heartbeat tick (processes due heartbeats)
    - Health checks (monitors system health)
    - Database connectivity monitoring

    Implements "pain response" - only surfaces critical errors after
    repeated failures to avoid unnecessary alerts.
    """
    global _start_time
    _start_time = time.time()

    settings = get_settings()
    health = get_system_health()

    logger.info(
        f"Autonomic layer started: heartbeat every {settings.autonomic_heartbeat_interval}s, "
        f"health check every {settings.autonomic_health_interval}s"
    )

    heartbeat_counter = 0
    health_counter = 0

    while True:
        try:
            await asyncio.sleep(1)  # Check every second
            heartbeat_counter += 1
            health_counter += 1

            # Update uptime
            health.uptime_seconds = time.time() - _start_time

            # Run heartbeat tick
            if heartbeat_counter >= settings.autonomic_heartbeat_interval:
                heartbeat_counter = 0
                try:
                    worker = get_heartbeat_worker()
                    result = await worker.tick()
                    if result["processed"]:
                        health.heartbeats_processed += len(result["processed"])
                        logger.info(
                            f"Autonomic heartbeat: processed {len(result['processed'])} heartbeats"
                        )
                except Exception as e:
                    logger.error(f"Autonomic heartbeat error: {e}")
                    health.record_error(f"Heartbeat: {e}")

            # Run health check
            if health_counter >= settings.autonomic_health_interval:
                health_counter = 0
                health.health_checks_run += 1

                # Check database health
                try:
                    db = get_db_client()
                    db_health = await db.health_check()
                    health.update_component(
                        name="database",
                        healthy=db_health["healthy"],
                        latency_ms=db_health["latency_ms"],
                        error=db_health["error"],
                    )
                    if not db_health["healthy"]:
                        logger.error(f"Database unhealthy: {db_health['error']}")
                except Exception as e:
                    logger.error(f"Database health check failed: {e}")
                    health.update_component(
                        name="database",
                        healthy=False,
                        error=str(e),
                    )

                # Check tool health
                try:
                    conductor = get_conductor()
                    if conductor.registry:
                        tool_health = await conductor.registry.health_check_all()
                        for tool_name, is_healthy in tool_health.items():
                            health.update_component(
                                name=f"tool:{tool_name}",
                                healthy=is_healthy,
                            )
                        unhealthy = [
                            name for name, status in tool_health.items() if not status
                        ]
                        if unhealthy:
                            logger.warning(f"Unhealthy tools: {unhealthy}")
                        else:
                            logger.debug("All tools healthy")
                except Exception as e:
                    logger.error(f"Tool health check failed: {e}")
                    health.record_error(f"Tool health: {e}")

                # Pain response - only alert on critical issues
                if health.should_alert(threshold=3):
                    logger.critical(
                        f"SYSTEM CRITICAL: {health.status.value} - "
                        f"Unhealthy: {health.unhealthy_components}, "
                        f"Consecutive failures: {health.consecutive_failures}"
                    )

                # Log overall status periodically
                logger.info(
                    f"System health: {health.status.value} "
                    f"(uptime: {health.uptime_seconds:.0f}s, "
                    f"checks: {health.health_checks_run}, "
                    f"heartbeats: {health.heartbeats_processed})"
                )

        except asyncio.CancelledError:
            logger.info("Autonomic layer shutting down")
            break
        except Exception as e:
            logger.error(f"Autonomic loop error: {e}")
            health.record_error(str(e))
            await asyncio.sleep(5)  # Back off on error


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    global _autonomic_task

    # Startup
    logger.info(f"Starting Loop Symphony Server v{__version__}")
    settings = get_settings()
    logger.info(f"Debug mode: {settings.debug}")

    # Start autonomic layer if enabled
    if settings.autonomic_enabled:
        logger.info("Starting autonomic layer...")
        _autonomic_task = asyncio.create_task(autonomic_loop())
    else:
        logger.info("Autonomic layer disabled (set AUTONOMIC_ENABLED=true to enable)")

    yield

    # Shutdown
    if _autonomic_task:
        logger.info("Stopping autonomic layer...")
        _autonomic_task.cancel()
        try:
            await _autonomic_task
        except asyncio.CancelledError:
            pass

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
