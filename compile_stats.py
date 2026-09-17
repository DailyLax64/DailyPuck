import urllib.request
import json
import os
import re
import time
from datetime import datetime, timezone

# 1. Setup Auth & Network Headers
RAW_COOKIE = os.environ.get("GAMESHEET_COOKIE", "")
SESSION_COOKIE = RAW_COOKIE.strip().replace('\n', '').replace('\r', '') if RAW_COOKIE else None

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://gamesheetstats.com/shares/dashboard',
    'Origin': 'https://gamesheetstats.com'
}

if SESSION_COOKIE:
    headers['Cookie'] = SESSION_COOKIE
    print("🍪 Session cookie attached to headers.")
else:
    print("⚠️ Warning: GAMESHEET_COOKIE not found. Fetching anonymously.")

def clean_name(name):
    return ' '.join(str(name or "").split()).strip()

# 2. Strict Precedence Division & Tier Parser
def parse_hockey_division(team_name, div_title="", source_name="", fallback_tier=None):
    team_clean = str(team_name or "").upper()
    div_clean = str(div_title or "").upper()
    source_clean = str(source_name or "").upper()

    age = None
    for txt in [team_clean, div_clean, source_clean]:
        m_age = re.search(r'\bU[- ]?(\d{1,2})(?:[A-Z]|\b)|\bUNDER[- ]?(\d{1,2})\b', txt)
        if m_age:
            digits = m_age.group(1) or m_age.group(2)
            age = f"U{digits}"
            break

    if not age:
        traditional_map = [
            (r'\bMINOR\s+NOVICE\b', 'U8'), (r'\b(MAJOR\s+NOVICE|NOVICE)\b', 'U9'),
            (r'\bMINOR\s+ATOM\b', 'U10'), (r'\b(MAJOR\s+ATOM|ATOM)\b', 'U11'),
            (r'\bMINOR\s+PEEWEE\b', 'U12'), (r'\b(MAJOR\s+PEEWEE|PEEWEE)\b', 'U13'),
            (r'\bMINOR\s+BANTAM\b', 'U14'), (r'\b(MAJOR\s+BANTAM|BANTAM)\b', 'U15'),
            (r'\bMINOR\s+MIDGET\b', 'U16'), (r'\b(MAJOR\s+MIDGET|MIDGET)\b', 'U18'),
            (r'\bJUVENILE\b', 'U21')
        ]
        for txt in [team_clean, div_clean, source_clean]:
            for pattern, trad_age in traditional_map:
                if re.search(pattern, txt):
                    age = trad_age
                    break
            if age: break

    tier = None
    confidence = 0

    tier_patterns = [
        (r'\bAAA\b', 'AAA'), (r'\bAA\b', 'AA'), (r'\bBB\b', 'BB'),
        (r'\bCC\b', 'CC'), (r'\bMD\b', 'MD'), (r'\bTIER\s*1\b', 'Tier 1'),
        (r'\bTIER\s*2\b', 'Tier 2'), (r'\bTIER\s*3\b', 'Tier 3'),
        (r'\bSELECT\b', 'Select'), (r'\b(HOUSE\s*LEAGUE|HL)\b', 'HL'),
        (r'\bA\b', 'A'), (r'\bB\b', 'B'), (r'\bC\b', 'C')
    ]

    m_attached = re.search(r'\bU\d{1,2}[- ]?(AAA|AA|BB|CC|MD|A|B|C)\b', team_clean)
    if m_attached:
        tier = m_attached.group(1)
        confidence = 3
    else:
        for pat, val in tier_patterns:
            if re.search(pat, team_clean):
                tier = val
                confidence = 3
                break

    if not tier and div_clean:
        sanitized_div = re.sub(r'\b(POOL|GROUP|FLIGHT|BRACKET|ROUND|DIV|DIVISION|CONFERENCE)\s+[A-Z0-9]\b', '', div_clean).strip()
        m_div_att = re.search(r'\bU\d{1,2}[- ]?(AAA|AA|BB|CC|MD|A|B|C)\b', sanitized_div)
        if m_div_att:
            tier = m_div_att.group(1)
            confidence = 2
        else:
            for pat, val in tier_patterns:
                if re.search(pat, sanitized_div):
                    tier = val
                    confidence = 2
                    break

    if not tier and fallback_tier and fallback_tier.upper() != "AUTO":
        tier = fallback_tier.upper()
        confidence = 1

    if not tier:
        for pat, val in tier_patterns:
            if re.search(pat, source_clean):
                tier = val
                confidence = 1
                break

    return age or "Other", tier or "AA", confidence

