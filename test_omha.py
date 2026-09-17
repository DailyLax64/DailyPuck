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

# Check Tri-County AA (15497)
url_standings = "https://gamesheetstats.com/api/standings/15497?"
req = urllib.request.Request(url_standings, headers=headers)
with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read().decode('utf-8'))
    first_row = data["data"][0]["standings"][0]
    
    print("=== WHAT IS INSIDE row['division']? ===")
    print(json.dumps(first_row.get("division"), indent=2))

# Test possible Division / Season endpoints to see if we can get all division names
division_id = data["data"][0].get("divisionId")
print(f"\nTesting divisionId: {division_id}")

test_urls = [
    f"https://gamesheetstats.com/api/divisions/{division_id}",
    f"https://gamesheetstats.com/api/seasons/15497/divisions",
    f"https://gamesheetstats.com/api/divisions?seasonId=15497"
]

for url in test_urls:
    try:
        r = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(r) as res:
            res_data = json.loads(res.read().decode('utf-8'))
            print(f"\n✅ SUCCESS endpoint: {url}")
            print(json.dumps(res_data, indent=2)[:300] + "...")
            break
    except Exception as e:
        print(f"❌ Failed {url}: {e}")
