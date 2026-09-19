import urllib.request
import urllib.error
import json
import os

# 1. Setup Session Authentication & Headers
FIREBASE_API_KEY = "AIzaSyCk5pKBFxvCMuwPchzXgvvz4XmmscJTvs8"
AUTH_GATEWAY_URL = "https://gateway-authserver-awy26srzoa-nn.a.run.app/auth/v4/tokens"

GAMESHEET_EMAIL = os.environ.get("GAMESHEET_EMAIL", "").strip()
GAMESHEET_PASSWORD = os.environ.get("GAMESHEET_PASSWORD", "").strip()
FALLBACK_AUTH = os.environ.get("GAMESHEET_AUTH", "").strip()
FALLBACK_COOKIE = os.environ.get("GAMESHEET_COOKIE", "").strip()

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://gamesheetstats.com/shares/dashboard',
    'Origin': 'https://gamesheetstats.com'
}

def get_auth_token():
    if not (GAMESHEET_EMAIL and GAMESHEET_PASSWORD):
        return None
    try:
        fb_url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
        fb_payload = json.dumps({"email": GAMESHEET_EMAIL, "password": GAMESHEET_PASSWORD, "returnSecureToken": True}).encode('utf-8')
        fb_req = urllib.request.Request(fb_url, data=fb_payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(fb_req, timeout=15) as resp:
            id_token = json.loads(resp.read().decode('utf-8')).get("idToken")
        
        gw_req = urllib.request.Request(AUTH_GATEWAY_URL, headers={"Authorization": f"Bearer {id_token}", "Origin": "https://gamesheet.app", "User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(gw_req, timeout=15) as resp:
            return json.loads(resp.read().decode('utf-8')).get("access")
    except Exception as e:
        print(f"Auth error: {e}")
        return None

token = get_auth_token()
if token:
    headers['Authorization'] = f"Bearer {token}"
    headers['Cookie'] = f"__session={token}"
elif FALLBACK_AUTH:
    headers['Authorization'] = FALLBACK_AUTH
    if FALLBACK_COOKIE:
        headers['Cookie'] = FALLBACK_COOKIE

def fetch_json(url):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as he:
        return {"_error_code": he.code, "_reason": str(he.reason)}
    except Exception as e:
        return {"_error": str(e)}

# Primary source to test: Tri-County AA (ID: 15497) or Garden City (ID: 15764)
SOURCE_ID = "15497"

print("=" * 70)
print(f"🔎 PROBING GAMESHEET API FOR SPECIAL TEAMS (SOURCE ID: {SOURCE_ID})")
print("=" * 70)

# -------------------------------------------------------------
# TEST 1: STANDINGS TABLE
# -------------------------------------------------------------
print("\n[TEST 1] Checking Standings Table (/api/standings/{id})...")
standings_url = f"https://gamesheetstats.com/api/standings/{SOURCE_ID}"
st_data = fetch_json(standings_url)

if isinstance(st_data, dict) and "data" in st_data:
    divs = st_data.get("data", [])
    if divs and "standings" in divs[0] and divs[0]["standings"]:
        first_row = divs[0]["standings"][0]
        team_name = first_row.get("team", {}).get("title") or first_row.get("team", {}).get("name")
        print(f"Sample Team: {team_name}")
        print("Standings Root Keys:", list(first_row.keys()))
        print("Standings 'stats' Object Raw Content:")
        print(json.dumps(first_row.get("stats", {}), indent=2))
    else:
        print("No standings rows found inside data.")
else:
    print("Standings Response:", st_data)

# -------------------------------------------------------------
# TEST 2: PLAYER / SKATER STANDINGS (PPG, SHG, PPA)
# -------------------------------------------------------------
print("\n" + "-" * 70)
print("[TEST 2] Checking Player Standings (/api/players/standings/{id})...")
skaters_url = f"https://gamesheetstats.com/api/players/standings/{SOURCE_ID}?limit=3&offset=0"
sk_data = fetch_json(skaters_url)

if isinstance(sk_data, dict) and "data" in sk_data:
    skaters = sk_data.get("data", [])
    if skaters:
        sample_player = skaters[0]
        player_name = f"{sample_player.get('firstName', '')} {sample_player.get('lastName', '')}"
        print(f"Sample Player: {player_name}")
        print("Player Root Keys:", list(sample_player.keys()))
        if sample_player.get("teams"):
            print("Player 'teams[0].stats' Raw Content:")
            print(json.dumps(sample_player["teams"][0].get("stats", {}), indent=2))
    else:
        print("No skaters returned.")
else:
    print("Skaters Response:", sk_data)

# -------------------------------------------------------------
# TEST 3: UNIFIED GAMES (Game Details / Boxscore Fields)
# -------------------------------------------------------------
print("\n" + "-" * 70)
print("[TEST 3] Checking Unified Games (/api/unified-games/{id})...")
games_url = f"https://gamesheetstats.com/api/unified-games/{SOURCE_ID}?filter[limit]=5"
gm_data = fetch_json(games_url)

raw_games = gm_data if isinstance(gm_data, list) else (gm_data.get("games") or gm_data.get("data") or []) if isinstance(gm_data, dict) else []

completed_game_id = None
if raw_games:
    print(f"Retrieved {len(raw_games)} games.")
    sample_game = raw_games[0]
    print("Game Root Keys:", list(sample_game.keys()))
    print("Home Team Object Keys:", list((sample_game.get("home") or {}).keys()))
    print("Home Team Stats / Data:")
    print(json.dumps(sample_game.get("home") or {}, indent=2))

    for g in raw_games:
        status = str(g.get("status") or "").lower()
        if status in ["final", "official", "completed", "2", "3"]:
            completed_game_id = g.get("gameId")
            break
else:
    print("Games Response:", gm_data)

# -------------------------------------------------------------
# TEST 4: GAME REPORT / BOX SCORE DETAILS
# -------------------------------------------------------------
if completed_game_id:
    print("\n" + "-" * 70)
    print(f"[TEST 4] Probing Completed Game Details (Game ID: {completed_game_id})...")
    
    probe_endpoints = [
        f"https://gamesheetstats.com/api/game-reports/{completed_game_id}",
        f"https://gamesheetstats.com/api/games/{completed_game_id}",
        f"https://gamesheetstats.com/api/scoresheets/{completed_game_id}"
    ]

    for ep in probe_endpoints:
        print(f"\n➤ Testing URL: {ep}")
        res = fetch_json(ep)
        if isinstance(res, dict) and not res.get("_error_code") and not res.get("_error"):
            print("  ✅ Endpoint Active! Top-Level Keys:", list(res.keys()))
            # Look for special teams, penalties, or goals
            for key in ["specialTeams", "powerPlays", "penalties", "goals", "summary", "stats"]:
                if key in res:
                    print(f"  Found '{key}':", json.dumps(res[key], indent=2)[:500] + "...")
            break
        else:
            print(f"  ❌ Response: {res}")
else:
    print("\n[TEST 4] No completed game ID available to probe detailed box scores.")

print("\n" + "=" * 70)
print("Diagnostic probe complete. Copy and paste the terminal output below.")
print("=" * 70)
