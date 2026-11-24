import re, requests, time, html as H, datetime as dt, collections
B="https://nijmegen.bestuurlijkeinformatie.nl"
MND={m:i+1 for i,m in enumerate("januari februari maart april mei juni juli augustus september oktober november december".split())}
s=requests.Session(); s.headers["User-Agent"]="NijmegenVastgoedMonitor/1.0"
h=s.get(B+"/Search",timeout=60).text
tok=re.search(r'name="__RequestVerificationToken" type="hidden" value="([^"]+)"',h).group(1)
TERMEN=["verkamer*","kamerverhuur","onzelfstandig*","woningsplitsing","splitsen","opkoopbescherming","short stay","middenhuur","optoppen","plint*","huisvestingsverordening"]
grens=dt.date(2026,8,26)
docs={}
for term in TERMEN:
    for page in range(1,13):
        time.sleep(5)
        t=s.post(B+"/Search/Results",data={"Page":page,"Query":term,"OrderBy":"1","__RequestVerificationToken":tok},headers={"X-Requested-With":"XMLHttpRequest"},timeout=60).text
        panels=re.split(r'<div class="panel" aria-live',t)[1:]
        if not panels: break
        oud=False
        for p in panels:
            href=re.search(r'href="([^"]+)"',p); m=re.search(r'<p>\s*(\d{1,2}) (\w+) (\d{4}) --',p)
            ti=" ".join(H.unescape(re.sub(r'<[^>]+>',' ',re.search(r'<h3.*?</h3>',p,re.S).group(0))).split())[:80]
            soort=re.search(r'aria-label="([^"]+)"',p); 
            if not (href and m): continue
            d=dt.date(int(m.group(3)),MND[m.group(2)],int(m.group(1)))
            if d<grens: oud=True; continue
            k=H.unescape(href.group(1))
            docs.setdefault(k,{"d":d,"t":ti,"s":soort.group(1) if soort else "?","termen":set()})["termen"].add(term)
        if oud: break
print("UNIEK sinds 26-08:",len(docs))
print("SOORT",collections.Counter(v["s"] for v in docs.values()))
wk=collections.Counter(v["d"].isocalendar()[1] for v in docs.values()); print("PERWEEK",sorted(wk.items()))
for term in TERMEN: print("ALLEEN",term,sum(1 for v in docs.values() if v["termen"]=={term}), "totaal", sum(1 for v in docs.values() if term in v["termen"]))
for k,v in sorted(docs.items(),key=lambda x:x[1]["d"],reverse=True): print("DOC",v["d"],v["s"][:5],"|",v["t"],"|",",".join(sorted(v["termen"])))
