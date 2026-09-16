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
    'Referer': 'https://gamesheetstats.com/shares/dashboard'
}

if SESSION_COOKIE:
    headers['Cookie'] = SESSION_COOKIE
    print("🍪 Session cookie attached to headers.")
else:
    print("⚠️ Warning: GAMESHEET_COOKIE not found. Fetching anonymously.")

# 2. Advanced Minor Hockey Division Parser
def clean_name(name):
    return ' '.join(str(name or "").split()).strip()

def parse_hockey_division(team_name, div_title="", source_name=""):
    """
    Robust extractor for minor hockey Age bracket (U7-U21) and Tier (AAA-HL).
    Examines team_name, division title, and source/league name.
    """
    full_text = f"{team_name} {div_title} {source_name}".upper()
    name_and_div = f"{team_name} {div_title}".upper()
    
    # --- 1. AGE DETECTION ---
    age = None
    
    # Check U-prefixed patterns (U11, U11AA, U-11, U 11, Under 11, Under-11)
    m_age = re.search(r'\bU[- ]?(\d{1,2})(?:[A-Z]|\b)|\bUNDER[- ]?(\d{1,2})\b', full_text)
    if m_age:
        digits = m_age.group(1) or m_age.group(2)
        age = f"U{digits}"
        
    # Traditional Ontario Minor Hockey naming fallback
    if not age:
        traditional_map = [
            (r'\bMINOR\s+NOVICE\b', 'U8'),
            (r'\b(MAJOR\s+NOVICE|NOVICE)\b', 'U9'),
            (r'\bMINOR\s+ATOM\b', 'U10'),
            (r'\b(MAJOR\s+ATOM|ATOM)\b', 'U11'),
            (r'\bMINOR\s+PEEWEE\b', 'U12'),
            (r'\b(MAJOR\s+PEEWEE|PEEWEE)\b', 'U13'),
            (r'\bMINOR\s+BANTAM\b', 'U14'),
            (r'\b(MAJOR\s+BANTAM|BANTAM)\b', 'U15'),
            (r'\bMINOR\s+MIDGET\b', 'U16'),
            (r'\b(MAJOR\s+MIDGET|MIDGET)\b', 'U18'),
            (r'\bJUVENILE\b', 'U21')
        ]
        for pattern, trad_age in traditional_map:
            if re.search(pattern, full_text):
                age = trad_age
                break
                
    # --- 2. TIER DETECTION ---
    tier = None
    
    # Priority A: Attached directly to age (e.g., U11AA, U11AAA, U11A, U11BB, U11MD, U13A)
    m_attached = re.search(r'\bU\d{1,2}[- ]?(AAA|AA|BB|CC|MD|A|B|C)\b', name_and_div)
    if m_attached:
        tier = m_attached.group(1)
        
    # Priority B: Standalone tiers in team name or division title
    standalone_tiers = [
        (r'\bAAA\b', 'AAA'),
        (r'\bAA\b', 'AA'),
        (r'\bBB\b', 'BB'),
        (r'\bCC\b', 'CC'),
        (r'\bMD\b', 'MD'),
        (r'\bTIER\s*1\b', 'Tier 1'),
        (r'\bTIER\s*2\b', 'Tier 2'),
        (r'\bTIER\s*3\b', 'Tier 3'),
        (r'\bSELECT\b', 'Select'),
        (r'\b(HOUSE\s*LEAGUE|HL)\b', 'HL'),
        (r'\bA\b', 'A'),
        (r'\bB\b', 'B'),
        (r'\bC\b', 'C')
    ]
    if not tier:
        for pattern, val in standalone_tiers:
            if re.search(pattern, name_and_div):
                tier = val
                break
                
    # Priority C: Inherit tier from league/source name (e.g., "Tri-County AA" -> AA)
    if not tier:
        for pattern, val in standalone_tiers:
            if re.search(pattern, source_name.upper()):
                tier = val
                break

    # Priority D: Fallback for minor hockey circuit
    if not tier:
        tier = "AA" if "AA" in source_name.upper() else "A"
        
    return age or "Other", tier

def fetch_json(url):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"   ❌ Fetch error for {url}: {e}")
        return None

# 3. Load Sources
if not os.path.exists("sources.json"):
    raise FileNotFoundError("Critical error: sources.json is missing.")

with open("sources.json", "r") as f:
    sources = json.load(f)

all_sources = []
for name, sid in sources.get("leagues", {}).items():
    all_sources.append({"name": name, "id": str(sid), "type": "league"})
for name, sid in sources.get("tournaments", {}).items():
    all_sources.append({"name": name, "id": str(sid), "type": "tournament"})

print(f"📡 Found {len(all_sources)} sources to compile.\n")

# Master Containers & Team Metadata Cross-Reference Map
team_id_metadata = {}  # team_id (int) -> {"age": age, "tier": tier, "team_name": t_name}
club_tier_map = {}     # (club_base, age) -> tier
standings_db = []
raw_standings_entries = []

