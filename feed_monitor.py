# coding:utf-8
import time
import os
from com.dtmilano.android.viewclient import ViewClient, AdbClient
from dotenv import load_dotenv
from lib.utils import new_stream_logger
from core.robot import ADBRobot
import pyperclip
from lib.db import ArticleDB


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
            show_earlier_messages = self.vc.findViewWithText("Show earlier messages")
            if show_earlier_messages:
                show_earlier_messages.touch()
                time.sleep(0.5)

            views = None
            selected_view = None

            def get_selected_view(views):
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

                if selected_view and selected_view.getId() == "com.tencent.mm:id/axy":
                    self.logger.info("Found article")
                    break

            # Refresh view structure
            self.logger.info("Dumping view structure")
            self.vc.dump()

            clipboard = None  # initialise clipboard - useful to compare with previously copied text to ensure we got the latest URL copied

            # Article loop - go through all articles in the feed
            while True:
                # Check for "articles(s) remainig"
                # loop through all views and check if there is a view with the text "articles(s) remainig"
                articles_remaining_view = None
                for view_id in views:
                    view = self.vc.findViewById(view_id)
                    if (
                        view.map.get("text", "")
                        .lower()
                        .endswith("articles(s) remainig")
                    ):
                        self.logger.info("Found 'articles(s) remainig'")
                        break

                if articles_remaining_view:
                    articles_remaining_view.touch()
                    time.sleep(0.5)

                # now we should be on the article, or rather on the account name view (axy). We'll get the metadata now.

                selected_view = get_selected_view(views)

                self.logger.info("Getting article metadata")

                metadata_complete = False  # if the title isn't fully visible, we'll have go down again... there doesn't seem to be a more elegant way of testing this though

                while not metadata_complete:
                    siblings = self.vc.findViewById(
                        selected_view.parent.getUniqueId()
                    ).children

                    # axa is on the same level as aq0, which then contains the account name (username) in lu8 and the timestamp in qdv. From there we will also jump to the next sibling to get the title

                    found_current = False
                    view_aq0 = None

                    for sibling in siblings:
                        # check if we are on the selected view (axa)
                        if sibling == selected_view:
                            found_current = True
                        elif found_current:  # the previous sibling was the selected view (axa), so we're on the next sibling, which should be aq0
                            if sibling.getId() == "com.tencent.mm:id/aq0":
                                view_aq0 = sibling
                                break

                    if not view_aq0:
                        self.logger.error("Cannot find aq0 view")  # todo: handle better
                        break

                    # Find header containers
                    article_metadata = {}

                    # Recursive function to search through children
                    def find_in_children(view, article_metadata):
                        if view.map.get("resource-id", "").endswith("lu8"):
                            article_metadata["account"] = view.map.get("text", "")
                        elif view.map.get("resource-id", "").endswith("qdv"):
                            article_metadata["timestamp"] = view.map.get("text", "")

                        for child in view.getChildren():
                            find_in_children(child, article_metadata)

                    # Search through this container's children
                    find_in_children(view_aq0, article_metadata)

                    # Look for title in next sibling container
                    if (
                        "account" in article_metadata
                        and "timestamp" in article_metadata
                    ):
                        parent = view_aq0.getParent()
                        if parent:
                            siblings = parent.getChildren()
                            found_current = False
                            for sibling in siblings:
                                if sibling == view_aq0:
                                    found_current = True
                                    continue
                                if found_current:
                                    # Look for title in this container's children
                                    def find_title_view(view):
                                        if (
                                            view.map.get("resource-id", "").endswith(
                                                "ozs"
                                            )
                                            or view.map.get("resource-id", "").endswith(
                                                "qkk"
                                            )
                                        ):  # ozs for regular title, qkk for a title with a secondary small thumbnail
                                            return view
                                        for child in view.getChildren():
                                            title = find_title_view(child)
                                            if title:
                                                return title
                                        return None

                                    title_view = find_title_view(sibling)
                                    if title_view:
                                        metadata_complete = True
                                        article_metadata["title"] = title_view.getText()
                                        self.logger.info(
                                            f"Found article: {article_metadata}"
                                        )
                                        break  # stop processing siblings
                                    else:  # title not visible, so we'll have to go down again
                                        self.logger.info(
                                            "Navigation: Pressing down arrow key to reveal full title and up again"
                                        )
                                        self.bot.shell("input keyevent 20")
                                        time.sleep(0.2)
                                        # press arrow up to go back
                                        self.bot.shell("input keyevent 19")
                                        time.sleep(0.2)
                                        self.bot.shell("input keyevent 20")
                                        time.sleep(0.2)
                                        self.logger.info(
                                            "Dumping view structure after navigation"
                                        )
                                        # refresh view info
                                        self.vc.dump()
                                        views = self.vc.getViewsById()
                                        selected_view = get_selected_view(views)
                                        for view_id in views:
                                            view_aq0 = self.vc.findViewById(view_id)
                                            if view_aq0.map["selected"] == "true":
                                                selected_view = view_aq0

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
                self.logger.info("Opening article")
                title_view.touch()

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
                    elif clipboard_new != clipboard:
                        article_metadata["url"] = clipboard_new
                        clipboard = clipboard_new
                        got_url = True
                    else:
                        self.logger.info("Clipboard did not change, retrying...")

                # swipe to dismiss the clipboard popup
                self.bot.swipe(start_x=250, start_y=2220, dx=-100)
                time.sleep(0.1)

                self.bot.go_back()
                time.sleep(0.5)

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

    monitor = WeChatFeedMonitor(
        serial=device_serial,
        adb_path="adb",
        logger=new_stream_logger(),
    )
    monitor.run(skip_first_batch=False)
