import urllib.request
import json
import os

raw_cookie = os.environ.get("GAMESHEET_COOKIE", "")
session_cookie = raw_cookie.strip().replace('\n', '').replace('\r', '') if raw_cookie else None

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://gamesheetstats.com/shares/dashboard'
}
if session_cookie:
    headers['Cookie'] = session_cookie

# Query the games endpoint for Tri-County AA (15497)
url = "https://gamesheetstats.com/api/seasons/15497/games?filter[limit]=5"
req = urllib.request.Request(url, headers=headers)

try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        games = data.get("data", [])
        print(f"✅ Success! Retrieved {len(games)} sample game records:\n")
        if games:
            print("First Game Record Structure:")
            print(json.dumps(games[0], indent=2))
        else:
            print("Response returned 0 games.")
except Exception as e:
    print(f"❌ Failed: {e}")
