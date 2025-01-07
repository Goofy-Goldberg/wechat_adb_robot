# coding:utf-8
from dotenv import load_dotenv
import os
from scripts.feed_monitor import WeChatFeedMonitor
from lib.utils import new_stream_logger


def push_result(url):
    print("Got new article url:", url)


if __name__ == "__main__":
    # Load environment variables from .env file
    load_dotenv()

    # Get device serial from environment variable
    device_serial = os.getenv("DEVICE_SERIAL")
    if not device_serial:
        raise ValueError("DEVICE_SERIAL not found in .env file")

    # Assume we already have device attached and has clipper installed
    monitor = WeChatFeedMonitor(
        serial=device_serial,
        result_callback=push_result,
        adb_path="adb",
        logger=new_stream_logger(),
    )
    monitor.run(skip_first_batch=False)
