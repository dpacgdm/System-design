import json

with open(r'c:\Users\dpacg\System-design\tools\chill_questions.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

for i, q in enumerate(data, 1):
    print(f"{i:02d}. [Page {q['page']}] {q['title']}")
