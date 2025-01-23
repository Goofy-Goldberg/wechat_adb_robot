import subprocess
import os
import logging
from contextlib import contextmanager
import time

logger = logging.getLogger(__name__)


@contextmanager
def manage_scrcpy(serial: str):
    if not serial:
        raise ValueError(
            "Couldn't launch scrcpy: didn't get device serial"
        )  # todo: more informative

    scrcpy_process = None

    try:
        # Only launch scrcpy if SKIP_SCRCPY is not set to "true"
        if not os.getenv("SKIP_SCRCPY", "").lower() == "true":
            logger.info("Starting scrcpy in background...")

            args = ["scrcpy", "-s", serial]

            if os.getenv("HEADLESS", "").lower() == "true":
                args.append(
                    "--no-window"
                )  # in headless mode, scrcpy doesn't seem to be able to sync the clipboard

            scrcpy_process = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Give scrcpy time to initialize
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
