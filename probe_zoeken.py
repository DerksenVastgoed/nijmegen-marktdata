import re, requests, time, html as H, datetime as dt
B="https://nijmegen.bestuurlijkeinformatie.nl"
MND={m:i+1 for i,m in enumerate("januari februari maart april mei juni juli augustus september oktober november december".split())}
s=requests.Session(); s.headers["User-Agent"]="NijmegenVastgoedMonitor/1.0"
h=s.get(B+"/Search",timeout=60).text
tok=re.search(r'name="__RequestVerificationToken" type="hidden" value="([^"]+)"',h).group(1)
TERMEN=["splits*","verkamer*","kamerverhuur","onzelfstandig*","opkoopbescherming","short stay","vakantieverhuur","huisvestingsverordening","transformatie","optoppen","middenhuur","erfpacht","woningsplitsing","omgevingsplan","plint*","leegstand"]
grens=dt.date(2026,8,26)
for term in TERMEN:
    data=[]; totaal=None
    for page in range(1,6):
        time.sleep(5)
        r=s.post(B+"/Search/Results",data={"Page":page,"Query":term,"OrderBy":"1","__RequestVerificationToken":tok},headers={"X-Requested-With":"XMLHttpRequest"},timeout=60)
        t=r.text
        m=re.search(r'van (\d+) resultaten',t); totaal=m.group(1) if m else totaal
        ds=[]
        for p in re.finditer(r'<p>\s*(\d{1,2}) (\w+) (\d{4}) --',t):
            try: ds.append(dt.date(int(p.group(3)),MND[p.group(2)],int(p.group(1))))
            except Exception: pass
        titels=[H.unescape(re.sub(r'<[^>]+>',' ',x)).split() for x in re.findall(r'<h3.*?</h3>',t,re.S)]
        data+=list(zip(ds,[" ".join(x)[:70] for x in titels]))
        if not ds or min(ds)<grens: break
    recent=[x for x in data if x[0]>=grens]
    print("TERM",term,"totaal",totaal,"sinds 26-08:",len(recent),"(pagina's gelezen tot",min([d for d,_ in data]) if data else None,")")
    for d,ti in recent[:6]: print("   ",d,ti)
