import os

with open('server.py', 'r', encoding='utf-8') as f:
    text = f.read()

prefix = 'def serve_dashboard(self):\n        html = """'
start_idx = text.find(prefix)
if start_idx != -1:
    content_start = start_idx + len(prefix)
    suffix = '"""\n\n        body = html.encode'
    end_idx = text.find(suffix, content_start)
    if end_idx != -1:
        html = text[content_start:end_idx]
        with open('public/index.html', 'w', encoding='utf-8') as out:
            out.write(html)
        print(f"Extracted {len(html)} bytes to public/index.html")
    else:
        print("Suffix not found")
else:
    print("Prefix not found")
