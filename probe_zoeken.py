import re, requests, time
B="https://nijmegen.bestuurlijkeinformatie.nl"
s=requests.Session(); s.headers["User-Agent"]="NijmegenVastgoedMonitor/1.0"
h=s.get(B+"/Search?searchString=verkamering",timeout=60).text
print("LEN",len(h))
for m in re.finditer(r'<form[^>]*>|data-ajax[-\w]*="[^"]*"|<input[^>]*>|<select[^>]*name="[^"]*"', h):
    print("ATTR", m.group(0)[:300])
for m in re.finditer(r'<script[^>]*src="([^"]+)"', h): print("SCRIPT", m.group(1))
time.sleep(5)
js=s.get(B+"/assets/search.min.js",timeout=60).text
for m in re.finditer(r'.{0,120}(url|ajax|Search|search)\s*[:=(].{0,160}', js):
    print("JS", m.group(0)[:300])
