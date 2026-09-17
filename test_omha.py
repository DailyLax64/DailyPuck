import urllib.request
import json
import os

raw_cookie = os.environ.get("GAMESHEET_COOKIE", "")
session_cookie = raw_cookie.strip().replace('\n', '').replace('\r', '') if raw_cookie else None

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://gamesheetstats.com/shares/dashboard',
    'Origin': 'https://gamesheetstats.com'
}
if session_cookie:
    headers['Cookie'] = session_cookie

url = "https://gamesheetstats.com/api/unified-games/15764?filter[limit]=5"
req = urllib.request.Request(url, headers=headers)

try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        raw_list = data if isinstance(data, list) else data.get("games") or data.get("data") or []
        print(f"Retrieved {len(raw_list)} records from unified-games.\n")
        if raw_list:
            print("First Game Record Raw JSON:")
            print(json.dumps(raw_list[0], indent=2))
except Exception as e:
    print(f"Fetch failed: {e}")
