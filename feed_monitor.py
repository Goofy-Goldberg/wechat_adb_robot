# coding:utf-8
import time
import os
from com.dtmilano.android.viewclient import ViewClient, AdbClient, ViewNotFoundException
from dotenv import load_dotenv
from lib.utils import new_stream_logger
from core.robot import ADBRobot
import pyperclip
from lib.db import ArticleDB
from lib.scrcpy import manage_scrcpy
from lib.article import Article
from datetime import datetime, timedelta, UTC
from zoneinfo import ZoneInfo


class FeedArticleItem:
    def __init__(self, node):
        self.node = node
        self.bounds = node.xpath("@bounds")[0]


def bounds(view):
    """
    Get the bounds of a view and return as a dictionary with left, top, right, bottom, width, and height values
    """
    bounds = view.getBounds()
    return {
        "left": bounds[0][0],
        "top": bounds[0][1],
        "right": bounds[1][0],
        "bottom": bounds[1][1],
        "width": bounds[1][0] - bounds[0][0],
        "height": bounds[1][1] - bounds[0][1],
    }


class WeChatFeedMonitor:
    def __init__(self, serial, adb_path="adb", logger=None):
        self.serial = serial
        self.adb_path = adb_path
        self.logger = logger or new_stream_logger()
        self.device, self.serialno = ViewClient.connectToDeviceOrExit(serialno=serial)
        self.vc = ViewClient(self.device, self.serialno)
        self.bot = ADBRobot(serial=serial, adb_path=adb_path)
        self.adb_client = AdbClient(serialno=serial)
        self.db = ArticleDB()
        self.seen_articles = {
            article.key: article
            for article in map(Article.from_dict, self.db.get_all_articles().values())
        }
        self.seen_articles_this_run = {}
        self.clipboard = None

    def _get_view_structure(self):
        self.vc.dump()

        # First, collect all views into a map
        views = self.vc.getViewsById()
        view_map = {}

        # First pass: collect all views and their properties
        for view_id in views:
            view = self.vc.findViewById(view_id)
            view_map[view_id] = {
                "id": view_id,
                "class": view.map.get("class", ""),
                "text": view.map.get("text", ""),
                "content-desc": view.map.get("content-desc", ""),
                "resource-id": view.map.get("resource-id", ""),
                "bounds": view.map.get("bounds", ""),
                "children": [],
                "parent": None,
            }

        # Second pass: build parent-child relationships
        tree = {}
        for view_id in views:
            view = self.vc.findViewById(view_id)
            parent = view.getParent()
            if parent:
                parent_id = None
                # Find parent's id in our map
                for pid in view_map:
                    if self.vc.findViewById(pid) == parent:
                        parent_id = pid
                        break
                if parent_id:
                    view_map[view_id]["parent"] = parent_id
                    view_map[parent_id]["children"].append(view_id)
            else:
                # This is a root node
                tree[view_id] = view_map[view_id]

        # Convert the tree to a nested dictionary structure
        def build_dict_tree(node_id):
            node = view_map[node_id].copy()
            # Convert children array of IDs to array of nested nodes
            children = node["children"]
            node["children"] = [build_dict_tree(child_id) for child_id in children]
            return node

        # Build final tree structure
        final_tree = {root_id: build_dict_tree(root_id) for root_id in tree}

        return final_tree

    def process_article(self, view_to_click_to_open):
        """
        Process an article by clicking on it and then copying the link
        Accepts a view object to click to open the article
        Returns the URL of the article
        """
        self.logger.info("Opening article")
        view_to_click_to_open.touch()

        # Process the article
        self.logger.info("Processing article...")
        time.sleep(0.5)

        got_url = False

        def copy_link(retry=10):
            base_sleep = 0.1
            attempt = 0
            while retry > 0:
                # Exponential backoff sleep
                sleep_time = base_sleep * (2**attempt)

                # tap three dots button
                self.bot.tap(1000, 209)
                time.sleep(0.1)

                self.vc.dump()
                # find the copy link button
                copy_link_button = self.vc.findViewWithText("Copy Link")
                if not copy_link_button:
                    self.logger.info(
                        f"Cannot find copy link button, trying to tap the three dots again (attempt {attempt + 1}, sleeping {sleep_time:.2f}s)"
                    )
                    time.sleep(sleep_time)
                    retry -= 1
                    attempt += 1
                else:
                    copy_link_button.touch()
                    time.sleep(0.3)

                    # if scrcpy is running, it should synchronise the clipboard. There might be a way to do this directly through adb. For now, we have to access the computer's clipboard.
                    return pyperclip.paste()

        while not got_url:
            clipboard_new = copy_link()

            if not clipboard_new:
                self.logger.error("Cannot find copy link button, retrying...")
                raise Exception("Cannot find copy link button")

            self.logger.info(f"Clipboard: {clipboard_new}")

            if not clipboard_new.startswith("https://"):
                self.logger.error("Clipboard does not contain a valid URL")
            elif clipboard_new != self.clipboard:
                self.clipboard = clipboard_new
                got_url = True
            else:
                self.logger.info("Clipboard did not change, retrying...")

        # swipe to dismiss the clipboard popup
        self.bot.swipe(start_x=250, start_y=2220, dx=-100)
        time.sleep(0.1)

        self.bot.go_back()
        time.sleep(0.5)

        return clipboard_new

    def run(self, skip_first_batch=True):
        """
        Execute script in a loop
        Due to WeChat's mechanism, the subscription page won't update if kept static
        So this script simulates human behavior by turning screen on/off, which works well in practice
        """
        loop_index = 0
        articles_collected = 0
        max_articles = int(os.getenv("MAX_ARTICLES"), 0)  # per profile
        if max_articles == 0:
            max_articles = None
        collection_timeout = int(os.getenv("COLLECTION_TIMEOUT", "30"))  # in seconds

        # Main loop - reinitiate the app, navigate to the feed page, scroll up to the top
        while True:
            self.logger.info("Starting loop {}".format(loop_index))

            # Check if we've hit the article limit
            if max_articles and articles_collected >= max_articles:
                self.logger.info(f"Reached maximum article limit of {max_articles}")
                break

            # Check if skip app opening is not true - useful for debugging to skip the long navigation to the feed page, if you can ensure you're on the right page
            if not os.getenv("SKIP_APP_OPENING", "").lower() == "true":
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

                self.logger.info("Navigating to profiles page")
                self.vc.dump()

                try:
                    view = self.vc.findViewByIdOrRaise("com.tencent.mm:id/g9")
                    view.touch()
                    time.sleep(0.1)
                    self.vc.dump()
                except ViewNotFoundException:
                    self.logger.error(
                        "View with resource-id 'com.tencent.mm:id/g9' not found."
                    )

                try:
                    view = self.vc.findViewWithText("Followed Official Accounts")
                    view.touch()
                    time.sleep(0.1)
                except ViewNotFoundException:
                    self.logger.error(
                        "View with text 'Followed Official Accounts' not found."
                    )

            self.vc.dump()

            usernames = [
                username_view.map.get("text", "")
                for username_view in self.vc.findViewsWithAttribute(
                    "resource-id", "com.tencent.mm:id/lun"
                )
            ]

            for (
                username
            ) in usernames:  # todo!: scroll when visible usernames are exhausted
                articles_collected_in_profile = 0

                profile_item = self.vc.findViewWithText(username)
                profile_item.touch()
                time.sleep(0.1)

                # we are on the articles list now

                def go_back_to_profiles():
                    self.bot.go_back()
                    time.sleep(0.1)
                    self.vc.dump()

                # check if there is a com.tencent.mm:id/byr view
                byr_view = self.vc.findViewWithAttribute(
                    "resource-id", "com.tencent.mm:id/byr"
                )
                if byr_view:
                    self.logger.info(
                        "This is the card type profile view, we don't have this implemented yet"
                    )
                    go_back_to_profiles()
                    continue

                def go_to_first_article():
                    # first we press down, up, down, down to select the newest (lowest) article
                    self.bot.shell("input keyevent 20")
                    time.sleep(0.1)
                    self.bot.shell("input keyevent 19")
                    time.sleep(0.1)
                    self.bot.shell("input keyevent 20")
                    time.sleep(0.1)
                    self.bot.shell("input keyevent 20")
                    time.sleep(0.1)
                    self.vc.dump()

                go_to_first_article()

                profile_done = False

                while not profile_done:
                    # Create article with required fields
                    article = Article(account=username, title=None)

                    # find the focused element
                    focused_view = self.vc.findViewWithAttribute("focused", "true")

                    # find the title (com.tencent.mm:id/qit) in children recursively
                    def find_title(view):
                        if view.map.get("resource-id", "") == "com.tencent.mm:id/qit":
                            return view.map.get("text", "")
                        for child in view.children:
                            result = find_title(child)
                            if result:
                                return result
                        return None

                    article.title = find_title(focused_view)
                    self.logger.info(f"Title: {article.title}")

                    def get_timestamp(focused_view):
                        # find the timestamp
                        siblings = focused_view.parent.children
                        for sibling in siblings:
                            if (
                                sibling.map.get("resource-id", "")
                                == "com.tencent.mm:id/c3b"
                            ):
                                timestamp_string = sibling.map.get("text", "")
                                try:
                                    # Get the device's timezone
                                    device_tz = ZoneInfo(self.bot.get_timezone())

                                    if "Yesterday" in timestamp_string:
                                        # Remove "Yesterday " prefix and parse as today, then subtract one day
                                        time_part = timestamp_string.replace(
                                            "Yesterday ", ""
                                        )
                                        today_time = datetime.strptime(
                                            time_part, "%I:%M %p"
                                        ).time()
                                        local_dt = datetime.combine(
                                            datetime.now(device_tz).date(), today_time
                                        ).replace(tzinfo=device_tz) - timedelta(days=1)
                                    elif "/" in timestamp_string:
                                        # Full date format
                                        local_dt = datetime.strptime(
                                            timestamp_string, "%m/%d/%y %I:%M %p"
                                        ).replace(tzinfo=device_tz)
                                    elif any(
                                        day in timestamp_string
                                        for day in [
                                            "Mon",
                                            "Tue",
                                            "Wed",
                                            "Thu",
                                            "Fri",
                                            "Sat",
                                            "Sun",
                                        ]
                                    ):
                                        # Day of week format - find the most recent matching day
                                        day_name = timestamp_string.split()[0]
                                        time_part = " ".join(
                                            timestamp_string.split()[1:]
                                        )
                                        today = datetime.now(device_tz)

                                        # Convert day name to weekday number (0-6)
                                        target_weekday = time.strptime(
                                            day_name, "%a"
                                        ).tm_wday
                                        current_weekday = today.weekday()

                                        # Calculate days difference
                                        days_diff = (
                                            current_weekday - target_weekday
                                        ) % 7
                                        if days_diff == 0:
                                            days_diff = (
                                                7  # If today, it must be from last week
                                            )

                                        target_date = today.date() - timedelta(
                                            days=days_diff
                                        )
                                        target_time = datetime.strptime(
                                            time_part, "%I:%M %p"
                                        ).time()
                                        local_dt = datetime.combine(
                                            target_date, target_time
                                        ).replace(tzinfo=device_tz)
                                    else:
                                        # Today's time only
                                        today_time = datetime.strptime(
                                            timestamp_string, "%I:%M %p"
                                        ).time()
                                        local_dt = datetime.combine(
                                            datetime.now(device_tz).date(), today_time
                                        ).replace(tzinfo=device_tz)

                                    # Convert to UTC timestamp
                                    return local_dt.astimezone(UTC).timestamp()
                                except ValueError:
                                    self.logger.error(
                                        f"Failed to parse timestamp: {timestamp_string}"
                                    )
                                break

                    timestamp = get_timestamp(focused_view)
                    if not timestamp:
                        # go up and down to reveal the timestamp
                        self.bot.shell("input keyevent 19")
                        time.sleep(0.1)
                        self.bot.shell("input keyevent 20")
                        time.sleep(0.1)
                        self.vc.dump()
                        focused_view = self.vc.findViewWithAttribute("focused", "true")
                        timestamp = get_timestamp(focused_view)

                    article.published_at = timestamp

                    self.logger.info(f"Timestamp: {article.timestamp}")

                    # Check if we should process this article
                    if (
                        article.key in self.seen_articles
                        and article.key not in self.seen_articles_this_run
                    ):
                        self.logger.info("Article already seen, moving to next profile")
                        go_back_to_profiles()
                        break

                    if article.key in self.seen_articles_this_run:
                        self.logger.info(
                            "Reached previously seen article in this run, moving to next profile"
                        )
                        go_back_to_profiles()
                        break

                    # Get the article URL
                    try:
                        article.url = self.process_article(focused_view)
                        time.sleep(0.1)

                        # Store the article immediately after getting URL
                        if self.db.add_article(
                            account=article.account,
                            title=article.title,
                            published_at=article.published_at,
                            url=article.url,
                        ):
                            self.seen_articles[article.key] = article
                            self.logger.info("Article added to database.")
                        else:
                            self.logger.info(
                                "Article already exists in database (duplicate URL), skipping"
                            )
                    except Exception as e:
                        self.logger.error(f"Error processing article: {e}")
                        # Continue with next article even if this one fails

                    # Update collection count
                    articles_collected_in_profile += 1
                    if max_articles:
                        self.logger.info(
                            f"Collected {articles_collected_in_profile}/{max_articles} articles in profile {username}"
                        )
                        if articles_collected_in_profile >= max_articles:
                            self.logger.info(
                                f"Maximum article limit reached, ending collection for this profile ({username})"
                            )
                            go_back_to_profiles()
                            break
                    else:
                        self.logger.info(
                            f"Collected {articles_collected_in_profile} articles in profile {username}"
                        )

                    # go back to the profiles list
                    self.bot.go_back()
                    time.sleep(0.1)
                    self.vc.dump()
                    # click on the username again
                    profile_item = self.vc.findViewWithText(username)
                    profile_item.touch()
                    time.sleep(0.1)
                    self.vc.dump()
                    # go to first article
                    go_to_first_article()
                    # now go up as many times as needed to get to the next article
                    num_up_presses = articles_collected_in_profile
                    for i in range(num_up_presses):
                        self.bot.shell("input keyevent 19")
                        time.sleep(0.1)
                    self.vc.dump()

            # After breaking from article loop, these cleanup steps will run:
            # Return to WeChat home page
            self.bot.go_back()

            # Return to home screen
            self.bot.force_home()
            time.sleep(0.1)

            # Turn screen off
            self.bot.screen_off()

            loop_index += 1

            # Apply collection timeout
            self.logger.info(
                f"Waiting {collection_timeout:.1f}s before next collection loop"
            )
            time.sleep(collection_timeout)

    def ensure_wechat_front(self):
        """
        Ensure WeChat is in foreground and on home page by killing the app if it's already running and starting it again
        """
        # kill the app if it's already running
        self.logger.info("Killing WeChat app")
        self.bot.kill_app()
        time.sleep(0.1)

        # start the app
        self.logger.info("Starting WeChat app")
        self.bot.run_app()
        time.sleep(0.1)

        # Wait for WeChat to load
        self.logger.info("Waiting for WeChat to load")
        self.vc.dump()
        while not self.vc.findViewWithText("WeChat"):
            time.sleep(0.1)
            self.vc.dump()

        self.bot.run_app()

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


if __name__ == "__main__":
    load_dotenv()

    device_serial = os.getenv("DEVICE_SERIAL")
    if not device_serial:
        raise ValueError("DEVICE_SERIAL not found in .env file")

    from lib.scrcpy import manage_scrcpy

    with manage_scrcpy():
        monitor = WeChatFeedMonitor(
            serial=device_serial,
            adb_path="adb",
            logger=new_stream_logger(),
        )
        monitor.run(skip_first_batch=False)
