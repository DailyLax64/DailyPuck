import urllib.request
import urllib.error
import json
import os
import re
import time
from datetime import datetime, timezone

# 1. Setup Automated Authentication & Network Headers
FIREBASE_API_KEY = os.environ.get("GAMESHEET_FIREBASE_KEY", "").strip()
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

def authenticate_gamesheet(email, password):
    """Logs into Firebase and exchanges the token with GameSheet's auth gateway."""
    if not FIREBASE_API_KEY:
        print("   ⚠️ GAMESHEET_FIREBASE_KEY is missing from environment secrets.")
        return None

    try:
        firebase_url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
        fb_payload = json.dumps({
            "email": email,
            "password": password,
            "returnSecureToken": True
        }).encode('utf-8')
        
        fb_req = urllib.request.Request(
            firebase_url,
            data=fb_payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(fb_req, timeout=15) as resp:
            fb_data = json.loads(resp.read().decode('utf-8'))
            firebase_id_token = fb_data.get("idToken")

        if not firebase_id_token:
            print("   ❌ Firebase authentication succeeded but no idToken returned.")
            return None

        gw_req = urllib.request.Request(
            AUTH_GATEWAY_URL,
            headers={
                "Authorization": f"Bearer {firebase_id_token}",
                "Origin": "https://gamesheet.app",
                "Referer": "https://gamesheet.app/",
                "Accept": "application/json, text/plain, */*",
                "User-Agent": "Mozilla/5.0"
            }
        )
        with urllib.request.urlopen(gw_req, timeout=15) as resp:
            gw_data = json.loads(resp.read().decode('utf-8'))
            access_token = gw_data.get("access")
            if access_token:
                return access_token

    except Exception as e:
        print(f"   ❌ Automated login failed: {e}")
    return None

active_token = None
if GAMESHEET_EMAIL and GAMESHEET_PASSWORD:
    print(f"🔐 Authenticating session for {GAMESHEET_EMAIL}...")
    active_token = authenticate_gamesheet(GAMESHEET_EMAIL, GAMESHEET_PASSWORD)

if active_token:
    headers['Authorization'] = f"Bearer {active_token}"
    headers['Cookie'] = f"__session={active_token}"
    print("🔑 Successfully generated and attached fresh GameSheet access token.")
elif FALLBACK_AUTH:
    headers['Authorization'] = FALLBACK_AUTH
    if FALLBACK_COOKIE:
        headers['Cookie'] = FALLBACK_COOKIE
    print("🍪 Using manual fallback token from secrets.")
else:
    print("⚠️ Warning: No active credentials found. Fetching anonymously.")

def clean_name(name):
    return ' '.join(str(name or "").split()).strip()

def clean_key(s):
    return re.sub(r'[^A-Z0-9]', '', str(s or '').upper())

def normalize(s):
    if not s:
        return ""
    s = str(s).upper()
    s = re.sub(r'[^A-Z0-9\s]', ' ', s)
    return ' '.join(s.split())

def is_burlington_eagles(name):
    c = clean_key(name)
    return "BURLINGTON" in c and "EAGLES" in c

def fetch_json(url, max_retries=2, silent=False):
    """Fetches JSON with automatic retry on transient gateway errors."""
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code in (502, 503, 504) and attempt < max_retries - 1:
                time.sleep(1.0)
                continue
            if not silent:
                print(f"   ❌ Fetch error for {url}: {e}")
            return None
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(1.0)
                continue
            if not silent:
                print(f"   ❌ Fetch error for {url}: {e}")
            return None
    return None

def fetch_paginated_roster(endpoint_name, s_id, s_name="", label="Roster"):
    """
    Fetches players or goalies in safe 1,000-record chunks with adaptive backoff
    to eliminate HTTP 502 Bad Gateway timeouts on massive multi-division seasons.
    """
    records = []
    offset = 0
    limit = 1000
    max_retries = 3

    while True:
        url = f"https://gamesheetstats.com/api/{endpoint_name}/standings/{s_id}?limit={limit}&offset={offset}"
        if offset == 0:
            print(f"   ➤ Fetching {label} URL: {url}")
        else:
            print(f"   ➤ Fetching Next {label} Page (Offset {offset}, Limit {limit})...")

        req = urllib.request.Request(url, headers=headers)
        chunk = None

        for attempt in range(max_retries):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    if data and "data" in data:
                        chunk = data.get("data", [])
                    elif isinstance(data, list):
                        chunk = data
                    else:
                        chunk = []
                break
            except urllib.error.HTTPError as e:
                print(f"   ⚠️ HTTP {e.code} on {label} offset {offset} (attempt {attempt+1}/{max_retries})")
                if e.code in (502, 503, 504) and limit > 250:
                    limit = limit // 2
                    url = f"https://gamesheetstats.com/api/{endpoint_name}/standings/{s_id}?limit={limit}&offset={offset}"
                    req = urllib.request.Request(url, headers=headers)
                time.sleep(1.5)
            except Exception as e:
                print(f"   ⚠️ Fetch error on {label} offset {offset} (attempt {attempt+1}/{max_retries}): {e}")
                time.sleep(1.5)

        if chunk is None or not chunk:
            break

        records.extend(chunk)
        if len(chunk) < limit:
            break

        offset += len(chunk)
        time.sleep(0.2)

    return records

def parse_game_boxscore(g_data, is_home):
    """
    Robust box score extractor for GameSheet game endpoints.
    Handles rosters, goals events, penalties, and goalie records.
    """
    if not g_data:
        return {}, []

    root = g_data.get("data") if isinstance(g_data, dict) and "data" in g_data and isinstance(g_data["data"], dict) else g_data
    if not isinstance(root, dict):
        return {}, []

    team_key = "home" if is_home else "visitor"
    team_obj = root.get(team_key) or {}
    team_id = team_obj.get("id") or team_obj.get("teamId")

    players_list = team_obj.get("players") or team_obj.get("roster") or team_obj.get("skaters") or []
    goalies_list = team_obj.get("goalies") or []

    skater_stats = {}
    stats_already_on_players = False

    for p in players_list:
        p_name = clean_name(f"{p.get('firstName', '')} {p.get('lastName', '')}") or clean_name(p.get("name") or p.get("title") or "")
        if not p_name:
            continue
        p_id = p.get("id") or p.get("playerId")
        jersey = str(p.get("jersey") or "")

        st = p.get("stats") or {}
        g = int(st.get("g") or st.get("goals") or 0)
        a = int(st.get("a") or st.get("assists") or 0)
        pts = int(st.get("pts") if st.get("pts") is not None else (g + a))
        pim = int(st.get("pim") or st.get("penalties") or 0)

        if "stats" in p and (g > 0 or a > 0 or pim > 0 or "g" in st or "goals" in st):
            stats_already_on_players = True

        key = clean_key(p_name)
        skater_stats[key] = {
            "name": p_name,
            "id": p_id,
            "jersey": jersey,
            "g": g,
            "a": a,
            "pts": pts,
            "pim": pim
        }

    if not stats_already_on_players:
        goals_events = root.get("goals") or []
        for goal in goals_events:
            g_team_id = goal.get("teamId") or goal.get("team_id")
            if team_id and g_team_id and str(g_team_id) != str(team_id):
                continue

            scorer = goal.get("scoredBy") or goal.get("scorer") or goal.get("player") or {}
            scorer_name = clean_name(f"{scorer.get('firstName', '')} {scorer.get('lastName', '')}") or clean_name(scorer.get("name") or scorer.get("title") or "")
            if scorer_name:
                s_key = clean_key(scorer_name)
                if s_key not in skater_stats:
                    skater_stats[s_key] = {"name": scorer_name, "id": scorer.get("id"), "jersey": str(scorer.get("jersey") or ""), "g": 0, "a": 0, "pts": 0, "pim": 0}
                skater_stats[s_key]["g"] += 1
                skater_stats[s_key]["pts"] += 1

            assists = goal.get("assists") or []
            if isinstance(goal.get("assistedBy"), list):
                assists = goal.get("assistedBy")
            elif goal.get("assistedBy"):
                assists = [goal.get("assistedBy")]
            if goal.get("assist1"):
                assists.append(goal.get("assist1"))
            if goal.get("assist2"):
                assists.append(goal.get("assist2"))

            for ast in assists:
                if not isinstance(ast, dict):
                    continue
                ast_name = clean_name(f"{ast.get('firstName', '')} {ast.get('lastName', '')}") or clean_name(ast.get("name") or ast.get("title") or "")
                if ast_name:
                    a_key = clean_key(ast_name)
                    if a_key not in skater_stats:
                        skater_stats[a_key] = {"name": ast_name, "id": ast.get("id"), "jersey": str(ast.get("jersey") or ""), "g": 0, "a": 0, "pts": 0, "pim": 0}
                    skater_stats[a_key]["a"] += 1
                    skater_stats[a_key]["pts"] += 1

        penalties_events = root.get("penalties") or []
        for pen in penalties_events:
            p_team_id = pen.get("teamId") or pen.get("team_id")
            if team_id and p_team_id and str(p_team_id) != str(team_id):
                continue
            p_player = pen.get("player") or pen.get("penalizedPlayer") or {}
            p_name = clean_name(f"{p_player.get('firstName', '')} {p_player.get('lastName', '')}") or clean_name(p_player.get("name") or p_player.get("title") or "")
            mins = int(pen.get("minutes") or pen.get("pim") or 2)
            if p_name:
                p_key = clean_key(p_name)
                if p_key not in skater_stats:
                    skater_stats[p_key] = {"name": p_name, "id": p_player.get("id"), "jersey": str(p_player.get("jersey") or ""), "g": 0, "a": 0, "pts": 0, "pim": 0}
                skater_stats[p_key]["pim"] += mins

    goalie_stats = []
    for gk in goalies_list:
        gk_name = clean_name(f"{gk.get('firstName', '')} {gk.get('lastName', '')}") or clean_name(gk.get("name") or gk.get("title") or "")
        if not gk_name:
            continue
        jersey = str(gk.get("jersey") or "")
        st = gk.get("stats") or {}
        ga = int(st.get("ga") or st.get("goalsAgainst") or 0)
        mins = int(st.get("min") or st.get("minutes") or st.get("min_played") or 45)
        so = int(st.get("so") or st.get("shutouts") or (1 if ga == 0 else 0))
        decision = gk.get("decision") or st.get("decision") or ""

        goalie_stats.append({
            "name": gk_name,
            "jersey": jersey,
            "ga": ga,
            "min": mins,
            "so": so,
            "decision": decision
        })

    return skater_stats, goalie_stats

# 2. Load Master Whitelist, Sources, and Exceptions
if not os.path.exists("master_teams.json"):
    raise FileNotFoundError("Critical error: master_teams.json is missing.")
with open("master_teams.json", "r", encoding="utf-8") as f:
    master_teams_db = json.load(f)

if not os.path.exists("sources.json"):
    raise FileNotFoundError("Critical error: sources.json is missing.")
with open("sources.json", "r", encoding="utf-8") as f:
    sources = json.load(f)

exceptions_db = []
if os.path.exists("exceptions.json"):
    try:
        with open("exceptions.json", "r", encoding="utf-8") as f:
            exc_data = json.load(f)
            exceptions_db = exc_data.get("tournament_team_exceptions", [])
            print(f"📋 Loaded {len(exceptions_db)} tournament exception rule(s) from exceptions.json.")
    except Exception as e:
        print(f"⚠️ Warning: Failed to parse exceptions.json: {e}")

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

lookup = {"U11 AA": {}, "U14 AA": {}}
for cohort in ["U11 AA", "U14 AA"]:
    for canonical, data in master_teams_db.get(cohort, {}).items():
        c_norm = normalize(canonical)
        lookup[cohort][c_norm] = canonical
        c_base = re.sub(r'\bU\d{1,2}AA\b|\b(U\d{1,2}|AA|AAA|A|BB|MD|MINOR|MAJOR)\b', '', c_norm).strip()
        c_base = ' '.join(c_base.split())
        if c_base:
            lookup[cohort][c_base] = canonical
        for alias in data.get("aliases", []):
            a_norm = normalize(alias)
            lookup[cohort][a_norm] = canonical
            a_base = re.sub(r'\bU\d{1,2}AA\b|\b(U\d{1,2}|AA|AAA|A|BB|MD|MINOR|MAJOR)\b', '', a_norm).strip()
            a_base = ' '.join(a_base.split())
            if a_base:
                lookup[cohort][a_base] = canonical

def check_team_exception(team_name, source_id):
    if not source_id or not exceptions_db:
        return None
    sid_str = str(source_id).strip()
    t_upper = str(team_name or "").upper().strip()
    for rule in exceptions_db:
        rule_sid = str(rule.get("tournament_id") or rule.get("source_id") or "").strip()
        rule_match = str(rule.get("team_match") or "").upper().strip()
        if rule_sid == sid_str and rule_match and rule_match in t_upper:
            return rule.get("target_cohort") or rule.get("target_division") or "U11 AA"
    return None

def resolve_master_team(team_name, div_title="", source_name="", forced_tier=None, source_id=None):
    forced_cohort = check_team_exception(team_name, source_id)
    if forced_cohort:
        cohort = forced_cohort
        t_norm = normalize(team_name)
        if t_norm in lookup.get(cohort, {}):
            return cohort, lookup[cohort][t_norm]

        t_base = re.sub(r'\bU\d{1,2}AA\b|\b(U11|U14|U\d{1,2}|AA|AAA|A|BB|MD|MINOR|MAJOR)\b', '', t_norm).strip()
        t_base = ' '.join(t_base.split())
        if t_base in lookup.get(cohort, {}):
            return cohort, lookup[cohort][t_base]

        for canonical in master_teams_db.get(cohort, {}):
            assoc_base = canonical.split()[0].upper()
            if len(assoc_base) >= 4 and assoc_base in t_base:
                return cohort, canonical
        return cohort, None

    team_div_text = f"{team_name} {div_title}".upper()
    full_text = f"{team_div_text} {source_name}".upper()

    age = None
    if re.search(r'\bU[- ]?11\b|\bATOM\b', full_text):
        age = "U11"
    elif re.search(r'\bU[- ]?14\b|\bBANTAM\b', full_text):
        age = "U14"

    if not age:
        return None, None

    if re.search(r'\bU\d{1,2}\s+A\b|\bTIER\s*2\b', team_div_text):
        if not re.search(r'\bAA\b', team_div_text):
            return None, None

    if re.search(r'\b(AAA|BB|CC|MD|SELECT|HL)\b', team_div_text):
        if not re.search(r'\bAA\b', team_div_text):
            return None, None

    is_aa = bool(re.search(r'\bAA\b', full_text)) or (forced_tier and forced_tier.upper() == "AA")
    if not is_aa:
        return None, None

    cohort = f"{age} AA"

    t_norm = normalize(team_name)
    if t_norm in lookup[cohort]:
        return cohort, lookup[cohort][t_norm]

    t_base = re.sub(r'\bU\d{1,2}AA\b|\b(U11|U14|U\d{1,2}|AA|AAA|A|BB|MD|MINOR|MAJOR)\b', '', t_norm).strip()
    t_base = ' '.join(t_base.split())
    if t_base in lookup[cohort]:
        return cohort, lookup[cohort][t_base]

    for canonical in master_teams_db.get(cohort, {}):
        assoc_base = canonical.split()[0].upper()
        if len(assoc_base) >= 4 and assoc_base in t_base:
            return cohort, canonical

    return cohort, None

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
            parent_div_title = clean_name(
                div_group.get("title") or 
                div_group.get("division", {}).get("title") or 
                div_group.get("name") or 
                ""
            )
            for row in div_group.get("standings", []):
                t_info = row.get("team", {})
                t_name = clean_name(t_info.get("title") or t_info.get("name", ""))
                t_id = t_info.get("id")
                stats = row.get("stats", {})
                row_div_title = clean_name(row.get("division", {}).get("title") or "")
                effective_div = row_div_title or parent_div_title

                cohort, canonical_name = resolve_master_team(t_name, effective_div, s_name, forced_tier=s_tier, source_id=s_id)

                if cohort and not canonical_name:
                    unmapped_audit.add((cohort, t_name, s_name, t_id))
                    continue
                if not cohort or not canonical_name:
                    continue

                if t_id:
                    team_id_to_master[int(t_id)] = (cohort, canonical_name)

                gp = int(stats.get("gp") or stats.get("GP") or 0)
                w = int(stats.get("w") or stats.get("W") or 0)
                l = int(stats.get("l") or stats.get("L") or 0)
                t = int(stats.get("t") or stats.get("T") or 0)
                pts = int(stats.get("pts") or stats.get("PTS") or 0)
                gf = int(stats.get("gf") or stats.get("GF") or 0)
                ga = int(stats.get("ga") or stats.get("GA") or 0)
                diff = int(stats.get("diff") or stats.get("DIFF") or 0)
                pim = int(stats.get("pim") or stats.get("PIM") or 0)

                ppg = int(stats.get("ppg") or stats.get("PPG") or 0)
                ppo = int(stats.get("ppo") or stats.get("PPO") or 0)
                ppga = int(stats.get("ppga") or stats.get("PPGA") or 0)
                ppoa = int(stats.get("ppoa") or stats.get("PPOA") or 0)
                shg = int(stats.get("shg") or stats.get("SHG") or 0)
                shga = int(stats.get("shga") or stats.get("SHGA") or 0)

                standings_db.append({
                    "team_id": t_id,
                    "team_name": canonical_name,
                    "division_title": cohort,
                    "age": cohort.split()[0],
                    "tier": cohort.split()[1],
                    "source_id": s_id,
                    "source_name": s_name,
                    "source_type": s_type,
                    "gp": gp,
                    "w": w,
                    "l": l,
                    "t": t,
                    "pts": pts,
                    "gf": gf,
                    "ga": ga,
                    "diff": diff,
                    "pim": pim,
                    "ppg": ppg,
                    "ppo": ppo,
                    "ppga": ppga,
                    "ppoa": ppoa,
                    "shg": shg,
                    "shga": shga
                })
    time.sleep(0.2)

# 4. STAGE 2: INGEST UNIFIED GAMES
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

        game_div_title = clean_name(g.get("division", {}).get("title") or "") if isinstance(g.get("division"), dict) else ""
        v_div = clean_name(visitor_obj.get("division", {}).get("title") or "") if isinstance(visitor_obj.get("division"), dict) else ""
        h_div = clean_name(home_obj.get("division", {}).get("title") or "") if isinstance(home_obj.get("division"), dict) else ""
        g_div = game_div_title or v_div or h_div or ""

        h_cohort, h_canonical = None, None
        if h_id and int(h_id) in team_id_to_master:
            h_cohort, h_canonical = team_id_to_master[int(h_id)]
        else:
            h_cohort, h_canonical = resolve_master_team(h_name, g_div, s_name, forced_tier=s_tier, source_id=s_id)
            if h_cohort and h_canonical and h_id:
                team_id_to_master[int(h_id)] = (h_cohort, h_canonical)

        v_cohort, v_canonical = None, None
        if v_id and int(v_id) in team_id_to_master:
            v_cohort, v_canonical = team_id_to_master[int(v_id)]
        else:
            v_cohort, v_canonical = resolve_master_team(v_name, g_div, s_name, forced_tier=s_tier, source_id=s_id)
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

# 5. STAGE 3: INGEST SKATERS & GOALIES
skaters_db = {}
goalies_db = {}

for src in all_sources:
    s_id, s_name, s_type, s_tier = src["id"], src["name"], src["type"], src["forced_tier"]
    print(f"\n📥 Roster Ingestion:    [{s_type.upper()}] {s_name} (ID: {s_id})")

    raw_skaters = fetch_paginated_roster("players", s_id, s_name, label="Skaters")
    print(f"   ✅ Total Skater records retrieved: {len(raw_skaters)}")

    mapped_sk = 0
    skipped_sk = 0

    for p in raw_skaters:
        p_name = clean_name(f"{p.get('firstName', '')} {p.get('lastName', '')}")
        if not p_name:
            skipped_sk += 1
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
                cohort, canonical_name = resolve_master_team(t_name, effective_div, s_name, forced_tier=s_tier, source_id=s_id)

            if not cohort or not canonical_name:
                skipped_sk += 1
                continue

            mapped_sk += 1
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
                "gp": gp, "g": g, "a": a, "pts": pts, "pim": pim,
                "game_logs": []
            })
    print(f"   🧮 Summary: {mapped_sk} Skaters mapped into dashboard | {skipped_sk} skipped.")
    time.sleep(0.2)

    raw_goalies = fetch_paginated_roster("goalies", s_id, s_name, label="Goalies")
    print(f"   ✅ Total Goalie records retrieved: {len(raw_goalies)}")

    mapped_gk = 0
    skipped_gk = 0

    for g in raw_goalies:
        g_name = clean_name(f"{g.get('firstName', '')} {g.get('lastName', '')}")
        if not g_name:
            skipped_gk += 1
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
                cohort, canonical_name = resolve_master_team(t_name, effective_div, s_name, forced_tier=s_tier, source_id=s_id)

            if not cohort or not canonical_name:
                skipped_gk += 1
                continue

            mapped_gk += 1
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
            tot_gp = goalies_db[goalie_key]["total_gp"]

            if tot_min > 0:
                goalies_db[goalie_key]["total_gaa"] = round((tot_ga * 45.0) / tot_min, 2)
            elif tot_gp > 0:
                goalies_db[goalie_key]["total_gaa"] = round(tot_ga / tot_gp, 2)
            else:
                goalies_db[goalie_key]["total_gaa"] = gaa

            if mins > 0:
                clean_gaa = round((ga * 45.0) / mins, 2)
            elif gp > 0:
                clean_gaa = round(ga / gp, 2)
            else:
                clean_gaa = gaa

            goalies_db[goalie_key]["sources"].append({
                "source_id": s_id, "source_name": s_name, "source_type": s_type,
                "gp": gp, "ga": ga, "min": mins, "gaa": clean_gaa, "so": so, "w": w, "l": l, "t": t_val,
                "game_logs": []
            })
    print(f"   🧮 Summary: {mapped_gk} Goalies mapped into dashboard | {skipped_gk} skipped.")
    time.sleep(0.2)

