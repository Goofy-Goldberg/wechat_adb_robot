# coding:utf-8
import time
import json
import os
from com.dtmilano.android.viewclient import ViewClient, AdbClient
from dotenv import load_dotenv
from lib.utils import new_stream_logger
from core.robot import ADBRobot


class FeedArticleItem:
    def __init__(self, node):
        self.node = node
        self.bounds = node.xpath("@bounds")[0]


class WeChatFeedMonitor:
    def __init__(
        self, serial, result_callback=lambda x: x, adb_path="adb", logger=None
    ):
        self.serial = serial
        self.result_callback = result_callback
        self.adb_path = adb_path
        self.logger = logger or new_stream_logger()
        self.device, self.serialno = ViewClient.connectToDeviceOrExit(serialno=serial)
        self.vc = ViewClient(self.device, self.serialno)
        self.bot = ADBRobot(serial=serial, adb_path=adb_path)
        self.adb_client = AdbClient(serialno=serial)
        self.seen_articles_file = "seen_articles.json"
        self._load_seen_articles()

    def _load_seen_articles(self):
        """Load previously seen articles from JSON file"""
        try:
            if os.path.exists(self.seen_articles_file):
                with open(self.seen_articles_file, "r") as f:
                    self.seen_articles = json.load(f)
            else:
                self.seen_articles = {}
        except Exception as e:
            self.logger.error(f"Error loading seen articles: {e}")
            self.seen_articles = {}

    def _save_seen_articles(self):
        """Save seen articles to JSON file"""
        try:
            with open(self.seen_articles_file, "w") as f:
                json.dump(self.seen_articles, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Error saving seen articles: {e}")

    def run(self, skip_first_batch=True, sleep_interval=30):
        """
        Execute script in a loop
        Due to WeChat's mechanism, the subscription page won't update if kept static
        So this script simulates human behavior by turning screen on/off, which works well in practice
        :param skip_first_batch: Whether to save and skip the first captured subscription list
        :param sleep_interval: Screen off duration
        """
        loop_index = 0
        while True:
            self.logger.info("Starting loop {}".format(loop_index))
            # Turn screen off and on again
            self.bot.screen_off()
            self.bot.screen_on()

            if os.getenv("PIN"):
                self.bot.unlock()

            # Return to home screen
            self.bot.go_home()
            time.sleep(0.1)

            # Open WeChat home page
            self.ensure_wechat_front()
            time.sleep(0.1)

            # Enter subscription page
            self.go_feed_page()
            time.sleep(0.1)

            if skip_first_batch and loop_index == 0:
                # Save and skip the first captured subscription list
                self.get_feed_list_and_find_updates(set_new=True)
            else:
                # Execute subscription list monitoring
                self.feed_monitoring()

            # Return to WeChat home page
            self.bot.go_back()

            # Return to home screen
            self.bot.force_home()
            time.sleep(0.1)

            # Turn screen off
            self.bot.screen_off()

            loop_index += 1
            time.sleep(sleep_interval)

    def ensure_wechat_front(self):
        """
        Ensure WeChat is in foreground and on home page using ViewClient
        """
        self.bot.run_app("com.tencent.mm")
        time.sleep(0.1)

        # Wait for WeChat to be in foreground
        self.vc.dump()
        while not self.vc.findViewWithText("WeChat"):
            self.bot.go_back()
            time.sleep(0.1)
            self.vc.dump()

        self.bot.run_app("com.tencent.mm")

    def go_feed_page(self):
        """
        Enter subscription list page using ViewClient
        """
        self.vc.dump()
        official_account = self.vc.findViewWithText("Official Account")

        if official_account:
            official_account.touch()
            time.sleep(0.1)
        else:
            # Try scrolling to find the button if not visible
            self.bot.swipe_up()
            time.sleep(0.1)
            self.vc.dump()
            official_account = self.vc.findViewWithText("Official Account")
            if official_account:
                official_account.touch()
                time.sleep(0.1)
            else:
                self.logger.error("Cannot find subscription tab")

    def get_feed_list(self):
        """
        Get the first screen of subscription list using ViewClient
        """
        self.vc.dump()
        list_view = self.vc.findViewWithAttribute("class", "android.widget.ListView")
        if not list_view:
            self.logger.error("Cannot find ListView")
            return []

        feed_items = []

        # Find all views by ID
        views = self.vc.getViewsById()

        for view_id in views:
            view = self.vc.findViewById(view_id)

            # Find header containers
            if view.map.get("resource-id") == "com.tencent.mm:id/aq0":
                item = {}

                # Recursive function to search through children
                def find_in_children(view, item):
                    if view.map.get("resource-id", "").endswith("lu8"):
                        item["account"] = view.map.get("text", "")
                    elif view.map.get("resource-id", "").endswith("qdv"):
                        item["timestamp"] = view.map.get("text", "")

                    for child in view.getChildren():
                        find_in_children(child, item)

                # Search through this container's children
                find_in_children(view, item)

                # Look for title in next sibling container
                if "account" in item and "timestamp" in item:
                    parent = view.getParent()
                    if parent:
                        siblings = parent.getChildren()
                        found_current = False
                        for sibling in siblings:
                            if sibling == view:
                                found_current = True
                                continue
                            if found_current:
                                # Look for title in this container's children
                                def find_title(view):
                                    if view.map.get("resource-id", "").endswith("ozs"):
                                        return view.map.get("text", "")
                                    for child in view.getChildren():
                                        title = find_title(child)
                                        if title:
                                            return title
                                    return None

                                title = find_title(sibling)
                                if title:
                                    item["title"] = title
                                    break

                    if item:
                        print(f"Found item: {item}")
                        feed_items.append(item)

        return feed_items

    def get_feed_articles_in_account_page(self):
        """
        Get the latest article list using ViewClient
        """
        self.vc.dump()
        articles = []

        # Find the ListView containing articles
        list_view = self.vc.findViewWithAttribute("class", "android.widget.ListView")
        if not list_view:
            return []

        # Get the last content box (latest articles)
        content_boxes = list_view.children
        if not content_boxes:
            return []

        last_content_box = content_boxes[-1]

        # Extract article items
        for article_view in last_content_box.children:
            try:
                bounds = article_view.getBounds()
                articles.append(FeedArticleItem({"bounds": bounds}))
            except Exception as e:
                self.logger.exception(f"Error parsing article item: {e}")

        return articles

    def get_feed_list_and_find_updates(self, set_new=True):
        """
        Get the first screen of subscription list and find updated subscription items
        """
        new_feed_list = self.get_feed_list()
        result = []

        for feed_item in new_feed_list:
            try:
                # Create a unique key for the article using account and title
                article_key = f"{feed_item['account']}:{feed_item['title']}"

                # Check if we've seen this article before
                if article_key not in self.seen_articles:
                    result.append(feed_item)
                    if set_new:
                        # Store the article with timestamp
                        self.seen_articles[article_key] = {
                            "timestamp": feed_item["timestamp"],
                            "first_seen": time.time(),
                        }
            except Exception as e:  # at this point the likely error be that not the entire feed item is visible
                self.logger.exception(f"Error processing feed item: {e}")

        if set_new:
            self._save_seen_articles()

        return result

    def feed_monitoring(self):
        """
        Monitor subscription list, find updated subscriptions, enter each subscription and click latest links.
        Uses a two-item-at-a-time scrolling pattern to process the feed efficiently.
        """
        while True:
            self.vc.dump()
            # check if there is any element with the text "Show earlier messages"
            show_earlier_messages = self.vc.findViewWithText("Show earlier messages")
            if show_earlier_messages:
                show_earlier_messages.touch()
                time.sleep(0.5)

            # Get the first two items in view
            feed_items = self.get_feed_list()[:2]
            if not feed_items:
                self.logger.info("No more items found")
                break

            # Check if we've seen these items before
            new_items = []
            for feed_item in feed_items:
                article_key = f"{feed_item['account']}:{feed_item['title']}"
                if article_key not in self.seen_articles:
                    new_items.append(feed_item)
                else:
                    # We've hit a seen article, stop processing
                    self.logger.info("Found previously seen article, stopping")
                    return

            # Process new items
            for index, feed_item in enumerate(new_items):
                # Find and click the account name
                title_views = self.vc.findViewsWithAttribute(
                    "resource-id", "com.tencent.mm:id/ozs"
                )
                view = title_views[index]

                runtime_id = view.getId()
                target_view = self.vc.findViewById(runtime_id)
                if target_view:
                    target_view.touch()

                    # Process the article
                    print("Processing article [incomplete implementation]")
                    time.sleep(0.5)

                    # tap three dots button
                    self.bot.tap(1000, 209)
                    time.sleep(0.5)

                    # tap copy link button
                    self.bot.tap(850, 1960)
                    time.sleep(0.1)

                    self.bot.go_back()
                    time.sleep(0.5)

                # Mark as seen
                article_key = f"{feed_item['account']}:{feed_item['title']}"
                self.seen_articles[article_key] = {
                    "timestamp": feed_item["timestamp"],
                    "first_seen": time.time(),
                }
                self._save_seen_articles()

            # Scroll down by the height of two items
            # Get the bounds of the first and third items to calculate scroll distance
            items = self.vc.findViewsWithAttribute(
                "resource-id", "com.tencent.mm:id/aq0"
            )
            if len(items) >= 3:
                first_item = items[0]
                second_item = items[1]
                scroll_distance = (
                    second_item.getBounds()[0][1] - first_item.getBounds()[0][1]
                )
                self.bot.swipe_up_by_distance(
                    scroll_distance
                )  # Scroll down by the height of two items
                time.sleep(0.5)  # Wait for scroll to complete
            else:
                # Not enough items to scroll, we're done
                break


def push_result(url):
    print("Got new article url:", url)


if __name__ == "__main__":
    load_dotenv()

    device_serial = os.getenv("DEVICE_SERIAL")
    if not device_serial:
        raise ValueError("DEVICE_SERIAL not found in .env file")

    monitor = WeChatFeedMonitor(
        serial=device_serial,
        result_callback=push_result,
        adb_path="adb",
        logger=new_stream_logger(),
    )
    monitor.run(skip_first_batch=False)
