# coding:utf-8
import time
import os
import re
import argparse
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
from pathlib import Path
from enum import Enum, auto


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


class ArticleStoreStatus(Enum):
    SUCCESS = auto()
    DUPLICATE = auto()
    DATABASE_ERROR = auto()
    INVALID_DATA = auto()  # For cases where article data is incomplete/invalid
    UNEXPECTED_ERROR = auto()


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

    def find_in_descendants(self, view, attribute="resource-id", value=None):
        found = []
        # Check current view's resource-id
        if view.map.get(attribute, "") == value:
            found.append(view)
        # Recursively check all children
        for child in view.children:
            found.extend(self.find_in_descendants(child, attribute, value))
        return found

    def find_in_siblings(self, view, attribute="resource-id", value=None):
        found = []
        siblings = view.parent.children
        for sibling in siblings:
            if sibling.map.get(attribute, "") == value:
                found.append(sibling)
        return found

    def store_article(self, article):
        """Store the article in the database and update seen_articles cache.

        Returns:
            ArticleStoreStatus: The status of the storage operation
            - SUCCESS: Article was successfully added
            - DUPLICATE: Article already exists in database
            - DATABASE_ERROR: Database-related error occurred
            - INVALID_DATA: Article data is invalid or incomplete
            - UNEXPECTED_ERROR: Other unexpected errors
        """
        # Validate article data
        if not all([article.account, article.title, article.published_at, article.url]):
            self.logger.error("Invalid article data: missing required fields")
            return ArticleStoreStatus.INVALID_DATA

        success, error_msg = self.db.add_article(
            account=article.account,
            title=article.title,
            published_at=article.published_at,
            url=article.url,
        )

        if success:
            self.seen_articles[article.key] = article
            self.logger.info("Article added to database.")
            return ArticleStoreStatus.SUCCESS
        else:
            if "Duplicate article" in error_msg:
                self.logger.info("Article already exists in database (duplicate URL)")
                return ArticleStoreStatus.DUPLICATE
            elif "Database error" in error_msg:
                self.logger.error(f"Database error: {error_msg}")
                return ArticleStoreStatus.DATABASE_ERROR
            else:
                self.logger.error(f"Unexpected error: {error_msg}")
                return ArticleStoreStatus.UNEXPECTED_ERROR

    def process_article_inner(self):
        """
        The actual processing of an article when already on the article page
        Returns URL of the article
        """

        # Process the article
        self.logger.info("Getting article metadata...")
        time.sleep(0.5)

        metadata = {}

        metadata["title"] = self.vc.findViewById("activity-name").getText()
        published_at = self.vc.findViewById("publish_time").getText()

        # parse published_at - the format is like 2025年01月22日 08:08
        local_dt = datetime.strptime(published_at, "%Y年%m月%d日 %H:%M")
        # Get device's timezone
        device_tz = ZoneInfo(self.bot.get_timezone())
        # Attach the device's timezone to the datetime
        local_dt = local_dt.replace(tzinfo=device_tz)
        # Convert to UTC timestamp
        metadata["published_at"] = local_dt.astimezone(UTC).timestamp()

        time.sleep(0.1)

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

            self.logger.debug(f"Clipboard: {clipboard_new}")

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

        metadata["url"] = clipboard_new

        return metadata

    def process_article(self, view_to_click_to_open):
        """
        Process an article by clicking on it and then copying the link
        Accepts a view object to click to open the article
        Returns the URL of the article or raises an exception if processing fails
        """
        try:
            self.logger.info("Opening article")
            self.bot.tap_bounds(view_to_click_to_open)
            self.bot.tap_bounds(
                view_to_click_to_open
            )  # todo: check why double tap is needed
            time.sleep(0.1)

            product = self.process_article_inner()

            self.bot.go_back()
            time.sleep(0.5)

            if not product.get("url"):
                raise ValueError("No URL found in processed article")

            return product["url"]
        except Exception as e:
            self.logger.error(f"Failed to process article: {str(e)}")
            # Go back to ensure we're in the right state for the next article
            self.bot.go_back()
            time.sleep(0.5)
            raise  # Re-raise the exception to be handled by the caller

    def run(self, skip_first_batch=True):
        """
        Execute script in a loop
        Due to WeChat's mechanism, the subscription page won't update if kept static
        So this script simulates human behavior by turning screen on/off, which works well in practice
        """
        loop_index = 0
        articles_collected = 0
        max_articles = os.getenv("MAX_ARTICLES")
        if max_articles is None:
            max_articles = 10  # default to 10 articles per profile
        else:
            try:
                max_articles = int(max_articles)
                if max_articles <= 0:
                    max_articles = 10  # if they provided 0 or negative, use default
            except ValueError:
                self.logger.warning(
                    f"Invalid MAX_ARTICLES value: {max_articles}, using default of 10"
                )
                max_articles = 10

        collection_timeout = int(os.getenv("COLLECTION_TIMEOUT", "30"))  # in seconds

        # Get accounts - if provided, use search flow, otherwise use followed accounts flow
        accounts = self.get_accounts()
        if accounts:
            self.logger.info(
                f"Found {len(accounts)} accounts to monitor via search: {accounts}"
            )
        else:
            self.logger.info("No accounts provided, monitoring followed accounts")

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
                self.logger.info("Turning screen off and on again")
                self.bot.screen_off()
                self.bot.screen_on()

                if os.getenv("PIN"):
                    self.logger.info("PIN provided, unlocking device")
                    self.bot.unlock()

                # Return to home screen
                self.logger.info("Going to home screen")
                self.bot.go_home()
                time.sleep(0.5)

                # Open WeChat home page
                self.logger.info("Opening WeChat home page")
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

            if accounts:  # Search flow
                for username_index, username in enumerate(accounts, start=1):
                    # navigate to search
                    # todo: we can use the search icon on the previous screen

                    # find by id
                    search_icon_view = self.vc.findViewById("com.tencent.mm:id/g7")
                    search_icon_view.touch()
                    time.sleep(0.1)
                    self.vc.dump()

                    # type the username
                    self.bot.type(username)
                    time.sleep(0.1)
                    self.bot.enter()
                    time.sleep(0.1)
                    self.vc.dump()

                    # tap the result
                    result_view = self.vc.findViewWithAttributeThatMatches(
                        "text", re.compile(r".*WeChat ID:.*$")
                    )
                    if result_view and username in result_view.getText():
                        result_view.touch()
                        time.sleep(0.1)
                        self.vc.dump()
                    else:
                        self.logger.error(
                            f"Cannot find result for username {username}, skipping..."
                        )
                        continue

                    # check if there is a com.tencent.mm:id/acf with text "Top" - if yes, we need an extra key_down to get to the latest articles
                    try:
                        if (
                            self.vc.findViewWithAttribute(
                                "resource-id", "com.tencent.mm:id/acf"
                            ).getText()
                            == "Top"
                        ):
                            self.bot.key_down()
                    except Exception:
                        pass

                    for article_index in range(max_articles):
                        self.logger.info(
                            f"Processing article {article_index + 1}/{max_articles} (account: {username}, {username_index}/{len(accounts)})"
                        )
                        article = Article(account=username)
                        self.bot.key_down()
                        self.bot.enter()
                        self.vc.dump()

                        # check if we are on an article view
                        article_view = self.vc.findViewWithAttribute(
                            "resource-id", "com.tencent.mm:id/l2a"
                        )
                        if not article_view:
                            # we probably tapped on the X articles remaining button, so we need to press down three times to get to the next article
                            self.bot.key_down(3)
                            self.bot.enter()
                            self.vc.dump()

                        # process the article
                        metadata = self.process_article_inner()
                        article.url = metadata["url"]
                        article.title = metadata["title"]
                        article.published_at = metadata["published_at"]
                        self.logger.info(article)
                        self.logger.info("Storing article...")
                        status = self.store_article(article)
                        if status == ArticleStoreStatus.SUCCESS:
                            articles_collected += 1
                        elif status == ArticleStoreStatus.DUPLICATE:
                            self.logger.info(
                                "Article already exists in database (duplicate URL), moving to the next profile..."
                            )
                            self.bot.go_back()
                            time.sleep(0.1)
                            break
                        elif status == ArticleStoreStatus.DATABASE_ERROR:
                            self.logger.warning(
                                "Database error occurred, retrying in 5 seconds..."
                            )
                            time.sleep(5)
                            continue
                        elif status == ArticleStoreStatus.INVALID_DATA:
                            self.logger.warning("Skipping article due to invalid data")
                            continue
                        else:  # UNEXPECTED_ERROR
                            self.logger.error(
                                "Unexpected error occurred while storing article"
                            )
                            continue

                        # go back
                        self.bot.go_back()
                        time.sleep(0.1)

                    # go back to the Official Accounts page
                    self.bot.go_back(2)
                    self.vc.dump()

            else:  # Followed accounts flow
                self.logger.warning(
                    "No accounts provided, monitoring followed accounts only. This is not fully implemented due to the complexity of the feed page (various article display formats) and may result in errors."
                )

                usernames = [
                    username_view.map.get("text", "")
                    for username_view in self.vc.findViewsWithAttribute(
                        "resource-id", "com.tencent.mm:id/lun"
                    )
                ]

                # debugging
                # usernames = ["俄罗斯卫星通讯社"]
                # usernames = ["新华社"]
                # usernames = ["中国驻安哥拉大使馆"]

                for (
                    username
                ) in usernames:  # todo!: scroll when visible usernames are exhausted
                    articles_collected_in_profile = 0

                    profile_item = self.vc.findViewWithText(username)
                    profile_item.touch()
                    time.sleep(0.1)
                    self.vc.dump()

                    # we are on the articles list now

                    def go_back_to_profiles():
                        self.bot.go_back()
                        time.sleep(0.1)
                        self.vc.dump()

                    def parse_timestamp(timestamp_string):
                        try:
                            # Get the device's timezone
                            device_tz = ZoneInfo(self.bot.get_timezone())

                            if "Yesterday" in timestamp_string:
                                # Remove "Yesterday " prefix and parse as today, then subtract one day
                                time_part = timestamp_string.replace("Yesterday ", "")
                                today_time = datetime.strptime(
                                    time_part, "%I:%M %p"
                                ).time()
                                local_dt = datetime.combine(
                                    datetime.now(device_tz).date(),
                                    today_time,
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
                                time_part = " ".join(timestamp_string.split()[1:])
                                today = datetime.now(device_tz)

                                # Convert day name to weekday number (0-6)
                                target_weekday = time.strptime(day_name, "%a").tm_wday
                                current_weekday = today.weekday()

                                # Calculate days difference
                                days_diff = (current_weekday - target_weekday) % 7
                                if days_diff == 0:
                                    days_diff = 7  # If today, it must be from last week

                                target_date = today.date() - timedelta(days=days_diff)
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
                                    datetime.now(device_tz).date(),
                                    today_time,
                                ).replace(tzinfo=device_tz)

                            # Convert to UTC timestamp
                            return local_dt.astimezone(UTC).timestamp()
                        except ValueError:
                            self.logger.error(
                                f"Failed to parse timestamp: {timestamp_string}"
                            )

                    def go_to_first_article():
                        # first is the lowest one, but we get to it with a different sequence of key events depending on what type of view it is
                        self.bot.key_down()
                        self.bot.key_up()
                        self.bot.key_down(
                            len(
                                self.vc.findViewsWithAttribute(
                                    "resource-id", "com.tencent.mm:id/byr"
                                )
                            )
                            - 1
                        )  # go down to the last item
                        # todo!: tab presses are more reliable
                        self.vc.dump()

                    go_to_first_article()

                    last_timestamp = None

                    profile_done = False

                    while (
                        articles_collected_in_profile < max_articles
                        and not profile_done
                    ):

                        def go_to_next_item():
                            # go back to the profiles list
                            self.bot.go_back()
                            self.vc.dump()
                            # click on the username again
                            profile_item = self.vc.findViewWithText(username)
                            profile_item.touch()
                            self.vc.dump()
                            # go to first article
                            go_to_first_article()
                            # now go up as many times as needed to get to the next article
                            num_up_presses = articles_collected_in_profile
                            for i in range(num_up_presses):
                                self.bot.shell("input keyevent 19")

                            self.vc.dump()

                        # find the focused element
                        focused_view = self.vc.findViewWithAttribute("focused", "true")

                        # if we are on a message, skip it
                        if (
                            focused_view.map.get("resource-id", "")
                            == "com.tencent.mm:id/bvo"
                        ):  # this means we're on a "message"
                            # get the timestamp - if it fails because it's not visible, we should be on the very first item in the feed
                            self.logger.info("This is a message, skipping...")
                            articles_collected_in_profile += 1  # todo: we're counting a skipped message as an article, fix this
                            try:
                                timestamp = parse_timestamp(
                                    self.find_in_descendants(
                                        focused_view,
                                        "resource-id",
                                        "com.tencent.mm:id/c3b",
                                    )[-1].map.get("text", "")
                                )
                            except Exception as e:
                                self.logger.info(
                                    f"Couldn't get timestamp, assuming this is the first item in the feed (error: {e})"
                                )
                                profile_done = True
                                break

                            if last_timestamp and last_timestamp == timestamp:
                                self.logger.info(
                                    "We're seeing the same message again, assuming we've reached the end of the feed..."
                                )
                                profile_done = True
                                break
                            last_timestamp = timestamp
                            go_to_next_item()
                            continue

                        article_views = []
                        is_batch = False

                        # if we are on a batch of articles, process them one by one
                        if self.find_in_descendants(
                            focused_view, "resource-id", "com.tencent.mm:id/by9"
                        ):
                            is_batch = True
                            # multiple articles under the same focused_view (bvm). ql4 is for the "hero" article, qit is used for those without thumbnails

                            # do up and down to view the whole item with the timestamp
                            self.bot.key_up()
                            self.bot.key_down()
                            self.vc.dump()

                            article_views = self.find_in_descendants(
                                focused_view, "resource-id", "com.tencent.mm:id/qit"
                            )
                            article_views += self.find_in_descendants(
                                focused_view, "resource-id", "com.tencent.mm:id/ql4"
                            )

                            timestamp_string = self.find_in_descendants(
                                focused_view.parent.parent,
                                "resource-id",
                                "com.tencent.mm:id/c3b",
                            )[
                                -1
                            ].map.get(
                                "text", ""
                            )  # for some reason, c3b is not a child of the parent (even though it looks like it in appium inspector). So we go one level up and find all the c3b elements and take the last one, which should be the one that belongs to this batch

                        else:
                            article_views = [focused_view]

                        for article_view in article_views:
                            # Create article with required fields
                            article = Article(account=username, title=None)

                            def article_already_seen():
                                if (
                                    article.key in self.seen_articles
                                    and article.key not in self.seen_articles_this_run
                                ):
                                    self.logger.info(
                                        "Article already seen, moving to next profile"
                                    )
                                    return True
                                if article.key in self.seen_articles_this_run:
                                    self.logger.info(
                                        "Reached previously seen article in this run, moving to next profile"
                                    )
                                    return True

                            if not is_batch:
                                article.title = self.find_in_descendants(
                                    article_view, "resource-id", "com.tencent.mm:id/qit"
                                )[0].map.get("text", "")
                                self.logger.info(f"Title: {article.title}")

                                c3b_views = self.find_in_siblings(
                                    article_view, "resource-id", "com.tencent.mm:id/c3b"
                                )

                                if c3b_views:
                                    timestamp = parse_timestamp(
                                        c3b_views[0].map.get("text", "")
                                    )
                                else:
                                    # go up and down to reveal the timestamp
                                    self.bot.shell("input keyevent 19")
                                    time.sleep(0.1)
                                    self.bot.shell("input keyevent 20")
                                    time.sleep(0.1)
                                    self.vc.dump()
                                    article_view = self.vc.findViewWithAttribute(
                                        "focused", "true"
                                    )
                                    timestamp = parse_timestamp(
                                        self.find_in_siblings(
                                            article_view,
                                            "resource-id",
                                            "com.tencent.mm:id/c3b",
                                        )[0].map.get("text", "")
                                    )

                                article.published_at = timestamp

                            else:  # batch format
                                article.published_at = parse_timestamp(timestamp_string)
                                article.title = article_view.map.get("text", "")
                                self.logger.info(f"Title: {article.title}")

                            # Check if we should process this article
                            if article_already_seen():
                                profile_done = True
                                break

                            # Get the article URL
                            try:
                                article.url = self.process_article(article_view)
                                time.sleep(0.1)

                                # Store the article immediately after getting URL
                                status = self.store_article(article)
                                if status == ArticleStoreStatus.SUCCESS:
                                    articles_collected_in_profile += 1
                                elif status == ArticleStoreStatus.DUPLICATE:
                                    self.logger.info(
                                        "Article already exists in database (duplicate URL)"
                                    )
                                    profile_done = True
                                    break
                                elif status == ArticleStoreStatus.DATABASE_ERROR:
                                    self.logger.warning(
                                        "Database error occurred, retrying in 5 seconds..."
                                    )
                                    time.sleep(5)
                                    continue
                                elif status == ArticleStoreStatus.INVALID_DATA:
                                    self.logger.warning(
                                        "Skipping article due to invalid data"
                                    )
                                    continue
                                else:  # UNEXPECTED_ERROR
                                    self.logger.error(
                                        "Unexpected error occurred while storing article"
                                    )
                                    continue
                            except Exception as e:
                                self.logger.error(
                                    f"Error processing or storing article: {e}"
                                )
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

                                    break
                            else:
                                self.logger.info(
                                    f"Collected {articles_collected_in_profile} articles in profile {username}"
                                )

                        if not profile_done:
                            go_to_next_item()

                    go_back_to_profiles()

            # After breaking from profiles loop, these cleanup steps will run:
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

    def get_accounts(self):
        """
        Get accounts from different sources in order of priority:
        1. Command line arguments
        2. Environment variable WECHAT_ACCOUNTS
        3. accounts.txt file (one username per line)
        Returns None if no accounts are found.
        """
        # First check command line arguments
        parser = argparse.ArgumentParser(description="WeChat Feed Monitor")
        parser.add_argument(
            "--accounts", nargs="+", help="List of WeChat accounts to monitor"
        )
        args = parser.parse_args()

        if args.accounts:
            return args.accounts

        # Then check environment variable
        accounts_env = os.getenv("WECHAT_ACCOUNTS")
        if accounts_env:
            return [acc.strip() for acc in accounts_env.split(",")]

        # Finally check accounts.txt
        accounts_file = Path("accounts.txt")
        if accounts_file.exists():
            with open(accounts_file, "r") as f:
                # Read lines and strip whitespace, filter out empty lines
                accounts = [line.strip() for line in f if line.strip()]
                if accounts:
                    return accounts

        return None


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
