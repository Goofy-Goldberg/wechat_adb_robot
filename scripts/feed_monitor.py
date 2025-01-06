# coding:utf-8
import logging
import re
import time
from wechat_adb_robot.core.robot import ADBRobot


class FeedItem:
    def __init__(self, node):
        self.node = node
        self.account_name = node.xpath(
            'node[@index="0"]/node[@index="0"]/node[@index="0"]/@text'
        )[0]
        self.last_article_time = node.xpath('node[@index="0"]/node[@index="1"]/@text')[
            0
        ]
        self.last_article_title = node.xpath(
            'node[@index="1"]/node[@index="0"]/node[@index="0"]/@text'
        )[0]
        self.bounds = node.xpath("@bounds")[0]


class FeedArticleItem:
    def __init__(self, node):
        self.node = node
        self.bounds = node.xpath("@bounds")[0]


class WeChatFeedMonitor:
    def __init__(
        self, serial, result_callback=lambda x: x, adb_path="adb", logger=None
    ):
        self.bot = ADBRobot(serial, adb_path=adb_path)
        self.result_callback = result_callback
        self.last_feed_list = []
        self.logger = logger if logger else logging.getLogger("feed_monitor")

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

            # Open clipboard app
            self.bot.ensure_clipboard()

            # Return to home screen
            self.bot.go_home()
            time.sleep(1)

            # Open WeChat home page
            self.ensure_wechat_front()
            time.sleep(1)

            # Enter subscription page
            self.go_feed_page()
            time.sleep(2)

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
        Ensure WeChat is in foreground and on home page
        """
        self.bot.run_app("com.tencent.mm")
        for _ in range(6):
            # Might not be on home page, pressing back 6 times should ensure return to home page
            # TODO: Use uidump to check if on WeChat home page
            self.bot.go_back()
        self.bot.run_app("com.tencent.mm")

    def go_feed_page(self):
        """
        Enter subscription list page
        """
        # TODO: Add logic to scroll and continue searching if not found on current screen

        dumps = self.bot.uidump_and_get_node()
        bounds672 = self.bot.get_node_bounds(
            "text",
            "订阅号",
            dumps=dumps,  # "Subscriptions"
        )  # For versions before 6.7.3
        bounds673 = self.bot.get_node_bounds(
            "text",
            "订阅号消息",
            dumps=dumps,  # "Subscription Messages"
        )  # For versions after 6.7.3

        if bounds672:
            self.bot.click_bounds(bounds672)
        elif bounds673:
            self.bot.click_bounds(bounds673)
            time.sleep(2)
            # For versions after 6.7.3, need to click the three-line more button in top right to enter list page
            boundsMore = self.bot.get_node_bounds(
                "content-desc",
                "订阅号",  # "Subscriptions"
            )  # For versions before 6.7.3
            if boundsMore:
                self.bot.click_bounds(boundsMore)
            else:
                self.logger.error(
                    "Cannot find more button in subscription message page"
                )
        else:
            self.logger.error(
                "Cannot find subscription tab, please confirm it's on WeChat home page"
            )

    def get_more_button_on_673_feed_page(self):
        """
        Get the first screen of subscription list on subscription page
        """
        page_node = self.bot.uidump_and_get_node()
        return page_node.xpath(
            '//node[@class="android.widget.ListView"]/node/node[@index="1"]'
        )

    def get_feed_list(self):
        """
        Get the first screen of subscription list on subscription page
        """
        page_node = self.bot.uidump_and_get_node()
        return [
            FeedItem(node)
            for node in page_node.xpath(
                '//node[@class="android.widget.ListView"]/node/node[@index="1"]'
            )
        ]

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

    def get_feed_articles_in_account_page(self):
        """
        Get the latest article list in subscription detail page, usually at the bottom
        """
        page_node = self.bot.uidump_and_get_node()
        content_boxes = page_node.xpath(
            '//node[@class="android.widget.FrameLayout"]/node[@class="android.widget.FrameLayout"]/node[@class="android.widget.ListView"]/node[@class="android.widget.RelativeLayout"]/node[@class="android.widget.LinearLayout"]/node[@class="android.widget.LinearLayout"]'
        )
        if len(content_boxes) == 0:
            return []
        last_content_box = content_boxes[len(content_boxes) - 1]
        return [FeedArticleItem(node) for node in last_content_box.xpath("node")]

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

    def output_result(self, url):
        self.logger.info("Output result: {}".format(url))
        self.result_callback(url)
