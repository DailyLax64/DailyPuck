import urllib.request
import os
import re
from bs4 import BeautifulSoup

raw_cookie = os.environ.get("GAMESHEET_COOKIE", "")
session_cookie = raw_cookie.strip().replace('\n', '').replace('\r', '') if raw_cookie else None

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Referer': 'https://gamesheetstats.com/'
}
if session_cookie:
    headers['Cookie'] = session_cookie

# Request the main games page for Tri-County AA
url = "https://gamesheetstats.com/seasons/15497/games"
print(f"Fetching HTML from: {url}\n")

req = urllib.request.Request(url, headers=headers)
try:
    with urllib.request.urlopen(req) as resp:
        html = resp.read().decode('utf-8')
        
        # Parse the HTML
        soup = BeautifulSoup(html, 'html.parser')
        
        # Find all hyperlinks that point to a specific game ID (e.g., /games/2997756)
        game_links = soup.find_all('a', href=lambda h: h and '/games/' in h and re.search(r'\d+$', h))
        
        print(f"✅ Success! Found {len(game_links)} game links on the page.\n")
        
        print("=== FIRST 5 GAMES EXTRACTED ===")
        # We will look at the parent container (like a table row <tr>) for each link to grab all the text
        for link in game_links[:5]:
            game_id = link['href'].split('/')[-1]
            
            # Find the row containing this game link
            row = link.find_parent('tr')
            if row:
                # Extract all text elements in this row
                row_data = list(row.stripped_strings)
                print(f"Game ID: {game_id}")
                print(f"Row Data: {row_data}\n")
            else:
                # Fallback if it's not a table row (e.g. mobile div cards)
                parent_div = link.find_parent('div')
                print(f"Game ID: {game_id}")
                print(f"Card Data: {list(parent_div.stripped_strings)}\n")
                
except Exception as e:
    print(f"❌ Failed to parse HTML: {e}")