# 6. STAGE 4: INGEST INDIVIDUAL GAME BOX SCORES (U11 AA & U14 AA BURLINGTON EAGLES ONLY)
print("\n" + "="*70)
print("📥 Stage 4: Ingesting Game Box Scores (U11 AA & U14 AA Burlington Eagles Games)")
print("="*70)

eagles_target_games = []
for g in all_compiled_games:
    cohort = g.get("division")
    if cohort in ["U11 AA", "U14 AA"] and g.get("status") == "final":
        h_name = g.get("home_name", "")
        v_name = g.get("visitor_name", "")
        if is_burlington_eagles(h_name) or is_burlington_eagles(v_name):
            eagles_target_games.append(g)

print(f"🎯 Found {len(eagles_target_games)} final game(s) involving the Burlington Eagles to query for box scores.")

# Discovered working pattern cache across games
discovered_pattern = None

for idx, g in enumerate(eagles_target_games, 1):
    gid = g.get("game_id")
    s_id = str(g.get("source_id", "")).strip()
    s_name = g.get("source_name", "")
    s_type = g.get("source_type", "league")
    cohort = g.get("division")
    age = cohort.split()[0]
    tier = cohort.split()[1]
    is_eagles_home = is_burlington_eagles(g.get("home_name"))
    eagles_canonical = "Burlington Eagles"
    opp_name = g.get("visitor_name") if is_eagles_home else g.get("home_name")
    date_str = g.get("date", "")

    score_str = f"{g.get('home_goals', 0)} - {g.get('visitor_goals', 0)}" if is_eagles_home else f"{g.get('visitor_goals', 0)} - {g.get('home_goals', 0)}"
    result = g.get("home_result") if is_eagles_home else g.get("visitor_result")

    box_data = None

    if discovered_pattern:
        url = discovered_pattern.format(gid=gid, s_id=s_id)
        box_data = fetch_json(url, silent=True)
    else:
        # Probe candidate endpoints for GameSheet boxscore structure
        candidate_urls = [
            f"https://gamesheetstats.com/api/games/{gid}",
            f"https://gamesheetstats.com/api/seasons/{s_id}/games/{gid}",
            f"https://gamesheetstats.com/api/gamesheets/{gid}",
            f"https://gamesheetstats.com/api/scoresheets/{gid}",
            f"https://gamesheetstats.com/api/games/{gid}/boxscore",
            f"https://gamesheetstats.com/api/game/{gid}",
            f"https://gamesheetstats.com/api/gamesheet/{gid}",
            f"https://gamesheetstats.com/api/scoresheet/{gid}",
            f"https://gamesheetstats.com/api/unified-games/game/{gid}",
        ]
        patterns = [
            "https://gamesheetstats.com/api/games/{gid}",
            "https://gamesheetstats.com/api/seasons/{s_id}/games/{gid}",
            "https://gamesheetstats.com/api/gamesheets/{gid}",
            "https://gamesheetstats.com/api/scoresheets/{gid}",
            "https://gamesheetstats.com/api/games/{gid}/boxscore",
            "https://gamesheetstats.com/api/game/{gid}",
            "https://gamesheetstats.com/api/gamesheet/{gid}",
            "https://gamesheetstats.com/api/scoresheet/{gid}",
            "https://gamesheetstats.com/api/unified-games/game/{gid}",
        ]

        for p_idx, test_url in enumerate(candidate_urls):
            test_resp = fetch_json(test_url, silent=True)
            if test_resp and isinstance(test_resp, (dict, list)):
                box_data = test_resp
                discovered_pattern = patterns[p_idx]
                print(f"   🎯 Discovered working GameSheet box score endpoint: {discovered_pattern}")
                break

    if not box_data:
        print(f"   [{idx}/{len(eagles_target_games)}] Notice: Game #{gid} ({date_str} vs {opp_name}) boxscore not served by GameSheet API.")
        continue

    print(f"   [{idx}/{len(eagles_target_games)}] Box Score Mapped: Game #{gid} ({date_str} vs {opp_name})")
    skaters_stats, goalies_stats = parse_game_boxscore(box_data, is_home=is_eagles_home)

    # 1. Attach Skater Game Logs
    for sk_key, sk_val in skaters_stats.items():
        matched_skater = None
        for p in skaters_db.values():
            if p.get("team") == eagles_canonical and p.get("age") == age:
                if clean_key(p.get("name")) == sk_key:
                    matched_skater = p
                    break

        if not matched_skater:
            player_key = f"{sk_val['name']}_{eagles_canonical}_{age}".upper()
            matched_skater = {
                "name": sk_val["name"],
                "team": eagles_canonical,
                "team_id": g.get("home_id") if is_eagles_home else g.get("visitor_id"),
                "jersey": sk_val["jersey"],
                "position": "F",
                "age": age,
                "tier": tier,
                "total_gp": 0, "total_g": 0, "total_a": 0, "total_pts": 0, "total_pim": 0,
                "sources": []
            }
            skaters_db[player_key] = matched_skater

        src_entry = next((s for s in matched_skater["sources"] if str(s.get("source_id")) == s_id), None)
        if not src_entry:
            src_entry = next((s for s in matched_skater["sources"] if clean_key(s.get("source_name")) == clean_key(s_name)), None)

        if not src_entry:
            src_entry = {
                "source_id": s_id,
                "source_name": s_name,
                "source_type": s_type,
                "gp": 0, "g": 0, "a": 0, "pts": 0, "pim": 0,
                "game_logs": []
            }
            matched_skater["sources"].append(src_entry)

        if "game_logs" not in src_entry:
            src_entry["game_logs"] = []

        if not any(log.get("game_id") == gid or (log.get("date") == date_str and log.get("opponent") == opp_name) for log in src_entry["game_logs"]):
            src_entry["game_logs"].append({
                "game_id": gid,
                "date": date_str,
                "opponent": opp_name,
                "is_home": is_eagles_home,
                "score_str": score_str,
                "result": result,
                "g": sk_val["g"],
                "a": sk_val["a"],
                "pts": sk_val["pts"],
                "pim": sk_val["pim"]
            })

    # 2. Attach Goalie Game Logs
    for gk_val in goalies_stats:
        gk_key = clean_key(gk_val["name"])
        matched_goalie = None
        for g_entry in goalies_db.values():
            if g_entry.get("team") == eagles_canonical and g_entry.get("age") == age:
                if clean_key(g_entry.get("name")) == gk_key:
                    matched_goalie = g_entry
                    break

        if not matched_goalie:
            goalie_key = f"{gk_val['name']}_{eagles_canonical}_{age}".upper()
            matched_goalie = {
                "name": gk_val["name"],
                "team": eagles_canonical,
                "team_id": g.get("home_id") if is_eagles_home else g.get("visitor_id"),
                "jersey": gk_val["jersey"],
                "position": "G",
                "age": age,
                "tier": tier,
                "total_gp": 0, "total_ga": 0, "total_min": 0, "total_gaa": 0.0, "total_so": 0,
                "total_w": 0, "total_l": 0, "total_t": 0,
                "sources": []
            }
            goalies_db[goalie_key] = matched_goalie

        src_entry = next((s for s in matched_goalie["sources"] if str(s.get("source_id")) == s_id), None)
        if not src_entry:
            src_entry = next((s for s in matched_goalie["sources"] if clean_key(s.get("source_name")) == clean_key(s_name)), None)

        if not src_entry:
            src_entry = {
                "source_id": s_id,
                "source_name": s_name,
                "source_type": s_type,
                "gp": 0, "ga": 0, "min": 0, "gaa": 0.0, "so": 0, "w": 0, "l": 0, "t": 0,
                "game_logs": []
            }
            matched_goalie["sources"].append(src_entry)

        if "game_logs" not in src_entry:
            src_entry["game_logs"] = []

        if not any(log.get("game_id") == gid or (log.get("date") == date_str and log.get("opponent") == opp_name) for log in src_entry["game_logs"]):
            src_entry["game_logs"].append({
                "game_id": gid,
                "date": date_str,
                "opponent": opp_name,
                "is_home": is_eagles_home,
                "score_str": score_str,
                "result": result,
                "ga": gk_val["ga"],
                "min": gk_val["min"],
                "so": gk_val["so"],
                "decision": gk_val["decision"] or result
            })

    time.sleep(0.2)

# 7. EXPORT COMPILED STATS
output_data = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "total_skaters": len(skaters_db),
    "total_goalies": len(goalies_db),
    "total_standings_rows": len(standings_db),
    "total_games": len(all_compiled_games),
    "skaters": sorted(list(skaters_db.values()), key=lambda x: x["total_pts"], reverse=True),
    "goalies": sorted(list(goalies_db.values()), key=lambda x: (x["total_gaa"], -x["total_gp"])),
    "standings": standings_db,
    "games": all_compiled_games,
    "master_teams": master_teams_db
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

# 8. UNMAPPED AUDIT REPORT
print("\n📋 UNMAPPED TEAM AUDIT LOG")
print("-" * 70)
if unmapped_audit:
    for cohort, name, src, tid in sorted(list(unmapped_audit)):
        print(f"⚠️  [{cohort}] '{name}' (ID: {tid}) in {src}")
else:
    print("💯 Perfect Structural Integrity! All encountered teams were matched.")
print("-" * 70)
