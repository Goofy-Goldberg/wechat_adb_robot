import subprocess
import os
import atexit
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@contextmanager
def manage_scrcpy():
    scrcpy_process = None

    try:
        # Only launch scrcpy if SKIP_SCRCPY is not set to "true"
        if not os.getenv("SKIP_SCRCPY", "").lower() == "true":
            logger.info("Starting scrcpy in background...")
            scrcpy_process = subprocess.Popen(
                ["scrcpy", "-d"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            # Give scrcpy time to initialize
            import time

            time.sleep(2)

        yield

    finally:
        if scrcpy_process:
            logger.info("Stopping scrcpy...")
            scrcpy_process.terminate()
            try:
                scrcpy_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("scrcpy didn't terminate gracefully, forcing kill...")
                scrcpy_process.kill()
