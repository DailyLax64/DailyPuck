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

def normalize(s):
    if not s:
        return ""
    s = str(s).upper()
    s = re.sub(r'[^A-Z0-9\s]', ' ', s)
    return ' '.join(s.split())

def fetch_json(url):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"   ❌ Fetch error for {url}: {e}")
        return None

# 2. Load Master Whitelist & Sources
if not os.path.exists("master_teams.json"):
    raise FileNotFoundError("Critical error: master_teams.json is missing.")
with open("master_teams.json", "r", encoding="utf-8") as f:
    master_teams_db = json.load(f)

if not os.path.exists("sources.json"):
    raise FileNotFoundError("Critical error: sources.json is missing.")
with open("sources.json", "r", encoding="utf-8") as f:
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

print(f"📡 Found {len(all_sources)} sources to compile across U11 AA and U14 AA.\n")

# Build normalized lookup dictionaries
lookup = {"U11 AA": {}, "U14 AA": {}}
for cohort in ["U11 AA", "U14 AA"]:
    for canonical, data in master_teams_db.get(cohort, {}).items():
        c_norm = normalize(canonical)
        lookup[cohort][c_norm] = canonical
        c_base = re.sub(r'\b(U\d{1,2}|AA|AAA|A|BB|MD|MINOR|MAJOR)\b', '', c_norm).strip()
        c_base = ' '.join(c_base.split())
        if c_base:
            lookup[cohort][c_base] = canonical
        for alias in data.get("aliases", []):
            a_norm = normalize(alias)
            lookup[cohort][a_norm] = canonical
            a_base = re.sub(r'\b(U\d{1,2}|AA|AAA|A|BB|MD|MINOR|MAJOR)\b', '', a_norm).strip()
            a_base = ' '.join(a_base.split())
            if a_base:
                lookup[cohort][a_base] = canonical

def resolve_master_team(team_name, div_title="", source_name="", forced_tier=None):
    full_text = f"{team_name} {div_title} {source_name}".upper()

    # 1. Determine Age
    age = None
    if re.search(r'\bU[- ]?11\b|\bATOM\b', full_text):
        age = "U11"
    elif re.search(r'\bU[- ]?14\b|\bBANTAM\b', full_text):
        age = "U14"

    if not age:
        return None, None

    # 2. Determine Tier (Reject explicit non-AA unless overridden)
    is_explicit_other_tier = bool(re.search(r'\b(AAA|BB|CC|MD|SELECT|HL)\b', full_text))
    has_explicit_single_a = bool(re.search(r'\bU\d{1,2}\s+A\b|\bTIER\s*2\b', f"{team_name} {div_title}".upper()))
    
    if is_explicit_other_tier or has_explicit_single_a:
        if not re.search(r'\bAA\b', full_text):
            return None, None

    is_aa = bool(re.search(r'\bAA\b', full_text)) or (forced_tier and forced_tier.upper() == "AA")
    if not is_aa:
        return None, None

    cohort = f"{age} AA"

    # 3. Direct Match via Normalized String
    t_norm = normalize(team_name)
    if t_norm in lookup[cohort]:
        return cohort, lookup[cohort][t_norm]

    # 4. Base Match (Stripped of age/tier tokens)
    t_base = re.sub(r'\b(U11|U14|U\d{1,2}|AA|AAA|A|BB|MD|MINOR|MAJOR)\b', '', t_norm).strip()
    t_base = ' '.join(t_base.split())
    if t_base in lookup[cohort]:
        return cohort, lookup[cohort][t_base]

    # 5. Association Root Fuzzy Match
    for canonical in master_teams_db.get(cohort, {}):
        assoc_base = canonical.split()[0].upper()
        if len(assoc_base) > 4 and assoc_base in t_base:
            return cohort, canonical

    return cohort, None

# Master Storage
team_id_to_master = {}
standings_db = []
unmapped_audit = set()