def fetch_json(url):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"   ❌ Fetch error for {url}: {e}")
        return None

# 3. Load Sources Configuration
if not os.path.exists("sources.json"):
    raise FileNotFoundError("Critical error: sources.json is missing.")

with open("sources.json", "r") as f:
    sources = json.load(f)

all_sources = []
for stype in ["leagues", "tournaments"]:
    for name, config in sources.get(stype, {}).items():
        if isinstance(config, dict):
            sid = str(config.get("id"))
            forced_tier = config.get("tier", "Auto")
        else:
            sid = str(config)
            forced_tier = "Auto"
        all_sources.append({
            "name": name,
            "id": sid,
            "type": stype[:-1],
            "forced_tier": forced_tier
        })

print(f"📡 Found {len(all_sources)} sources to compile.\n")

canonical_teams = {}
team_id_to_canonical = {}
raw_standings_entries = []

# 4. STAGE 1: INGEST STANDINGS
for src in all_sources:
    s_id = src["id"]
    s_name = src["name"]
    s_type = src["type"]
    s_tier = src["forced_tier"]
    print(f"📥 Standings Ingestion: [{s_type.upper()}] {s_name} (ID: {s_id})...")

    standings_url = f"https://gamesheetstats.com/api/standings/{s_id}?"
    st_data = fetch_json(standings_url)
    if st_data and "data" in st_data:
        for div_group in st_data.get("data", []):
            for row in div_group.get("standings", []):
                t_info = row.get("team", {})
                t_name = clean_name(t_info.get("title") or t_info.get("name", "Unknown Team"))
                t_id = t_info.get("id")
                stats = row.get("stats", {})
                
                div_obj = row.get("division", {})
                div_title = clean_name(div_obj.get("title") or div_obj.get("name", ""))
                
                age, tier, confidence = parse_hockey_division(t_name, div_title, s_name, fallback_tier=s_tier)
                
                team_key = (t_name.upper(), age)
                if team_key not in canonical_teams or confidence > canonical_teams[team_key]["confidence"]:
                    canonical_teams[team_key] = {"age": age, "tier": tier, "confidence": confidence}

                if t_id:
                    team_id_to_canonical[int(t_id)] = team_key

                raw_standings_entries.append({
                    "team_id": t_id,
                    "team_name": t_name,
                    "division_title": div_title,
                    "detected_age": age,
                    "team_key": team_key,
                    "source_id": s_id,
                    "source_name": s_name,
                    "source_type": s_type,
                    "gp": int(stats.get("gp") or stats.get("GP") or 0),
                    "w": int(stats.get("w") or stats.get("W") or 0),
                    "l": int(stats.get("l") or stats.get("L") or 0),
                    "t": int(stats.get("t") or stats.get("T") or 0),
                    "pts": int(stats.get("pts") or stats.get("PTS") or 0),
                    "gf": int(stats.get("gf") or stats.get("GF") or 0),
                    "ga": int(stats.get("ga") or stats.get("GA") or 0),
                    "diff": int(stats.get("diff") or stats.get("DIFF") or 0),
                    "pim": int(stats.get("pim") or stats.get("PIM") or 0)
                })
    time.sleep(0.2)

standings_db = []
for entry in raw_standings_entries:
    c_info = canonical_teams.get(entry["team_key"], {"age": entry["detected_age"], "tier": "AA"})
    standings_db.append({
        "team_id": entry["team_id"],
        "team_name": entry["team_name"],
        "division_title": entry["division_title"],
        "age": c_info["age"],
        "tier": c_info["tier"],
        "source_id": entry["source_id"],
        "source_name": entry["source_name"],
        "source_type": entry["source_type"],
        "gp": entry["gp"], "w": entry["w"], "l": entry["l"], "t": entry["t"],
        "pts": entry["pts"], "gf": entry["gf"], "ga": entry["ga"],
        "diff": entry["diff"], "pim": entry["pim"]
    })

# 5. STAGE 2: INGEST SKATERS & GOALIES
skaters_db = {}
goalies_db = {}

