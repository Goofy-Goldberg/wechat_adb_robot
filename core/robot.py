# coding:utf-8
import logging
import re
import time
from lxml import etree
import subprocess
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("adb_robot")


class WindowManager:
    def __init__(self, wm_shell):
        self.wm_shell = wm_shell
        self.width, self.height = self.get_size()

    def get_size(self):
        o = self.wm_shell("size")
        m = re.match(r".*?(\d+)x(\d+).*?", o)
        if not m:
            raise ValueError("Unable to get window dimensions: {}".format(o))
        x, y = m.groups()
        return int(x), int(y)

    def set_size(self, width, height):
        self.wm_shell("size {}x{}".format(width, height))


class ADBRobot:
    def __init__(
        self, serial, temp_dump_file="/sdcard/wechat_dump.xml", adb_path="adb"
    ):
        self.serial = serial
        self.temp_dump_file = temp_dump_file
        self.adb_path = adb_path
        self.wm = WindowManager(self.wm_shell)

    def shell(self, cmd="", decode=True):
        """
        Execute the specified cmd command
        :param cmd:
        :return:
        """
        if not cmd:
            return ""
        logger.debug("running shell: {}".format(cmd))
        proc = subprocess.Popen(
            "{} -s {} shell {}".format(self.adb_path, self.serial, cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True,
        )
        stdout, stderr = proc.communicate()
        if decode:
            stdout = stdout.decode()
            stderr = stderr.decode()
        if len(stderr) != 0:
            return stderr
        else:
            return stdout
        return stdout

    def wm_shell(self, wm_cmd=""):
        return self.shell(f"wm {wm_cmd}")

    def is_app_installed(self, app_name):
        return len(self.shell(f"pm list packages | grep {app_name}")) > 0

    def run_app(self, app_name):
        """
        app_name = "com.tencent.mm"
        """
        self.shell(
            "monkey -p {} -c android.intent.category.LAUNCHER 1".format(app_name)
        )

    def is_screen_on(self):
        result1 = self.shell("dumpsys input_method | grep mInteractive=true")
        result2 = self.shell("dumpsys input_method | grep mScreenOn=true")
        return result1 != "" or result2 != ""

    def screen_on(self):
        if not self.is_screen_on():
            self.shell("input keyevent 26")

    def unlock(self):
        # adb shell input text XXXX && adb shell input keyevent 66
        pin = os.getenv("PIN")
        if not pin:
            raise ValueError("PIN is not set")
        # repeat 66 three times with a small delay to ensure we get to the pin input
        self.shell("input keyevent 66")
        time.sleep(0.25)
        self.shell("input keyevent 66")
        time.sleep(0.25)
        self.shell("input keyevent 66")
        time.sleep(0.25)
        # enter pin
        self.shell(f"input text {pin}")
        self.shell("input keyevent 66")
        time.sleep(0.25)

    def screen_off(self):
        if self.is_screen_on():
            self.shell("input keyevent 26")

    def go_home(self):
        self.shell("input keyevent 3")

    def force_home(self):
        """
        Force reset to initial state
        """
        self.go_home()
        for _ in range(3):
            self.go_back()
        self.go_home()

    def go_back(self):
        self.shell("input keyevent 4")

    def enter(self):
        self.shell("input keyevent 66")

    def tap(self, x, y):
        self.shell("input tap {} {}".format(x, y))

    def swipe_down(self):
        """
        Swipe down half screen
        """
        self.shell(
            "input swipe {} {} {} {}".format(
                self.wm.width / 2,
                self.wm.height / 4,
                self.wm.width / 2,
                self.wm.height / 4 * 3,
            )
        )

    def swipe_up(self):
        """
        Swipe up half screen
        """
        self.shell(
            "input swipe {} {} {} {}".format(
                self.wm.width / 2,
                self.wm.height / 4 * 3,
                self.wm.width / 2,
                self.wm.height / 4,
            )
        )

    def swipe_by_distance(self, distance):
        """
        Swipe by distance - negative distance is up, positive is down
        """
        self.shell(
            "input swipe {} {} {} {}".format(
                self.wm.width / 2,
                self.wm.height
                - 300,  # start near bottom of screen to avoid triggering gestures
                self.wm.width / 2,
                self.wm.height - distance - 300,
            )
        )

    def uidump_and_get_node(self, retry_times=3):
        """
        Get current page node
        """
        node = None
        error = None

        for _ in range(retry_times):
            try:
                self.shell("uiautomator dump {}".format(self.temp_dump_file))
                dumps = self.shell("cat {}".format(self.temp_dump_file), decode=False)
                logger.debug(dumps.decode("utf-8"))
                if not dumps.startswith(b"<"):
                    raise ValueError(dumps)
                node = etree.XML(dumps)
                break
            except Exception as e:
                logger.exception(e)
                error = e

        if node is None:
            raise error
        return node

    def activity_top(self):
        """
        Determine what the current application is
        """
        return self.shell("dumpsys activity top")

    def get_node_bounds(self, attr_name, attr_value, dumps=None):
        if dumps is None:
            dumps = self.uidump_and_get_node()
        try:
            bounds = dumps.xpath(
                '//node[@{}="{}"]/@bounds'.format(attr_name, attr_value)
            )[0]
        except Exception:
            return False
        return bounds

    def get_points_in_bounds(self, bounds):
        """
        '[42,1023][126,1080]' => 42, 1023, 126, 1080
        """
        points = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]").match(bounds).groups()
        return list(map(int, points))

    def click_bounds(self, bounds):
        """
        bounds = '[42,1023][126,1080]'
        """
        # check if bounds is tuple
        if isinstance(bounds, tuple):
            self.tap(bounds[0][0] + bounds[1][0] / 2, bounds[0][1] + bounds[1][1] / 2)
        else:
            bounds_points = self.get_points_in_bounds(bounds)
            self.tap(
                (bounds_points[0] + bounds_points[2]) / 2,
                (bounds_points[1] + bounds_points[3]) / 2,
            )

    def set_clipboard_text(self, text):
        """
        Set clipboard text using Android's built-in clipboard
        """
        escaped_text = text.replace(
            '"', '\\"'
        )  # Escape quotes to prevent shell command issues
        self.shell(f'am broadcast -a clipper.set -e text "{escaped_text}"')

    def get_clipboard_text(self):
        """
        Get clipboard text using Android's built-in clipboard manager
        """
        # Copy to a temporary file since clipboard content might contain special characters
        tmp_file = "/sdcard/clipboard_content.txt"
        self.shell(f"service call clipboard 2 i32 1 > {tmp_file}")
        content = self.shell(f"cat {tmp_file}")
        self.shell(f"rm {tmp_file}")

        # Parse the service call output
        if "Parcel" in content:
            try:
                # Extract text between quotes if present
                match = re.search(r'"([^"]*)"', content)
                if match:
                    return match.group(1)
            except Exception as e:
                logger.error(f"Error parsing clipboard content: {e}")
        return ""

    def copy_to_clipboard(self, text):
        """
        Copy text to clipboard using input commands
        """
        # First, create a temporary file with the text
        tmp_file = "/sdcard/temp_text.txt"
        self.shell(f'echo "{text}" > {tmp_file}')

        # Launch a text editor (using Google Keep as an example)
        self.run_app("com.google.android.keep")
        time.sleep(1)  # Wait for app to launch

        # Create new note
        self.tap(
            self.wm.width / 2, self.wm.height - 100
        )  # Adjust coordinates as needed
        time.sleep(0.5)

        # Input the text
        self.shell(f'input text "$(cat {tmp_file})"')
        time.sleep(0.5)

        # Select all (Ctrl+A)
        self.shell("input keyevent 29 keyevent 31")  # KEYCODE_A while holding Ctrl
        time.sleep(0.5)

        # Copy (Ctrl+C)
        self.shell("input keyevent 29 keyevent 47")  # KEYCODE_C while holding Ctrl

        # Clean up
        self.shell(f"rm {tmp_file}")
        self.go_back()
        self.go_back()  # Exit Keep

    def remove_ensure_clipboard(self):
        # Remove the old ensure_clipboard method as it's no longer needed
        pass
