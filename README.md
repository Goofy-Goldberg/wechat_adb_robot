# WAR: WeChat Automation Robot based on ADB
Designed for Android WeChat app version 8.0.54.

## What is WAR? & Why WAR?
A WeChat automation script library based on [adb](https://developer.android.com/studio/command-line/adb), using pure click simulation. Supports Android devices and various operating systems that can use adb.

After exhausting various approaches like xposed, iPad/Mac protocols, web protocols, and WeChat hooks, we've returned to the old path of simulating human interaction. Simulating human interaction never gets banned!

## Quick Start
### Installation
This project was set up using [uv](https://docs.astral.sh/uv/getting-started/installation/).

I recommend using it to install the dependencies etc. - just run `uv sync` and it should create a virtual environment and install the dependencies. (You should still activate the virtual environment yourself as usual - `./.venv/bin/activate`).

#### Note:

On first run, you may see warnings like these:

```
/Users/user/Tools/wechat_adb_robot/.venv/lib/python3.13/site-packages/com/dtmilano/android/common.py:35: SyntaxWarning: invalid escape sequence '\d'
  return '(?P<%s>\d+)' % name
/Users/user/Tools/wechat_adb_robot/.venv/lib/python3.13/site-packages/com/dtmilano/android/common.py:56: SyntaxWarning: invalid escape sequence '\S'
  return '(?P<%s>\S+%s)' % (name, '' if greedy else '?')
/Users/user/Tools/wechat_adb_robot/.venv/lib/python3.13/site-packages/com/dtmilano/android/common.py:128: SyntaxWarning: invalid escape sequence '\P'
  possibleChoices.append(os.path.join("""C:\Program Files\Android\android-sdk\platform-tools""", adb))
/Users/user/Tools/wechat_adb_robot/.venv/lib/python3.13/site-packages/com/dtmilano/android/common.py:129: SyntaxWarning: invalid escape sequence '\P'
  possibleChoices.append(os.path.join("""C:\Program Files (x86)\Android\android-sdk\platform-tools""", adb))
```

These seem to be harmless in our case and can be ignored.

### Preparation
1. Connect Android device via USB, enable debugging in developer mode, check "Allow debugging" and "Allow simulated clicks" in the device's developer options.
2. Ensure [adb](https://developer.android.com/studio/command-line/adb) command is available
3. Ensure [scrcpy](https://github.com/Genymobile/scrcpy) is installed, use `which scrcpy` to check. Scrcpy is used to sync the clipboard, to copy article URLs.
4. Optionally create a `.env` file with specific settings (all are optional as they have defaults, except for the Elasticsearch configuration):

    ```
    MAX_ARTICLES=10                     # Number of articles to collect per profile (default: 10)
    COLLECTION_TIMEOUT=30               # Seconds to wait between collection loops
    PIN=<your_device_pin>               # If your device has a PIN lock (default: none)
    DEVICE_SERIAL=<your_device_serial>  # If you want to run the script on a specific device. Otherwise, the script will use the first device listed by `adb devices`. Serial is the string after `device` in `adb devices` output. (default: none)
    SKIP_APP_OPENING=true               # To speed things up in dev, skips getting to the Followed Accounts page in the app (default: false)
    SKIP_SCRCPY=true                    # If you want to run your own instance of scrcpy (default: false)
    HEADLESS=true                       # If you want to run scrcpy in headless mode. This will probably break URL retrieval (clipboard sync) (default: false)
    ES_HOST=localhost                  # Elasticsearch host (default: localhost - has to be set explicitly to enable fetching accounts from Elasticsearch)
    ES_PORT=9200                       # Elasticsearch port (default: 9200)
    ES_USERNAME=elastic               # Elasticsearch username (optional)
    ES_PASSWORD=changeme             # Elasticsearch password (optional)
    ES_VERIFY_CERTS=false           # Whether to verify SSL certificates (default: false)
    SKIP_DUPLICATES=false             # Whether to skip duplicate (already seen) articles (default: true)
    API_HOST=localhost               # API host (for storing articles in Elasticsearch) (default: localhost)
    API_PORT=8000                    # API port (default: 8000)
    ```

### Running the Script
The script can monitor WeChat official accounts in three ways:

1. **Command Line Arguments**
   ```bash
   python feed_monitor.py --usernames chinaemb_mu chinaemb_rw SputnikNews
   ```

2. **Environment Variable**
   In your `.env` file or exported:
   ```bash
   USERNAMES=chinaemb_mu,chinaemb_rw,SputnikNews
   ```

3. **Elasticsearch**
   If you have Elasticsearch configured (via environment variables), the script will fetch accounts from the `accounts` index. Each document in the index should have a `username` field.

4. **Text File**
   Create a `usernames.txt` file with one username per line:
   ```
   chinaemb_mu
   chinaemb_rw
   SputnikNews
   ```

If no accounts are specified through any of these methods, the script will monitor all accounts you follow in WeChat (not recommended).

### Notes
- Usernames (Weixin IDs) are not case-sensitive
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

## Environment Variables

Create a `.env` file with specific settings (all are optional as they have defaults):

```
MAX_ARTICLES=10                     # Number of articles to collect per profile (default: 10)
COLLECTION_TIMEOUT=30               # Seconds to wait between collection loops
PIN=<your_device_pin>               # If your device has a PIN lock (default: none)
DEVICE_SERIAL=<your_device_serial>  # If you want to run the script on a specific device. Otherwise, the script will use the first device listed by `adb devices`. Serial is the string after `device` in `adb devices` output. (default: none)
SKIP_APP_OPENING=true               # To speed things up in dev, skips getting to the Followed Accounts page in the app (default: false)
SKIP_SCRCPY=true                    # If you want to run your own instance of scrcpy (default: false)
HEADLESS=true                       # If you want to run scrcpy in headless mode. This will probably break URL retrieval (clipboard sync) (default: false)

# Elasticsearch configuration (optional)
ES_HOST=localhost                  # Elasticsearch host (default: localhost)
ES_PORT=9200                       # Elasticsearch port (default: 9200)
ES_USERNAME=elastic               # Elasticsearch username (optional)
ES_PASSWORD=changeme             # Elasticsearch password (optional)
ES_VERIFY_CERTS=false           # Whether to verify SSL certificates (default: false)
```

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