# 4. STAGE 1: SCRAPE STANDINGS & BUILD TEAM RESOLUTION MAP
for src in all_sources:
    s_id = src["id"]
    s_name = src["name"]
    s_type = src["type"]
    print(f"📥 Processing Standings: [{s_type.upper()}] {s_name} (ID: {s_id})...")

    standings_url = f"https://gamesheetstats.com/api/standings/{s_id}?"
    st_data = fetch_json(standings_url)
    if st_data and "data" in st_data:
        for div_group in st_data.get("data", []):
            div_title = clean_name(div_group.get("title") or div_group.get("name", ""))
            for row in div_group.get("standings", []):
                t_info = row.get("team", {})
                t_name = clean_name(t_info.get("title") or t_info.get("name", "Unknown Team"))
                t_id = t_info.get("id")
                stats = row.get("stats", {})
                
                age, tier = parse_hockey_division(t_name, div_title, s_name)
                
                if t_id:
                    team_id_metadata[int(t_id)] = {"age": age, "tier": tier, "team_name": t_name}
                
                # Register known club tier for cross-resolution
                club_base = re.sub(r'\b(U\d{1,2}|AAA|AA|BB|CC|MD|A|B|C)\b', '', t_name.upper()).strip()
                club_base = ' '.join(club_base.split())
                if age != "Other" and tier:
                    club_tier_map[(club_base, age)] = tier
                
                raw_standings_entries.append({
                    "team_id": t_id,
                    "team_name": t_name,
                    "division_title": div_title,
                    "age": age,
                    "tier": tier,
                    "club_base": club_base,
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
    time.sleep(0.3)

# Resolve any missing tiers in standings entries via cross-referencing
for entry in raw_standings_entries:
    age = entry["age"]
    tier = entry["tier"]
    if age != "Other" and (tier == "Other" or not tier):
        tier = club_tier_map.get((entry["club_base"], age), "AA")
        entry["tier"] = tier
        if entry["team_id"]:
            team_id_metadata[int(entry["team_id"])]["tier"] = tier

    standings_db.append({
        "team_id": entry["team_id"],
        "team_name": entry["team_name"],
        "division_title": entry["division_title"],
        "age": entry["age"],
        "tier": entry["tier"],
        "source_id": entry["source_id"],
        "source_name": entry["source_name"],
        "source_type": entry["source_type"],
        "gp": entry["gp"], "w": entry["w"], "l": entry["l"], "t": entry["t"],
        "pts": entry["pts"], "gf": entry["gf"], "ga": entry["ga"],
        "diff": entry["diff"], "pim": entry["pim"]
    })

# 5. STAGE 2: SCRAPE SKATERS & GOALIES (ROBUST TEAM MAPPING)
skaters_db = {}
goalies_db = {}

for src in all_sources:
    s_id = src["id"]
    s_name = src["name"]
    s_type = src["type"]
    print(f"📥 Processing Rosters:   [{s_type.upper()}] {s_name} (ID: {s_id})...")

    # --- Skaters ---
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
                
                if gp == 0 and pts == 0:
                    continue
                
                # Inherit confirmed division from standings map first
                if t_id and int(t_id) in team_id_metadata:
                    age = team_id_metadata[int(t_id)]["age"]
                    tier = team_id_metadata[int(t_id)]["tier"]
                else:
                    age, tier = parse_hockey_division(t_name, "", s_name)

                player_key = f"{p_name}_{t_name}".upper()
                
                if player_key not in skaters_db:
                    skaters_db[player_key] = {
                        "name": p_name,
                        "team": t_name,
                        "team_id": t_id,
                        "jersey": jersey,
                        "position": pos,
                        "age": age,
                        "tier": tier,
                        "total_gp": 0, "total_g": 0, "total_a": 0, "total_pts": 0, "total_pim": 0,
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
    time.sleep(0.3)

    # --- Goalies ---
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
                
                if gp == 0:
                    continue
                
                # Inherit confirmed division from standings map first
                if t_id and int(t_id) in team_id_metadata:
                    age = team_id_metadata[int(t_id)]["age"]
                    tier = team_id_metadata[int(t_id)]["tier"]
                else:
                    age, tier = parse_hockey_division(t_name, "", s_name)

                goalie_key = f"{g_name}_{t_name}".upper()
                
                if goalie_key not in goalies_db:
                    goalies_db[goalie_key] = {
                        "name": g_name,
                        "team": t_name,
                        "team_id": t_id,
                        "jersey": jersey,
                        "position": "G",
                        "age": age,
                        "tier": tier,
                        "total_gp": 0, "total_ga": 0, "total_min": 0, "total_gaa": 0.0,
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
                if tot_min > 0:
                    goalies_db[goalie_key]["total_gaa"] = round((tot_ga * 45.0) / tot_min, 2)
                else:
                    goalies_db[goalie_key]["total_gaa"] = gaa
                    
                goalies_db[goalie_key]["sources"].append({
                    "source_id": s_id, "source_name": s_name, "source_type": s_type,
                    "gp": gp, "ga": ga, "min": mins, "gaa": gaa, "so": so, "w": w, "l": l, "t": t_val
                })
    time.sleep(0.3)

# 6. EXPORT CLEAN COMPILED STATS
output_data = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "total_skaters": len(skaters_db),
    "total_goalies": len(goalies_db),
    "total_standings_rows": len(standings_db),
    "skaters": sorted(list(skaters_db.values()), key=lambda x: x["total_pts"], reverse=True),
    "goalies": sorted(list(goalies_db.values()), key=lambda x: (x["total_gaa"], -x["total_gp"])),
    "standings": standings_db
}

output_path = "hockey_stats.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(output_data, f, indent=2)

print("\n" + "="*50)
print("🎉 Clean Minor Hockey Compilation Complete!")
print(f"🏒 Skaters Processed: {len(skaters_db)}")
print(f"🥅 Goalies Processed: {len(goalies_db)}")
print(f"📊 Standings Rows:    {len(standings_db)}")
print(f"💾 Saved cleanly to {output_path}")
print("="*50)
