WAR: WeChat Automation Robot based on ADB
===
Designed for Android WeChat app version 8.0.54.

# What is WAR? & Why WAR?
A WeChat automation script library based on [adb](https://developer.android.com/studio/command-line/adb), using pure click simulation. Supports Android devices and various operating systems that can use adb (tested on mac, ubuntu). Due to business requirements, current development mainly focuses on monitoring/scraping/operating official accounts/subscription accounts. More scripts can be added in the future, PRs welcome.

After exhausting various approaches like xposed, iPad/Mac protocols, web protocols, and WeChat hooks, we've returned to the old path of simulating human interaction. Simulating human interaction never gets banned!

# Quick Start
#### Preparation
1. Connect Android device via USB, enable debugging in developer mode, check "Allow debugging" and "Allow simulated clicks" in the device's developer options.
2. Ensure [adb](https://developer.android.com/studio/command-line/adb) command is available, use `adb devices` to get `serial` (phone serial number)
    ```shell
    $ adb devices
    List of devices attached
    fe57c975        device
    ```

#### Script 1: Subscription Account Monitor `/examples/feed_monitor.py`
1. Install clipper
    ```
    $ adb -s fe57c975 install apks/clipper1.2.1.apk
    ```
2. Monitor subscription/official account updates (must be followed) and get updated article list
    ```python
    from wechat_adb_robot.scripts.feed_monitor import WeChatFeedMonitor
    from wechat_adb_robot.lib.utils import new_stream_logger

    def push_result(url):
        print("Got new article url, push to db:", url)

    monitor = WeChatFeedMonitor(serial="fe57c975",
                                result_callback=push_result,
                                adb_path="adb",
                                logger=new_stream_logger())
    monitor.run(skip_first_batch=False)  # skip_first_batch=True to skip update detection in first loop
    ```
3. Running results:
    ```
    [14:46:57][INFO][root] => Starting loop 0
    [14:47:12][INFO][root] => Recently updated official accounts: ['金融宽课', '越甲策市', '招商汽车研究', 'IPP评论', '中国教育新闻网', '随手札记', '市川新田三丁目', '中金点睛']
    [14:47:28][INFO][root] => Output result: https://mp.weixin.qq.com/s/mPxaA9oGK5X3FNBWb2aeVQ
    [14:47:44][INFO][root] => Output result: https://mp.weixin.qq.com/s/YhQtDCRCPnhpplkWA6YtGQ
    [14:48:00][INFO][root] => Output result: https://mp.weixin.qq.com/s/Jm16fIMycBs4YT_Wn62apw
    
    ...

    [14:50:58][INFO][root] => Starting loop 1
    [14:51:14][INFO][root] => Recently updated official accounts: []
    [14:51:46][INFO][root] => Starting loop 2
    [14:52:01][INFO][root] => Recently updated official accounts: []
    [14:52:34][INFO][root] => Starting loop 3
    
    ...
    ```
    ![example.gif](https://github.com/tommyyz/wechat_adb_robot/raw/master/example.gif)

# Update Info
- 2019.06.27: Added support for new subscription page interface after version 6.7.3 (left screen in image below)
  ![compare_v672_v673.jpeg](https://github.com/tommyyz/wechat_adb_robot/raw/master/compare_v672_v673.jpeg)

# TODO List
- [x] Monitor subscription list updates and get updated article list
- [ ] Search and follow subscription accounts
- [ ] Unfollow subscription accounts
- [ ] Scrape historical articles from given list of official accounts
- [ ] Batch add friends
- [ ] Auto post to Moments
- [ ] Tell me: yuhao6066@gmail.com
