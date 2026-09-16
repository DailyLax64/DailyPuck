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

# 2. Helpers for Data Extraction & Normalization
def clean_name(name):
    return ' '.join(str(name or "").split()).strip()

def parse_age_and_tier(text, fallback_tier="AA"):
    """
    Extracts age brackets (U9-U18) and tiers (AAA, AA, A, BB, B, CC, C, MD)
    directly from team or division names.
    """
    upper_text = text.upper()
    
    # Extract Age Bracket
    age_match = re.search(r'\b(U\d{1,2})\b', upper_text)
    age = age_match.group(1) if age_match else "Other"
    
    # Extract Tier
    tier_patterns = [r'\b(AAA)\b', r'\b(AA)\b', r'\b(BB)\b', r'\b(CC)\b', r'\b(MD)\b', r'\b(A)\b', r'\b(B)\b', r'\b(C)\b']
    tier = None
    for pattern in tier_patterns:
        match = re.search(pattern, upper_text)
        if match:
            tier = match.group(1)
            break
            
    if not tier:
        # Fallback to tier inside the source name if available
        for pattern in tier_patterns:
            match = re.search(pattern, fallback_tier.upper())
            if match:
                tier = match.group(1)
                break
    return age, tier or "Other"

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

# Master Containers
skaters_db = {}
goalies_db = {}
standings_db = []

# 4. Scrape & Aggregate
for src in all_sources:
    s_id = src["id"]
    s_name = src["name"]
    s_type = src["type"]
    print(f"📥 Processing [{s_type.upper()}] {s_name} (ID: {s_id})...")

    # --- Standings Scraping ---
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
                
                age, tier = parse_age_and_tier(f"{t_name} {div_title}", fallback_tier=s_name)
                
                standings_db.append({
                    "team_id": t_id,
                    "team_name": t_name,
                    "division_title": div_title,
                    "age": age,
                    "tier": tier,
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
    time.sleep(0.4)

    # --- Skaters Scraping ---
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
                    continue  # skip inactive entries
                
                age, tier = parse_age_and_tier(t_name, fallback_tier=s_name)
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
                        "total_gp": 0,
                        "total_g": 0,
                        "total_a": 0,
                        "total_pts": 0,
                        "total_pim": 0,
                        "sources": []
                    }
                
                skaters_db[player_key]["total_gp"] += gp
                skaters_db[player_key]["total_g"] += g
                skaters_db[player_key]["total_a"] += a
                skaters_db[player_key]["total_pts"] += pts
                skaters_db[player_key]["total_pim"] += pim
                skaters_db[player_key]["sources"].append({
                    "source_id": s_id,
                    "source_name": s_name,
                    "source_type": s_type,
                    "gp": gp, "g": g, "a": a, "pts": pts, "pim": pim
                })
    time.sleep(0.4)

    # --- Goalies Scraping ---
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
                
                age, tier = parse_age_and_tier(t_name, fallback_tier=s_name)
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
                        "total_gp": 0,
                        "total_ga": 0,
                        "total_min": 0,
                        "total_gaa": 0.0,
                        "total_so": 0,
                        "total_w": 0,
                        "total_l": 0,
                        "total_t": 0,
                        "sources": []
                    }
                
                goalies_db[goalie_key]["total_gp"] += gp
                goalies_db[goalie_key]["total_ga"] += ga
                goalies_db[goalie_key]["total_min"] += mins
                goalies_db[goalie_key]["total_so"] += so
                goalies_db[goalie_key]["total_w"] += w
                goalies_db[goalie_key]["total_l"] += l
                goalies_db[goalie_key]["total_t"] += t_val
                
                # Calculate weighted GAA if total minutes exist
                tot_min = goalies_db[goalie_key]["total_min"]
                tot_ga = goalies_db[goalie_key]["total_ga"]
                if tot_min > 0:
                    goalies_db[goalie_key]["total_gaa"] = round((tot_ga * 45.0) / tot_min, 2)
                else:
                    goalies_db[goalie_key]["total_gaa"] = gaa
                    
                goalies_db[goalie_key]["sources"].append({
                    "source_id": s_id,
                    "source_name": s_name,
                    "source_type": s_type,
                    "gp": gp, "ga": ga, "min": mins, "gaa": gaa, "so": so, "w": w, "l": l, "t": t_val
                })
    time.sleep(0.4)

# 5. Export Compiled JSON Database
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
print(f"🎉 Compilation Complete!")
print(f"🏒 Skaters Processed: {len(skaters_db)}")
print(f"🥅 Goalies Processed: {len(goalies_db)}")
print(f"📊 Standings Rows:    {len(standings_db)}")
print(f"💾 Saved to {output_path}")
print("="*50)
