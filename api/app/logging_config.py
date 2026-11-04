import logging


def configure_logging() -> None:
    """Same log format for the API and the worker."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx logs every request URL at INFO, and a Telegram URL holds the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