# 3. STAGE 1: INGEST STANDINGS
for src in all_sources:
    s_id, s_name, s_type, s_tier = src["id"], src["name"], src["type"], src["forced_tier"]
    print(f"📥 Standings Ingestion: [{s_type.upper()}] {s_name} (ID: {s_id})...")

    standings_url = f"https://gamesheetstats.com/api/standings/{s_id}?"
    st_data = fetch_json(standings_url)
    if st_data and "data" in st_data:
        for div_group in st_data.get("data", []):
            for row in div_group.get("standings", []):
                t_info = row.get("team", {})
                t_name = clean_name(t_info.get("title") or t_info.get("name", ""))
                t_id = t_info.get("id")
                stats = row.get("stats", {})
                div_title = clean_name(row.get("division", {}).get("title") or "")

                cohort, canonical_name = resolve_master_team(t_name, div_title, s_name, forced_tier=s_tier)

                if cohort and not canonical_name:
                    unmapped_audit.add((cohort, t_name, s_name, t_id))
                    continue
                if not cohort or not canonical_name:
                    continue

                if t_id:
                    team_id_to_master[int(t_id)] = (cohort, canonical_name)

                standings_db.append({
                    "team_id": t_id,
                    "team_name": canonical_name,
                    "division_title": cohort,
                    "age": cohort.split()[0],
                    "tier": cohort.split()[1],
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

# 4. STAGE 2: INGEST UNIFIED GAMES (Populates remaining Team IDs before rosters run)
games_dict = {}
valid_final_states = ["final", "official", "completed", "complete", "played", "finished", "2", "3"]

for src in all_sources:
    s_id, s_name, s_type, s_tier = src["id"], src["name"], src["type"], src["forced_tier"]
    print(f"📥 Schedule Ingestion:   [{s_type.upper()}] {s_name} (ID: {s_id})...")

    g_data = fetch_json(f"https://gamesheetstats.com/api/unified-games/{s_id}?filter[limit]=10000")
    raw_games = g_data if isinstance(g_data, list) else (g_data.get("games") or g_data.get("data") or []) if isinstance(g_data, dict) else []

    for g in raw_games:
        gid = g.get("gameId")
        if not gid:
            continue

        visitor_obj = g.get("visitor") or {}
        home_obj = g.get("home") or {}
        v_name = clean_name(visitor_obj.get("title") or visitor_obj.get("name", ""))
        h_name = clean_name(home_obj.get("title") or home_obj.get("name", ""))
        v_id = visitor_obj.get("id")
        h_id = home_obj.get("id")

        v_div = visitor_obj.get("division", {}).get("title") if isinstance(visitor_obj.get("division"), dict) else ""
        h_div = home_obj.get("division", {}).get("title") if isinstance(home_obj.get("division"), dict) else ""
        g_div = v_div or h_div or ""

        # Resolve Home and Visitor
        h_cohort, h_canonical = None, None
        if h_id and int(h_id) in team_id_to_master:
            h_cohort, h_canonical = team_id_to_master[int(h_id)]
        else:
            h_cohort, h_canonical = resolve_master_team(h_name, g_div, s_name, forced_tier=s_tier)
            if h_cohort and h_canonical and h_id:
                team_id_to_master[int(h_id)] = (h_cohort, h_canonical)

        v_cohort, v_canonical = None, None
        if v_id and int(v_id) in team_id_to_master:
            v_cohort, v_canonical = team_id_to_master[int(v_id)]
        else:
            v_cohort, v_canonical = resolve_master_team(v_name, g_div, s_name, forced_tier=s_tier)
            if v_cohort and v_canonical and v_id:
                team_id_to_master[int(v_id)] = (v_cohort, v_canonical)

        if not h_canonical and not v_canonical:
            continue

        assigned_cohort = h_cohort or v_cohort

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
            "home_name": h_canonical or h_name,
            "home_goals": h_goals,
            "home_result": h_res,
            "visitor_id": v_id,
            "visitor_name": v_canonical or v_name,
            "visitor_goals": v_goals,
            "visitor_result": v_res,
            "division": assigned_cohort
        }
    time.sleep(0.2)

all_compiled_games = sorted(list(games_dict.values()), key=lambda x: x["timestamp"] or x["date"])

# 5. STAGE 3: INGEST SKATERS & GOALIES (All Team IDs & Divisions Now Known)
skaters_db = {}
goalies_db = {}

for src in all_sources:
    s_id, s_name, s_type, s_tier = src["id"], src["name"], src["type"], src["forced_tier"]
    print(f"📥 Roster Ingestion:    [{s_type.upper()}] {s_name} (ID: {s_id})...")

    # Skaters
    sk_data = fetch_json(f"https://gamesheetstats.com/api/players/standings/{s_id}?limit=10000&offset=0")
    if sk_data and "data" in sk_data:
        for p in sk_data.get("data", []):
            p_name = clean_name(f"{p.get('firstName', '')} {p.get('lastName', '')}")
            if not p_name:
                continue
            jersey, pos = p.get("jersey", ""), clean_name(p.get("position", "F"))
            p_div = clean_name(p.get("division", {}).get("title") or "") if isinstance(p.get("division"), dict) else ""

            for t in p.get("teams", []):
                t_name = clean_name(t.get("title") or t.get("name", ""))
                t_id = t.get("id")
                t_div = clean_name(t.get("division", {}).get("title") or "") if isinstance(t.get("division"), dict) else ""
                effective_div = t_div or p_div

                st = t.get("stats", {})
                gp = int(st.get("gp") or 0)
                g = int(st.get("g") or 0)
                a = int(st.get("a") or 0)
                pts = int(st.get("pts") if st.get("pts") is not None else (g + a))
                pim = int(st.get("pim") or 0)

                cohort, canonical_name = None, None
                if t_id and int(t_id) in team_id_to_master:
                    cohort, canonical_name = team_id_to_master[int(t_id)]
                else:
                    cohort, canonical_name = resolve_master_team(t_name, effective_div, s_name, forced_tier=s_tier)

                if not cohort or not canonical_name:
                    continue

                age, tier = cohort.split()[0], cohort.split()[1]
                player_key = f"{p_name}_{canonical_name}_{age}".upper()
                if player_key not in skaters_db:
                    skaters_db[player_key] = {
                        "name": p_name, "team": canonical_name, "team_id": t_id, "jersey": jersey, "position": pos,
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
    gk_data = fetch_json(f"https://gamesheetstats.com/api/goalies/standings/{s_id}?limit=10000&offset=0")
    if gk_data and "data" in gk_data:
        for g in gk_data.get("data", []):
            g_name = clean_name(f"{g.get('firstName', '')} {g.get('lastName', '')}")
            if not g_name:
                continue
            jersey = g.get("jersey", "")
            g_div = clean_name(g.get("division", {}).get("title") or "") if isinstance(g.get("division"), dict) else ""

            for t in g.get("teams", []):
                t_name = clean_name(t.get("title") or t.get("name", ""))
                t_id = t.get("id")
                t_div = clean_name(t.get("division", {}).get("title") or "") if isinstance(t.get("division"), dict) else ""
                effective_div = t_div or g_div

                st = t.get("stats", {})
                gp = int(st.get("gp") or 0)

                cohort, canonical_name = None, None
                if t_id and int(t_id) in team_id_to_master:
                    cohort, canonical_name = team_id_to_master[int(t_id)]
                else:
                    cohort, canonical_name = resolve_master_team(t_name, effective_div, s_name, forced_tier=s_tier)

                if not cohort or not canonical_name:
                    continue

                age, tier = cohort.split()[0], cohort.split()[1]
                ga = int(st.get("ga") or 0)
                mins = int(st.get("min") or st.get("min_played") or 0)
                gaa = float(st.get("gaa") or 0.0)
                so = int(st.get("so") or st.get("shutouts") or 0)
                w, l, t_val = int(st.get("w") or 0), int(st.get("l") or 0), int(st.get("t") or 0)

                goalie_key = f"{g_name}_{canonical_name}_{age}".upper()
                if goalie_key not in goalies_db:
                    goalies_db[goalie_key] = {
                        "name": g_name, "team": canonical_name, "team_id": t_id, "jersey": jersey, "position": "G",
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

# 6. EXPORT COMPILED STATS
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

print("\n" + "="*70)
print("🎉 Clean U11 AA & U14 AA Compilation Complete!")
print(f"🏒 Skaters Processed: {len(skaters_db)}")
print(f"🥅 Goalies Processed: {len(goalies_db)}")
print(f"📊 Standings Rows:    {len(standings_db)}")
print(f"📋 Games Tracked:     {len(all_compiled_games)}")
print(f"💾 Saved to {output_path}")
print("="*70)

# 7. UNMAPPED AUDIT REPORT
print("\n📋 UNMAPPED TEAM AUDIT LOG (U11 / U14 Teams Ignored Due to Missing Rule)")
print("-" * 70)
if unmapped_audit:
    for cohort, name, src, tid in sorted(list(unmapped_audit)):
        print(f"⚠️  [{cohort}] '{name}' (ID: {tid}) in {src}")
    print("\n👉 To track any of these, simply add their exact name as an alias in master_teams.json!")
else:
    print("💯 Perfect Structural Integrity! All encountered teams were matched.")
print("-" * 70)
