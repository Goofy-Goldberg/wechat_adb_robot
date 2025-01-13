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
        self.seen_articles_this_run = {}

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

            # Check if skip navigation is not true
            if (
                not os.getenv("SKIP_NAVIGATION", "").lower() == "true"
            ):  # useful for debugging to skip the long navigation, if you can ensure you're on the right page
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

            # Loop through the feed items

            self.vc.dump()

            # check if there is any element with the text "Show earlier messages"
            show_earlier_messages = self.vc.findViewWithText("Show earlier messages")
            if show_earlier_messages:
                show_earlier_messages.touch()
                time.sleep(0.5)

            # press arrow down key three times to navigate to the listing
            for i in range(3):
                self.logger.info(
                    f"Initial navigation: Pressing down arrow key ({i+1}/3)"
                )
                self.bot.shell("input keyevent 20")
                time.sleep(0.1)

            # Refresh view structure
            self.logger.info("Dumping view structure")
            self.vc.dump()

            while True:
                views = self.vc.getViewsById()

                # # Get header views
                # header_views = []
                # for view_id in views:
                #     view = self.vc.findViewById(view_id)
                #     if view.map[
                #         "resource-id"
                #     ].endswith(
                #         "axy"
                #     ):  # nb: axy refers to the username view in the feed item, not the feed item/article itself
                #         header_views.append(view)

                article_ready_to_process = False

                while (
                    not article_ready_to_process
                ):  # loop until we navigate to an article
                    selected_view = None

                    for view_id in views:
                        view = self.vc.findViewById(view_id)
                        if view.map["selected"] == "true":
                            selected_view = view
                            break

                    if selected_view:
                        if selected_view.getId() != "com.tencent.mm:id/axy":
                            self.logger.info(
                                f"selected view {selected_view.getId()} is not an article: moving down..."
                            )
                            self.logger.info(
                                "Navigation: Pressing down arrow key to find article"
                            )
                            self.bot.shell("input keyevent 20")
                            time.sleep(0.2)
                            self.logger.info("Dumping view structure after navigation")
                            self.vc.dump()
                            views = self.vc.getViewsById()
                        else:
                            # now we are on the article, or rather on the account name view (axy). We'll get the metadata now.

                            self.logger.info("Getting article metadata")

                            metadata_complete = False  # if the title isn't fully visible, we'll have go down again... there doesn't seem to be a more elegant way of testing this though

                            while not metadata_complete:
                                siblings = self.vc.findViewById(
                                    selected_view.parent.getUniqueId()
                                ).children

                                # axa is on the same level as aq0, which then contains the account name (username) in lu8 and the timestamp in qdv. From there we will also jump to the next sibling to get the title

                                found_current = False
                                view = None

                                for sibling in siblings:
                                    # check if we are on the selected view (axa)
                                    if sibling == selected_view:
                                        found_current = True
                                    elif found_current:
                                        if sibling.getId() == "com.tencent.mm:id/aq0":
                                            view = sibling
                                            break

                                if not view:
                                    self.logger.error(
                                        "Cannot find aq0 view"
                                    )  # todo: handle better
                                    break

                                # Find header containers
                                article_metadata = {}

                                # Recursive function to search through children
                                def find_in_children(view, article_metadata):
                                    if view.map.get("resource-id", "").endswith("lu8"):
                                        article_metadata["account"] = view.map.get(
                                            "text", ""
                                        )
                                    elif view.map.get("resource-id", "").endswith(
                                        "qdv"
                                    ):
                                        article_metadata["timestamp"] = view.map.get(
                                            "text", ""
                                        )

                                    for child in view.getChildren():
                                        find_in_children(child, article_metadata)

                                # Search through this container's children
                                find_in_children(view, article_metadata)

                                # Look for title in next sibling container
                                if (
                                    "account" in article_metadata
                                    and "timestamp" in article_metadata
                                ):
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
                                                def find_title_view(view):
                                                    if (
                                                        view.map.get(
                                                            "resource-id", ""
                                                        ).endswith("ozs")
                                                        or view.map.get(
                                                            "resource-id", ""
                                                        ).endswith("qkk")
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
                                                    article_metadata["title"] = (
                                                        title_view.getText()
                                                    )
                                                    self.logger.info(
                                                        f"Found article: {article_metadata}"
                                                    )
                                                    article_ready_to_process = True
                                                    break  # stop processing siblings
                                                else:  # title not visible, so we'll have to go down again
                                                    self.logger.info(
                                                        "Navigation: Pressing down arrow key to reveal full title"
                                                    )
                                                    self.bot.shell("input keyevent 20")
                                                    time.sleep(0.2)
                                                    self.logger.info(
                                                        "Dumping view structure after navigation"
                                                    )
                                                    self.vc.dump()
                                                    views = self.vc.getViewsById()
                                                    for view_id in views:
                                                        view = self.vc.findViewById(
                                                            view_id
                                                        )
                                                        if (
                                                            view.map["selected"]
                                                            == "true"
                                                        ):
                                                            selected_view = view

                # check if article in seen_articles
                article_key = (
                    f"{article_metadata['account']}:{article_metadata['title']}"
                )
                if (
                    article_key in self.seen_articles
                    and article_key not in self.seen_articles_this_run
                ):  # we do not want to stop if we are simply on the same article again without it being actually old
                    self.logger.info("Article already seen, skipping")
                    break

                if article_key in self.seen_articles_this_run:
                    self.logger.info(
                        "We're still on an article that we've seen before in this run, moving on..."
                    )  # todo!: somethings's wrong here, we are always on the previous article it seems even though a single down key press should move us to the next article if the whole article is visible. Additionally, when the article should open, it doesn't, so we're probably either selecting some other view or not updating its bounds correctly
                    self.logger.info(
                        "Navigation: Pressing down arrow key to move to next article"
                    )
                    self.bot.shell("input keyevent 20")
                    time.sleep(0.2)
                    self.logger.info("Dumping view structure after navigation")
                    self.vc.dump()
                    views = self.vc.getViewsById()
                    continue

                # Open the article
                self.logger.info("Opening article")
                title_view.touch()

                # Process the article
                self.logger.info("Processing article [incomplete implementation]")
                time.sleep(0.5)

                # tap three dots button
                self.bot.tap(1000, 209)
                time.sleep(0.5)

                # tap copy link button
                self.bot.tap(850, 1960)
                time.sleep(0.3)

                # swipe to dismiss the clipboard popup
                self.bot.swipe(start_x=250, start_y=2220, dx=-100)
                time.sleep(0.1)

                self.bot.go_back()
                time.sleep(0.5)

                # Mark as seen
                article_record = {
                    "timestamp": article_metadata["timestamp"],
                    "first_seen": time.time(),
                }
                article_key = (
                    f"{article_metadata['account']}:{article_metadata['title']}"
                )
                self.seen_articles[article_key] = article_record
                self.seen_articles_this_run[article_key] = article_record
                self._save_seen_articles()

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


def push_result(url):
    self.logger.info("Got new article url:", url)


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
