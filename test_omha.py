import urllib.request
import json
import os

raw_cookie = os.environ.get("GAMESHEET_COOKIE", "")
session_cookie = raw_cookie.strip().replace('\n', '').replace('\r', '') if raw_cookie else None

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://gamesheetstats.com/shares/dashboard'
}
if session_cookie:
    headers['Cookie'] = session_cookie

# Test Tri-County AA (15497) Schedule
url = "https://gamesheetstats.com/api/useSchedule/getSeasonSchedule/15497?filter[limit]=5"
req = urllib.request.Request(url, headers=headers)

try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        games = data.get("data", [])
        print(f"Retrieved {len(games)} sample game records:\n")
        for g in games[:3]:
            print(json.dumps(g, indent=2))
except Exception as e:
    print(f"Schedule fetch failed: {e}")
