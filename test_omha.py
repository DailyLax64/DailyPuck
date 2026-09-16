import urllib.request
import json
import os

league_id = 15556
url = f"https://gamesheetstats.com/api/players/standings/{league_id}?limit=5&offset=0"

raw_cookie = os.environ.get("GAMESHEET_COOKIE", "")
session_cookie = raw_cookie.strip().replace('\n', '').replace('\r', '') if raw_cookie else None

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://gamesheetstats.com/shares/dashboard'
}

if session_cookie:
    headers['Cookie'] = session_cookie
    print("Session cookie attached to headers.")
else:
    print("Warning: GAMESHEET_COOKIE not found.")

req = urllib.request.Request(url, headers=headers)

try:
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        players = data.get("data", [])
        print(f"Retrieved {len(players)} player records:\n")
        for p in players:
            name = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip()
            teams = p.get("teams", [])
            team_name = (teams[0].get("title") or teams[0].get("name", "Unknown Team")) if teams else "No Team Listed"
            print(f"- {name} | Team: {team_name} | Pos: {p.get('position', 'N/A')}")
except Exception as e:
    print(f"Fetch failed: {e}")
