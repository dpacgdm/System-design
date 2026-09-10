import urllib.request
import re
import json

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

all_questions = []

for page in range(1, 6):
    url = f'https://chillinterview.com/learn/system-design-questions?page={page}'
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
            
            # Look for titles in the Next.js hydration payload or HTML
            # Titles start with "Design "
            # Let's find matches like: "title":"Design ..."
            matches = re.findall(r'"title":"(Design [^"]+)"', html)
            if not matches:
                # Try finding in HTML tags: <h3>Design ...</h3> or <h2>Design ...</h2>
                matches = re.findall(r'<h[23][^>]*>(Design [^<]+)</h[23]>', html)
            
            # Deduplicate preserving order
            seen = set()
            page_titles = []
            for m in matches:
                if m not in seen and "Questions" not in m and "Articles" not in m:
                    seen.add(m)
                    page_titles.append(m)
                    
            print(f'Page {page}: found {len(page_titles)} questions')
            for t in page_titles:
                all_questions.append({'page': page, 'title': t})
    except Exception as e:
        print(f'Error on page {page}: {e}')

print(f'Total unique questions: {len(all_questions)}')
with open(r'c:\Users\dpacg\System-design\tools\chill_questions.json', 'w', encoding='utf-8') as f:
    json.dump(all_questions, f, indent=2)
