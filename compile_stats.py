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

# Authenticate dynamically if credentials exist
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

def normalize(s):
    if not s:
        return ""
    s = str(s).upper()
    s = re.sub(r'[^A-Z0-9\s]', ' ', s)
    return ' '.join(s.split())

def fetch_json(url, max_retries=3):
    """Fetches JSON with automatic retry on transient gateway errors."""
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code in (502, 503, 504) and attempt < max_retries - 1:
                time.sleep(1.5)
                continue
            print(f"   ❌ Fetch error for {url}: {e}")
            return None
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(1.5)
                continue
            print(f"   ❌ Fetch error for {url}: {e}")
            return None
    return None

def fetch_paginated_roster(endpoint_name, s_id, s_name="", label="Roster"):
    """
    Fetches players or goalies in safe 1,000-record chunks with adaptive backoff
    to eliminate HTTP 502 Bad Gateway timeouts on massive multi-division seasons like OMHA Exhibition.
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
                break  # Success
            except urllib.error.HTTPError as e:
                print(f"   ⚠️ HTTP {e.code} on {label} offset {offset} (attempt {attempt+1}/{max_retries})")
                if e.code in (502, 503, 504) and limit > 250:
                    # Cut chunk size in half if server runs out of memory
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

# Build normalized lookup dictionaries
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
    """Checks if a team/source combination matches a defined exception rule."""
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
    # Check exception rule first
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

# Master Storage
team_id_to_master = {}
standings_db = []
unmapped_audit = set()

# 3. STAGE 1: INGEST STANDINGS & RAW SPECIAL TEAMS COUNTS
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
