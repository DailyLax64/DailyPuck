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

test_targets = [
    (15497, "league", "Tri-County AA"),
    (15764, "tournament", "Garden City Early")
]

for id_num, target_type, label in test_targets:
    print(f"\n==========================================")
    print(f"Testing [{target_type.upper()}] {label} (ID: {id_num})")
    print(f"==========================================")
    
    candidate_urls = [
        f"https://gamesheetstats.com/api/useScoredGames/getSeasonScores/{id_num}?filter[gametype]=overall&filter[limit]=10&filter[offset]=0&filter[timeZoneOffset]=-240",
        f"https://gamesheetstats.com/api/tournaments/{id_num}/games?filter[limit]=10",
        f"https://gamesheetstats.com/api/unified-games/{id_num}?filter[limit]=10",
        f"https://gamesheetstats.com/api/seasons/{id_num}/games?filter[limit]=10"
    ]
    
    found = False
    for url in candidate_urls:
        endpoint_name = url.split("?")[0].split("/")[-2] + "/" + url.split("?")[0].split("/")[-1]
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                raw_list = data if isinstance(data, list) else data.get("games") or data.get("data") or []
                
                if isinstance(raw_list, list) and len(raw_list) > 0:
                    print(f"✅ SUCCESS on endpoint: .../{endpoint_name}")
                    print(f"   Retrieved {len(raw_list)} sample records.")
                    
                    sample = raw_list[0]
                    game_inner = sample.get("game") if isinstance(sample.get("game"), dict) else sample
                    home = game_inner.get("homeTeam") or game_inner.get("home") or {}
                    visitor = game_inner.get("visitorTeam") or game_inner.get("away") or {}
                    final_score = game_inner.get("finalScore") or {}
                    
                    h_name = home.get("title") or home.get("name") if isinstance(home, dict) else home
                    v_name = visitor.get("title") or visitor.get("name") if isinstance(visitor, dict) else visitor
                    h_goals = final_score.get("homeGoals") or final_score.get("homeScore")
                    v_goals = final_score.get("visitorGoals") or final_score.get("visitorScore")
                    date_val = game_inner.get("date") or sample.get("date")
                    
                    print(f"   Sample Matchup: {v_name} ({v_goals}) vs {h_name} ({h_goals}) | Date: {date_val}")
                    found = True
                    break
        except Exception as e:
            print(f"❌ Failed .../{endpoint_name}: {e}")
            
    if not found:
        print(f"⚠️ No candidates returned data for ID {id_num}")
