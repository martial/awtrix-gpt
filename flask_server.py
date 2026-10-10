"""Entry point run by systemd: `venv/bin/python flask_server.py`.

Everything else lives in the `awtrix_gpt` package; this file only configures
logging, loads `.env` and starts the Flask app.
"""

import logging
import os

from dotenv import load_dotenv

from awtrix_gpt.web import create_app

logger = logging.getLogger(__name__)


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    port = int(os.getenv("PORT", 5001))
    debug = os.getenv("FLASK_DEBUG", "False").lower() == "true"
    logger.info("Starting server on port %s with debug=%s", port, debug)
    try:
        app = create_app()
        app.run(host="0.0.0.0", port=port, debug=debug)
    except Exception as e:
        logger.error("Server error: %s", e)
        raise


if __name__ == "__main__":
    main()
