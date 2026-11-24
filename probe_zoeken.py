import re, requests, time, html as H
B="https://nijmegen.bestuurlijkeinformatie.nl"
s=requests.Session(); s.headers["User-Agent"]="NijmegenVastgoedMonitor/1.0"
h=s.get(B+"/Search",timeout=60).text
tok=re.search(r'name="__RequestVerificationToken" type="hidden" value="([^"]+)"',h).group(1)
sel=re.search(r'<select[^>]*name="OrderBy".*?</select>',h,re.S).group(0)
print("ORDER", re.findall(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)',sel))
print("COOKIES", list(s.cookies.keys()))
time.sleep(5)
for page in (1,2):
    r=s.post(B+"/Search/Results",data={"Page":page,"Query":"verkamering","OrderBy":"1","__RequestVerificationToken":tok},
             headers={"X-Requested-With":"XMLHttpRequest"},timeout=60)
    print("STATUS",page,r.status_code,r.headers.get("content-type"),len(r.text))
    t=r.text
    print("TOTAAL", re.findall(r'\d+ tot \d+ van \d+ resultaten',t)[:1])
    for m in re.finditer(r'<h3.*?</h3>',t,re.S):
        blok=m.group(0)
        href=re.search(r'href="([^"]+)"',blok); 
        print("HIT", H.unescape(re.sub(r'<[^>]+>',' ',blok)).split()[:20], href.group(1) if href else None)
    print("RAW", re.sub(r'\s+',' ',t)[:1500])
    time.sleep(5)
