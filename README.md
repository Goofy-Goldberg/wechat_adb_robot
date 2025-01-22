WAR: WeChat Automation Robot based on ADB
===
Designed for Android WeChat app version 8.0.54.

# What is WAR? & Why WAR?
A WeChat automation script library based on [adb](https://developer.android.com/studio/command-line/adb), using pure click simulation. Supports Android devices and various operating systems that can use adb (tested on mac, ubuntu). Due to business requirements, current development mainly focuses on monitoring/scraping/operating official accounts/subscription accounts. More scripts can be added in the future, PRs welcome.

After exhausting various approaches like xposed, iPad/Mac protocols, web protocols, and WeChat hooks, we've returned to the old path of simulating human interaction. Simulating human interaction never gets banned!

# Quick Start
### Preparation
1. Connect Android device via USB, enable debugging in developer mode, check "Allow debugging" and "Allow simulated clicks" in the device's developer options.
2. Ensure [adb](https://developer.android.com/studio/command-line/adb) command is available, use `adb devices` to get `serial` (phone serial number)
    ```shell
    $ adb devices
    List of devices attached
    fe57c975        device
    ```
3. Create a `.env` file with your device serial:
    ```
    DEVICE_SERIAL=your_device_serial
    PIN=your_device_pin  # Optional: if your device has a PIN lock
    MAX_ARTICLES=10      # Number of articles to collect per profile (default: 10)
    COLLECTION_TIMEOUT=30 # Optional: seconds to wait between collection loops
    ```

### Running the Script
The script can monitor WeChat official accounts in two ways:

1. **Monitor Specific Accounts**
   You can specify accounts to monitor in three ways:

   a. Command line arguments:
   ```bash
   python feed_monitor.py --accounts chinaemb_mu chinaemb_rw SputnikNews
   ```

   b. Environment variable (in .env file or exported):
   ```bash
   WECHAT_ACCOUNTS=chinaemb_mu,chinaemb_rw,SputnikNews
   ```

   c. Text file (accounts.txt):
   ```
   chinaemb_mu
   chinaemb_rw
   SputnikNews
   ```

   The script checks for accounts in this order of priority:
   1. Command line arguments
   2. WECHAT_ACCOUNTS environment variable
   3. accounts.txt file

2. **Monitor Followed Accounts** (not recommended)
   - Simply run the script without specifying any accounts:
     ```bash
     python feed_monitor.py
     ```
   - This will monitor all accounts you follow in WeChat
   - This is not recommended as the implementation is imperfect due to the complexity of the feed page (various article display formats) and may result in errors

### Notes
- The script will automatically use the search flow when specific accounts are provided, and the followed accounts flow when no accounts are specified
- The followed accounts flow is more complex due to various article display formats and may be less reliable
- For best results, use the search flow with specific accounts

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