for src in all_sources:
    s_id = src["id"]
    s_name = src["name"]
    s_type = src["type"]
    s_tier = src["forced_tier"]
    print(f"📥 Roster Ingestion:    [{s_type.upper()}] {s_name} (ID: {s_id})...")

    # Skaters
    skaters_url = f"https://gamesheetstats.com/api/players/standings/{s_id}?limit=10000&offset=0"
    sk_data = fetch_json(skaters_url)
    if sk_data and "data" in sk_data:
        for p in sk_data.get("data", []):
            p_name = clean_name(f"{p.get('firstName', '')} {p.get('lastName', '')}")
            if not p_name: continue
            
            jersey = p.get("jersey", "")
            pos = clean_name(p.get("position", "F"))
            
            for t in p.get("teams", []):
                t_name = clean_name(t.get("title") or t.get("name", "Unknown Team"))
                t_id = t.get("id")
                st = t.get("stats", {})
                
                gp = int(st.get("gp") or 0)
                g = int(st.get("g") or 0)
                a = int(st.get("a") or 0)
                pts = int(st.get("pts") if st.get("pts") is not None else (g + a))
                pim = int(st.get("pim") or 0)
                
                if gp == 0 and pts == 0: continue

                c_info = None
                if t_id and int(t_id) in team_id_to_canonical:
                    c_info = canonical_teams.get(team_id_to_canonical[int(t_id)])
                if not c_info:
                    d_age, d_tier, _ = parse_hockey_division(t_name, "", s_name, fallback_tier=s_tier)
                    c_info = canonical_teams.get((t_name.upper(), d_age), {"age": d_age, "tier": d_tier})

                age, tier = c_info["age"], c_info["tier"]
                player_key = f"{p_name}_{t_name}_{age}".upper()
                if player_key not in skaters_db:
                    skaters_db[player_key] = {
                        "name": p_name, "team": t_name, "team_id": t_id, "jersey": jersey, "position": pos,
                        "age": age, "tier": tier, "total_gp": 0, "total_g": 0, "total_a": 0, "total_pts": 0, "total_pim": 0,
                        "sources": []
                    }
                
                skaters_db[player_key]["total_gp"] += gp
                skaters_db[player_key]["total_g"] += g
                skaters_db[player_key]["total_a"] += a
                skaters_db[player_key]["total_pts"] += pts
                skaters_db[player_key]["total_pim"] += pim
                skaters_db[player_key]["sources"].append({
                    "source_id": s_id, "source_name": s_name, "source_type": s_type,
                    "gp": gp, "g": g, "a": a, "pts": pts, "pim": pim
                })
    time.sleep(0.2)

    # Goalies
    goalies_url = f"https://gamesheetstats.com/api/goalies/standings/{s_id}?limit=10000&offset=0"
    gk_data = fetch_json(goalies_url)
    if gk_data and "data" in gk_data:
        for g in gk_data.get("data", []):
            g_name = clean_name(f"{g.get('firstName', '')} {g.get('lastName', '')}")
            if not g_name: continue
            jersey = g.get("jersey", "")
            
            for t in g.get("teams", []):
                t_name = clean_name(t.get("title") or t.get("name", "Unknown Team"))
                t_id = t.get("id")
                st = t.get("stats", {})
                
                gp = int(st.get("gp") or 0)
                ga = int(st.get("ga") or 0)
                mins = int(st.get("min") or st.get("min_played") or 0)
                gaa = float(st.get("gaa") or 0.0)
                so = int(st.get("so") or st.get("shutouts") or 0)
                w = int(st.get("w") or 0)
                l = int(st.get("l") or 0)
                t_val = int(st.get("t") or 0)
                
                if gp == 0: continue

                c_info = None
                if t_id and int(t_id) in team_id_to_canonical:
                    c_info = canonical_teams.get(team_id_to_canonical[int(t_id)])
                if not c_info:
                    d_age, d_tier, _ = parse_hockey_division(t_name, "", s_name, fallback_tier=s_tier)
                    c_info = canonical_teams.get((t_name.upper(), d_age), {"age": d_age, "tier": d_tier})

                age, tier = c_info["age"], c_info["tier"]
                goalie_key = f"{g_name}_{t_name}_{age}".upper()
                if goalie_key not in goalies_db:
                    goalies_db[goalie_key] = {
                        "name": g_name, "team": t_name, "team_id": t_id, "jersey": jersey, "position": "G",
                        "age": age, "tier": tier, "total_gp": 0, "total_ga": 0, "total_min": 0, "total_gaa": 0.0,
                        "total_so": 0, "total_w": 0, "total_l": 0, "total_t": 0,
                        "sources": []
                    }
                
                goalies_db[goalie_key]["total_gp"] += gp
                goalies_db[goalie_key]["total_ga"] += ga
                goalies_db[goalie_key]["total_min"] += mins
                goalies_db[goalie_key]["total_so"] += so
                goalies_db[goalie_key]["total_w"] += w
                goalies_db[goalie_key]["total_l"] += l
                goalies_db[goalie_key]["total_t"] += t_val
                
                tot_min = goalies_db[goalie_key]["total_min"]
                tot_ga = goalies_db[goalie_key]["total_ga"]
                goalies_db[goalie_key]["total_gaa"] = round((tot_ga * 45.0) / tot_min, 2) if tot_min > 0 else gaa
                    
                goalies_db[goalie_key]["sources"].append({
                    "source_id": s_id, "source_name": s_name, "source_type": s_type,
                    "gp": gp, "ga": ga, "min": mins, "gaa": gaa, "so": so, "w": w, "l": l, "t": t_val
                })
    time.sleep(0.2)

