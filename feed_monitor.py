# coding:utf-8
import time
from com.dtmilano.android.viewclient import ViewClient
from dotenv import load_dotenv
from lib.utils import new_stream_logger
import os
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
            # Turn screen on
            self.bot.screen_on()

            # Return to home screen
            self.bot.go_home()
            time.sleep(1)

            # Open WeChat home page
            self.ensure_wechat_front()
            time.sleep(1)

            # Enter subscription page
            self.go_feed_page()
            time.sleep(1)

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
            time.sleep(1)

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
        old_account_names = [_.account_name for _ in self.last_feed_list]
        result = []

        for new_feed_item in new_feed_list:
            if new_feed_item.account_name not in old_account_names:
                result.append(new_feed_item)

        if set_new:
            self.last_feed_list = new_feed_list

        return result

    def feed_monitoring(self):
        """
        Monitor subscription list, find updated subscriptions, enter each subscription and click latest links to copy to clipboard
        """
        # Get list of recently updated subscriptions
        newly_update_feed_list = self.get_feed_list_and_find_updates(set_new=True)
        self.logger.info(
            "Recently updated official accounts: {}".format(
                [_.account_name for _ in newly_update_feed_list]
            )
        )

        for feed_item in newly_update_feed_list:
            # Enter subscription detail page
            self.logger.info(
                "Entering subscription [{}] detail page ...".format(
                    feed_item.account_name
                )
            )
            self.bot.click_bounds(feed_item.bounds)

            # Get latest article list for the subscription
            feed_articles = self.get_feed_articles_in_account_page()
            self.logger.info(
                "Number of articles in latest article list: {}".format(
                    len(feed_articles)
                )
            )

            # Search latest article list for the subscription
            for feed_article_item in feed_articles:
                # Click article detail page
                self.logger.debug("Entering article detail page ...")
                self.bot.click_bounds(feed_article_item.bounds)
                time.sleep(2)

                # Click more
                self.logger.debug("Clicking more ...")
                more_button_bounds = self.bot.get_node_bounds(
                    "content-desc",
                    "更多",  # "More"
                )  # "More"
                if more_button_bounds:
                    self.bot.click_bounds(more_button_bounds)
                    time.sleep(2)
                else:
                    self.logger.error("Cannot find more button, article issue?")

                # Click copy link
                self.logger.debug("Clicking copy link ...")
                copy_link_btn_bounds = self.bot.get_node_bounds(
                    "text",
                    "复制链接",  # "Copy Link"
                )  # "Copy Link"
                if copy_link_btn_bounds:
                    self.bot.click_bounds(copy_link_btn_bounds)
                    time.sleep(1)

                    # Get clipboard content and output
                    self.output_result(self.bot.get_clipboard_text())
                else:
                    self.logger.error("Cannot find copy link button, article issue?")

                self.logger.debug("Returning to subscription page ...")
                self.bot.go_back()
            self.bot.go_back()


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
