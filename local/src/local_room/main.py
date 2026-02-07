"""Main entry point for Local Room service."""

import logging
import uvicorn

from local_room.config import LocalRoomConfig
from local_room.api.routes import create_app

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


def main():
    """Run the Local Room service."""
    config = LocalRoomConfig.from_env()

    logger.info(f"Starting Local Room: {config.room_id}")
    logger.info(f"Ollama: {config.ollama_host} (model: {config.ollama_model})")
    logger.info(f"Server: {config.server_url}")
    logger.info(f"Listening on: {config.host}:{config.port}")

    app = create_app(config)

    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
