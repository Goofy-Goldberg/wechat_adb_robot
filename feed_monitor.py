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
        self.seen_articles = self.db.get_all_articles()
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

        # tap three dots button
        self.bot.tap(1000, 209)
        time.sleep(0.1)

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
                    self.logger.error(
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
        max_articles = int(os.getenv("MAX_ARTICLES", "0"))  # 0 means no limit
        collection_timeout = int(os.getenv("COLLECTION_TIMEOUT", "30"))  # in seconds

        # Main loop - reinitiate the app, navigate to the feed page, scroll up to the top
        while True:
            self.logger.info("Starting loop {}".format(loop_index))

            # Check if we've hit the article limit
            if max_articles > 0 and articles_collected >= max_articles:
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

            if os.getenv("FEED_TYPE", "ALL").lower() == "all":
                self.vc.dump()

                # Double tap the header to scroll up to the top of the feed
                feed_header = self.vc.findViewWithText("Subscription Account Messages")
                if feed_header:
                    feed_header.touch()
                    time.sleep(0.1)
                    feed_header.touch()
                else:
                    self.logger.warning(
                        "Cannot find feed header, scrolling up using 50 arrow up presses..."
                    )
                    # press arrow up key 50 times
                    for i in range(50):
                        self.bot.shell("input keyevent 19")
                        time.sleep(0.1)

                # Loop through the feed items

                # check if there is any element with the text "Show earlier messages"
                show_earlier_messages = self.vc.findViewWithText(
                    "Show earlier messages"
                )
                if show_earlier_messages:
                    show_earlier_messages.touch()
                    time.sleep(0.5)

                views = None
                selected_view = None

                def get_selected_view(views):
                    # todo: multiple views can have selected=true
                    for view_id in views:
                        view = self.vc.findViewById(view_id)
                        if view.map["selected"] == "true":
                            return view
                    return None

                # keep pressing the down arrow key until we've navigated to an article
                self.logger.info("Navigating to the first article...")

                while True:
                    self.bot.shell("input keyevent 20")
                    time.sleep(0.1)
                    self.vc.dump()
                    views = self.vc.getViewsById()
                    selected_view = get_selected_view(views)

                    if (
                        selected_view
                        and selected_view.getId() == "com.tencent.mm:id/axy"
                    ):
                        self.logger.info("Found article")
                        break

                # Refresh view structure
                self.logger.info("Dumping view structure")
                self.vc.dump()

                # Article loop - go through all articles in the feed
                while True:
                    # todo: for now we ignore the articles remaining button. Hopefully we'll have read the articles by the time of the collection script anyway. It requires a different loop to go through the ql7 and qkk title views within the box with the remaining articles.

                    # # Check for "articles(s) remainig"
                    # # loop through all views and check if there is a view with the text "articles(s) remainig"
                    # articles_remaining_view = None
                    # for view_id in views:
                    #     view = self.vc.findViewById(view_id)
                    #     if (
                    #         view.map.get("text", "")
                    #         .lower()
                    #         .endswith("article(s) remaining")
                    #     ):  # the resource-id is com.tencent.mm:id/ov_, but we're using the text to find views wherever possible to avoid having to update the script when the app is updated (and presumably the resource-id changes)
                    #         self.logger.info("Found 'article(s) remaining'")
                    #         articles_remaining_view = view
                    #         break

                    # if articles_remaining_view:
                    #     articles_remaining_view.touch()
                    #     time.sleep(0.5)
                    #     # arrow up once to go back up
                    #     # todo: (this presumes the articles remaining button was under the last article we processed...)
                    #     self.bot.shell("input keyevent 19")
                    #     time.sleep(0.1)

                    # now we should be on the article, or rather on the account name view (axy). We'll get the metadata now.

                    selected_view = get_selected_view(views)

                    self.logger.info("Getting article metadata")

                    article_metadata = {}

                    while "title" not in article_metadata:
                        # find the username (lu8), timestamp (qdv) and title (ozs or qkk) and add them to the article_metadata dictionary

                        # note: it would be great if we could simply get the parent of the selected view, but for some reason the parent is the whole ListView with all the articles, even if the first selected axy view is displayed as under a LinearLayout in Appium Inspector

                        # find selected views
                        selected_views = []
                        views = self.vc.getViewsById()
                        for view_id in views:
                            view = self.vc.findViewById(view_id)
                            if view.map.get("selected", "false") == "true":
                                selected_views.append(view)

                        for selected_view in selected_views:
                            if selected_view.map.get("resource-id", "").endswith("lu8"):
                                article_metadata["account"] = selected_view.map.get(
                                    "text", ""
                                )
                            elif selected_view.map.get("resource-id", "").endswith(
                                "ozs"
                            ) or selected_view.map.get("resource-id", "").endswith(
                                "qkk"
                            ):
                                article_metadata["title"] = selected_view.map.get(
                                    "text", ""
                                )
                            elif selected_view.map.get("resource-id", "").endswith(
                                "mtd"
                            ):
                                thumbnail_view = selected_view

                        if "title" not in article_metadata:
                            self.logger.info(
                                "Navigation: Pressing down arrow key to reveal full title and up again"
                            )
                            self.bot.shell("input keyevent 20")
                            time.sleep(0.2)
                            # # press arrow up to go back
                            # self.bot.shell("input keyevent 19")
                            # time.sleep(0.2)
                            # self.bot.shell("input keyevent 20")
                            # time.sleep(0.2)
                            self.logger.info("Dumping view structure after navigation")
                            # refresh view info
                            self.vc.dump()

                    self.logger.info(f"Found article metadata: {article_metadata}")

                    # check if article in seen_articles
                    article_key = (
                        f"{article_metadata['account']}:{article_metadata['title']}"
                    )
                    if (
                        article_key in self.seen_articles
                        and article_key not in self.seen_articles_this_run
                    ):
                        self.logger.info("Article already seen, ending collection")
                        break  # Break the article loop, continue with main loop

                    if article_key in self.seen_articles_this_run:
                        self.logger.info(
                            "Reached previously seen article in this run - we've hit the end of the feed. Ending collection."
                        )
                        break  # Break the article loop, continue with main loop

                    # Open the article
                    article_url = self.process_article(
                        thumbnail_view
                    )  # todo: verify that this is working
                    article_metadata["url"] = article_url

                    # Mark as seen
                    article_record = {
                        "account": article_metadata["account"],
                        "title": article_metadata["title"],
                        "timestamp": article_metadata["timestamp"],
                        "first_seen": time.time(),
                        "url": article_metadata["url"],
                    }
                    article_key = (
                        f"{article_metadata['account']}:{article_metadata['title']}"
                    )

                    # Add to database and update local cache
                    if self.db.add_article(
                        article_metadata["account"],
                        article_metadata["title"],
                        article_metadata["timestamp"],
                        article_metadata["url"],
                    ):
                        self.seen_articles[article_key] = article_record
                        self.seen_articles_this_run[article_key] = article_record

                    articles_collected += 1
                    if max_articles > 0:
                        self.logger.info(
                            f"Collected {articles_collected}/{max_articles} articles"
                        )
                        if articles_collected >= max_articles:
                            self.logger.info(
                                "Maximum article limit reached, ending collection"
                            )
                            break  # Break the article loop, continue with main loop

                    # move to next article

                    self.logger.info(
                        "Navigation: Pressing down arrow key twice to move to next article (once to activate the selection, once to move to the next article)"
                    )
                    self.bot.shell("input keyevent 20")
                    time.sleep(0.1)
                    self.bot.shell("input keyevent 20")
                    time.sleep(0.2)
                    self.logger.info("Dumping view structure after navigation")
                    self.vc.dump()
                    views = self.vc.getViewsById()

            if os.getenv("FEED_TYPE", "ALL").lower() == "profiles":
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
                    self.vc.dump()
                except ViewNotFoundException:
                    self.logger.error(
                        "View with text 'Followed Official Accounts' not found."
                    )

                # profile_items = self.vc.findViewsWithAttribute(
                #     "resource-id", "com.tencent.mm:id/cyr"
                # )

                usernames = [
                    username_view.map.get("text", "")
                    for username_view in self.vc.findViewsWithAttribute(
                        "resource-id", "com.tencent.mm:id/lun"
                    )
                ]

                for (
                    username
                ) in usernames:  # todo!: scroll when visible usernames are exhausted
                    profile_item = self.vc.findViewWithText(username)
                    profile_item.touch()
                    time.sleep(0.1)

                    username = usernames[i]

                    # we are on the articles list now

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

                    profile_done = False

                    articles_by_username = {}

                    while not profile_done:
                        # now let's get the article metadata
                        article_metadata = {"username": username}

                        # find the focused element (where focused = true)
                        focused_view = self.vc.findViewWithAttribute("focused", "true")
                        if focused_view:
                            self.logger.info(f"Focused view: {focused_view.map}")

                        # find the title (com.tencent.mm:id/qit) in children recursively
                        def find_title(view):
                            if (
                                view.map.get("resource-id", "")
                                == "com.tencent.mm:id/qit"
                            ):
                                return view.map.get("text", "")
                            for child in view.children:
                                result = find_title(child)
                                if result:
                                    return result
                            return None

                        article_metadata["title"] = find_title(focused_view)
                        self.logger.info(f"Title: {article_metadata.get('title')}")

                        # find the timestamp - it's a sibling of the focused view with the id com.tencent.mm:id/c3b
                        siblings = focused_view.parent.children
                        for sibling in siblings:
                            if (
                                sibling.map.get("resource-id", "")
                                == "com.tencent.mm:id/c3b"
                            ):
                                article_metadata["timestamp"] = sibling.map.get(
                                    "text", ""
                                )
                                break

                        self.logger.info(
                            f"Timestamp: {article_metadata.get('timestamp')}"
                        )

                        if username not in articles_by_username:
                            articles_by_username[username] = []

                        articles_by_username[username].append(article_metadata)

                        if len(articles_by_username[username]) >= int(
                            os.getenv("MAX_ARTICLES_PER_PROFILE", "10")
                        ):
                            profile_done = True

                        # check if the last article is already in the database
                        if article_metadata["title"] in self.seen_articles:
                            profile_done = True

                        # tap the focused view to open the article
                        article_metadata["url"] = self.process_article(focused_view)
                        time.sleep(0.1)

                        # todo! store the article

                        # navigate up
                        self.bot.shell("input keyevent 19")
                        time.sleep(0.1)
                        self.vc.dump()

                    # go back to the profiles list
                    self.bot.go_back()
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
