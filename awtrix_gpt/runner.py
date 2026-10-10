"""Background thread that drives an AwtrixManager, and a headless CLI entry point."""

import logging
import threading
from typing import Callable, Optional

from awtrix_gpt.manager import AwtrixManager

ManagerFactory = Callable[..., AwtrixManager]   # called as factory(host=..., debug=...)


class DisplayRunner:
    """Owns the display thread. `start()` (re)creates the manager via the factory."""

    def __init__(self, factory: ManagerFactory, *, poll_seconds: float = 5.0, logger=None):
        self._factory = factory
        self._poll = poll_seconds
        self.logger = logger or logging.getLogger(__name__)
        self.manager: Optional[AwtrixManager] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, host: Optional[str] = None, debug: Optional[bool] = None) -> AwtrixManager:
        """Stop any previous thread, build a fresh manager and drive it in a new thread.

        Each thread gets its own stop event: a previous thread still inside a
        blocking `sleep()` when `stop()` times out must still exit afterwards,
        instead of seeing a shared event cleared and running on forever.
        """
        self.stop()
        manager = self._factory(host=host, debug=debug)
        stop = threading.Event()
        thread = threading.Thread(target=self._loop, args=(manager, stop),
                                  name="awtrix-display", daemon=True)
        self.manager, self._stop, self._thread = manager, stop, thread
        thread.start()
        self.logger.info("Display thread started for %s", manager.host)
        return manager

    def stop(self, join_timeout: float = 5.0) -> None:
        if self.running:
            self._stop.set()
            self._thread.join(timeout=join_timeout)
        self._thread = None

    def _loop(self, manager: AwtrixManager, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                manager.tick()
            except Exception as e:
                self.logger.error("Error in display cycle: %s", e)
            stop.wait(self._poll)


def run_forever() -> None:
    """Headless mode: `python -m awtrix_gpt.runner` drives the clock without the web UI."""
    from dotenv import load_dotenv

    from config_loader import load_config

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    runner = DisplayRunner(lambda host=None, debug=None: AwtrixManager.from_config(
        load_config(force_reload=True), host=host, debug=debug))
    runner.start()
    try:
        while True:
            threading.Event().wait(60)
    except KeyboardInterrupt:
        runner.stop()


if __name__ == "__main__":
    run_forever()
