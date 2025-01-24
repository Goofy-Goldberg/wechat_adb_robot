WAR: WeChat Automation Robot based on ADB
===
Designed for Android WeChat app version 8.0.54.

# What is WAR? & Why WAR?
A WeChat automation script library based on [adb](https://developer.android.com/studio/command-line/adb), using pure click simulation. Supports Android devices and various operating systems that can use adb.

After exhausting various approaches like xposed, iPad/Mac protocols, web protocols, and WeChat hooks, we've returned to the old path of simulating human interaction. Simulating human interaction never gets banned!

# Quick Start
### Preparation
1. Connect Android device via USB, enable debugging in developer mode, check "Allow debugging" and "Allow simulated clicks" in the device's developer options.
2. Ensure [adb](https://developer.android.com/studio/command-line/adb) command is available
3. Ensure [scrcpy](https://github.com/Genymobile/scrcpy) is installed, use `which scrcpy` to check. Scrcpy is used to sync the clipboard, to copy article URLs.
4. Optionally create a `.env` file with specific settings:

    ```
    MAX_ARTICLES=10                     # Number of articles to collect per profile (default: 10)
    COLLECTION_TIMEOUT=30               # Optional: seconds to wait between collection loops
    PIN=your_device_pin                 # Optional: if your device has a PIN lock
    DEVICE_SERIAL=your_device_serial    # Optional: if you want to specify a specific device. Otherwise, the script will use the first device listed by `adb devices`. Serial is the string after `device` in `adb devices` output.
    SKIP_APP_OPENING=false              # Optional: to speed things up in dev, skips getting to the Followed Accounts page in the app
    SKIP_SCRCPY=true                    # Optional: if you want to run your own instance of scrcpy (default: false)
    HEADLESS=true                       # Optional: if you want to run scrcpy in headless mode. This will probably break URL retrieval (clipboard sync) (default: false)
    ```

### Running the Script
The script can monitor WeChat official accounts in two ways:

1. **Monitor Specific Accounts**
   You can specify accounts to monitor in three ways, and the script will check for them in this order of priority:

   a. Command line arguments:
   ```bash
   python feed_monitor.py --usernames chinaemb_mu chinaemb_rw SputnikNews
   ```

   b. Environment variable (in .env file or exported):
   ```bash
   USERNAMES=chinaemb_mu,chinaemb_rw,SputnikNews
   ```

   c. Text file (usernames.txt):
   ```
   chinaemb_mu
   chinaemb_rw
   SputnikNews
   ```

2. **Monitor Followed Accounts** (not recommended)
   - Simply run the script without specifying any accounts:
     ```bash
     python feed_monitor.py
     ```
   - This will monitor all accounts you follow in WeChat
   - This is not recommended as the implementation is imperfect due to the complexity of the feed page (various article display formats) and may result in errors

### Notes
- The script will automatically use the search flow when specific accounts are provided (i.e. no need to follow the accounts first), and the followed accounts flow when no accounts are specified
- The followed accounts flow is more complex due to various article display formats and may be less reliable
- For best results, use the search flow with specific accounts


# Tips

## ADB over WiFi

There is a utility script that will try to connect to an Android device over WiFi.

1. Start with the device connected through USB
2. Run the script: `./adb-wifi.sh`
3. Wait for the script to finish with `Connected successfully!`
4. Unplug the USB cable

Alternatively, you can use the following one-liner, but it's less robust (no retries, hardcoded 5-second wait):

```
adb tcpip 5555 && sleep 5 && adb connect $(adb shell ip -f inet addr show wlan0 | grep inet | awk '{print $2}' | cut -d/ -f1):5555
```