# 6. STAGE 3: INGEST UNIFIED GAMES & SCHEDULES
games_dict = {}
valid_final_states = ["final", "official", "completed", "complete", "played", "finished", "2", "3"]

for src in all_sources:
    s_id = src["id"]
    s_name = src["name"]
    s_type = src["type"]
    print(f"📥 Schedule Ingestion:   [{s_type.upper()}] {s_name} (ID: {s_id})...")

    games_url = f"https://gamesheetstats.com/api/unified-games/{s_id}?filter[limit]=10000"
    g_data = fetch_json(games_url)
    
    raw_games = g_data if isinstance(g_data, list) else (g_data.get("games") or g_data.get("data") or []) if isinstance(g_data, dict) else []
    
    for g in raw_games:
        gid = g.get("gameId")
        if not gid: continue

        visitor_obj = g.get("visitor") or {}
        home_obj = g.get("home") or {}

        v_name = clean_name(visitor_obj.get("title") or visitor_obj.get("name", "Unknown Team"))
        h_name = clean_name(home_obj.get("title") or home_obj.get("name", "Unknown Team"))
        v_id = visitor_obj.get("id")
        h_id = home_obj.get("id")

        raw_status = str(g.get("status") or "").strip().lower()
        is_final = raw_status in valid_final_states

        v_goals = int(visitor_obj.get("goals") or 0) if is_final else None
        h_goals = int(home_obj.get("goals") or 0) if is_final else None

        v_res, h_res = None, None
        if is_final:
            if v_goals > h_goals:
                v_res, h_res = "W", "L"
            elif h_goals > v_goals:
                v_res, h_res = "L", "W"
            else:
                v_res, h_res = "T", "T"

        # Division determination
        v_div = visitor_obj.get("division", {}).get("title") if isinstance(visitor_obj.get("division"), dict) else ""
        h_div = home_obj.get("division", {}).get("title") if isinstance(home_obj.get("division"), dict) else ""
        g_div = v_div or h_div or ""

        games_dict[str(gid)] = {
            "game_id": gid,
            "date": g.get("date", ""),
            "time": g.get("time", ""),
            "timestamp": g.get("timeStampZulu", ""),
            "status": "final" if is_final else "scheduled",
            "location": g.get("location", ""),
            "source_id": s_id,
            "source_name": s_name,
            "source_type": s_type,
            "home_id": h_id,
            "home_name": h_name,
            "home_goals": h_goals,
            "home_result": h_res,
            "visitor_id": v_id,
            "visitor_name": v_name,
            "visitor_goals": v_goals,
            "visitor_result": v_res,
            "division": g_div
        }

    time.sleep(0.2)

all_compiled_games = sorted(list(games_dict.values()), key=lambda x: x["timestamp"] or x["date"])

# 7. EXPORT COMPILED STATS & COMPLETE GAME MATRIX
output_data = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "total_skaters": len(skaters_db),
    "total_goalies": len(goalies_db),
    "total_standings_rows": len(standings_db),
    "total_games": len(all_compiled_games),
    "skaters": sorted(list(skaters_db.values()), key=lambda x: x["total_pts"], reverse=True),
    "goalies": sorted(list(goalies_db.values()), key=lambda x: (x["total_gaa"], -x["total_gp"])),
    "standings": standings_db,
    "games": all_compiled_games
}

output_path = "hockey_stats.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(output_data, f, indent=2)

print("\n" + "="*55)
print("🎉 Minor Hockey Matrix Compilation Complete!")
print(f"🏒 Skaters Processed: {len(skaters_db)}")
print(f"🥅 Goalies Processed: {len(goalies_db)}")
print(f"📊 Standings Rows:    {len(standings_db)}")
print(f"📋 Total Games Tracked: {len(all_compiled_games)}")
print(f"💾 Saved cleanly to {output_path}")
print("="*55)
