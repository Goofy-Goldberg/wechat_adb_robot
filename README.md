# WAR: WeChat Automation Robot based on ADB
Designed for Android WeChat app version 8.0.54.

## What is WAR? & Why WAR?
A WeChat automation script library based on [adb](https://developer.android.com/studio/command-line/adb), using pure click simulation. Supports Android devices and various operating systems that can use adb.

After exhausting various approaches like xposed, iPad/Mac protocols, web protocols, and WeChat hooks, we've returned to the old path of simulating human interaction. Simulating human interaction never gets banned!

## Quick Start
### Installation
This project was set up using [uv](https://docs.astral.sh/uv/getting-started/installation/).

I recommend using it to install the dependencies etc. - just run `uv sync` and it should create a virtual environment, activate it, and install the dependencies.

### Preparation
1. Connect Android device via USB, enable debugging in developer mode, check "Allow debugging" and "Allow simulated clicks" in the device's developer options.
2. Ensure [adb](https://developer.android.com/studio/command-line/adb) command is available
3. Ensure [scrcpy](https://github.com/Genymobile/scrcpy) is installed, use `which scrcpy` to check. Scrcpy is used to sync the clipboard, to copy article URLs.
4. Optionally create a `.env` file with specific settings (all are optional as they have defaults):

    ```
    MAX_ARTICLES=10                     # Number of articles to collect per profile (default: 10)
    COLLECTION_TIMEOUT=30               # Seconds to wait between collection loops
    PIN=<your_device_pin>               # If your device has a PIN lock (default: none)
    DEVICE_SERIAL=<your_device_serial>  # If you want to run the script on a specific device. Otherwise, the script will use the first device listed by `adb devices`. Serial is the string after `device` in `adb devices` output. (default: none)
    SKIP_APP_OPENING=true               # To speed things up in dev, skips getting to the Followed Accounts page in the app (default: false)
    SKIP_SCRCPY=true                    # If you want to run your own instance of scrcpy (default: false)
    HEADLESS=true                       # If you want to run scrcpy in headless mode. This will probably break URL retrieval (clipboard sync) (default: false)
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

## Running the API Server

The project includes a FastAPI server that provides access to the collected articles. To run it:

1. Install the required dependencies:
```bash
pip install fastapi uvicorn
```

2. Start the server:
```bash
uvicorn api.main:app --reload
```

The server will start on `http://localhost:8000`. You can access:
- The API documentation at `http://localhost:8000/docs`
- The OpenAPI specification at `http://localhost:8000/openapi.json`

## API Documentation

The script includes a FastAPI-based REST API for accessing the collected articles. The API runs on port 8000 by default.

### Endpoints

#### 1. List Articles
```http
GET /articles/
```
Returns a list of articles with optional filtering and pagination.

Query Parameters:
- `username` (optional): Filter articles by username
- `limit` (optional, default: 100): Maximum number of articles to return
- `offset` (optional, default: 0): Number of articles to skip
- `after` (optional): Only return articles with ID greater than this value

Example Response:
```json
[
  {
    "id": 1,
    "username": "chinaemb_mu",
    "title": "Article Title",
    "published_at": "1234567890",
    "timestamp": 1234567890,
    "url": "https://...",
    "display_name": "中国驻X大使馆"
  }
]
```

#### 2. Get Single Article
```http
GET /articles/{username}/{title}
```
Returns a specific article by username and title.

Example Response:
```json
{
  "id": 1,
  "username": "chinaemb_mu",
  "title": "Article Title",
  "published_at": "1234567890",
  "timestamp": 1234567890,
  "url": "https://...",
  "display_name": "中国驻X大使馆"
}
```

#### 3. List Usernames
```http
GET /usernames/
```
Returns a list of all unique usernames in the database.

Example Response:
```json
[
  "chinaemb_mu",
  "chinaemb_rw",
  "SputnikNews"
]
```

### Example Usage

1. Get the latest 50 articles:
```bash
curl "http://localhost:8000/articles/?limit=50"
```

2. Get articles after a specific ID:
```bash
curl "http://localhost:8000/articles/?after=123"
```

3. Get articles from a specific username:
```bash
curl "http://localhost:8000/articles/?username=chinaemb_mu"
```

4. Get a specific article:
```bash
curl "http://localhost:8000/articles/chinaemb_mu/Article%20Title"
```

5. Get all usernames:
```bash
curl "http://localhost:8000/usernames/"
```

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
