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

# Test 1: Check Standings structure for Tri-County AA (15497)
print("\n=== STANDINGS ENDPOINT SAMPLE (Tri-County AA: 15497) ===")
url_standings = "https://gamesheetstats.com/api/standings/15497?"
try:
    req = urllib.request.Request(url_standings, headers=headers)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        div_groups = data.get("data", [])
        if div_groups:
            first_group = div_groups[0]
            print("Division Group Top-Level Keys:", list(first_group.keys()))
            print("Division Title:", first_group.get("title") or first_group.get("name"))
            print("Division Metadata:", {k: v for k, v in first_group.items() if k != "standings"})
            
            standings_rows = first_group.get("standings", [])
            if standings_rows:
                first_row = standings_rows[0]
                print("\nStandings Row Keys:", list(first_row.keys()))
                print("Team Object Details:", json.dumps(first_row.get("team", {}), indent=2))
        else:
            print("No standings data returned.")
except Exception as e:
    print(f"Standings check failed: {e}")

# Test 2: Check Player / Team structure
print("\n=== PLAYER ENDPOINT SAMPLE ===")
url_player = "https://gamesheetstats.com/api/players/standings/15497?limit=1&offset=0"
try:
    req = urllib.request.Request(url_player, headers=headers)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        players = data.get("data", [])
        if players:
            p = players[0]
            print("Player Top-Level Keys:", list(p.keys()))
            print("Player Teams Array:", json.dumps(p.get("teams", []), indent=2))
except Exception as e:
    print(f"Player check failed: {e}")
