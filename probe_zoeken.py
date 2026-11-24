import re, requests, time
B="https://nijmegen.bestuurlijkeinformatie.nl"
s=requests.Session(); s.headers["User-Agent"]="NijmegenVastgoedMonitor/1.0"
h=s.get(B+"/Search",timeout=60).text
tok=re.search(r'name="__RequestVerificationToken" type="hidden" value="([^"]+)"',h).group(1)
time.sleep(5)
t=s.post(B+"/Search/Results",data={"Page":1,"Query":"verkamer*","OrderBy":"1","__RequestVerificationToken":tok},headers={"X-Requested-With":"XMLHttpRequest"},timeout=60).text
panels=re.split(r'(?=<div class="panel" aria-live)',t)
print("KOP", re.sub(r'\s+',' ',panels[0])[-400:])
for i,p in enumerate(panels[1:]):
    if i in (0,4) or 'Overzichtsitem' in p: print("PANEL",i, re.sub(r'\s+',' ',p)[:3000])
print("STAART", re.sub(r'\s+',' ',panels[-1])[-1500:])
time.sleep(5)
t2=s.post(B+"/Search/Results",data={"Page":1,"Query":"xqzv onbestaandwoord","OrderBy":"1","__RequestVerificationToken":tok},headers={"X-Requested-With":"XMLHttpRequest"},timeout=60).text
print("LEEG", re.sub(r'\s+',' ',t2)[:800])
time.sleep(5)
t3=s.post(B+"/Search/Results",data={"Page":1,"Query":"verkamer*","OrderBy":"1","__RequestVerificationToken":"fout"},headers={"X-Requested-With":"XMLHttpRequest"},timeout=60)
print("FOUTTOKEN", t3.status_code, re.sub(r'\s+',' ',t3.text)[:300])
