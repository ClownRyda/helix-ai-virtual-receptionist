"""
Entry point — starts both the FastAPI REST server and the ARI WebSocket agent
concurrently in the same asyncio event loop.
"""
import asyncio
import structlog
import uvicorn

from database import init_db
from ari_agent import run_ari_agent
from api import app
from config import settings

log = structlog.get_logger(__name__)


async def main():
    # Initialize database
    await init_db()
    log.info("Database initialized")

    # Pre-warm Whisper model on startup
    log.info("Pre-warming Whisper model...")
    from stt.whisper_engine import get_model
    await asyncio.get_event_loop().run_in_executor(None, get_model)
    log.info("Whisper ready")

    # Pre-warm Silero VAD on startup so the first call does not stall before greeting.
    log.info("Pre-warming Silero VAD...")
    from vad.silero_engine import _load_model
    await asyncio.get_event_loop().run_in_executor(None, _load_model)
    log.info("Silero VAD ready")

    # Start FastAPI in background
    config = uvicorn.Config(
        app=app,
        host=settings.api_host,
        port=settings.api_port,
        log_level="info",
    )
    server = uvicorn.Server(config)

    # Run FastAPI + ARI agent concurrently
    await asyncio.gather(
        server.serve(),
        run_ari_agent_with_retry(),
    )


async def run_ari_agent_with_retry():
    """Run the ARI agent with auto-reconnect on disconnect."""
    while True:
        try:
            log.info("Starting ARI agent...")
            await run_ari_agent()
        except Exception as e:
            log.error("ARI agent crashed, retrying in 5s", error=str(e))
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
