#!/usr/bin/env python3
"""
De tekst van de artikelen in de planregels, per link uit bestemmingen.json.

WAAROM (28 november 2026). bestemming.py legt per pand vast welke bestemming
en aanduiding er gelden, met een link naar het artikel (verwijzingnaartekst).
Wat een aanduiding toestaat, staat alleen in die tekst. Bij Smetiusstraat 15
maakte 'horeca' binnen Gemengd - 3 (artikel 10 van Nijmegen Centrum -
Binnenstad) een hotel mogelijk, omdat dat artikel horeca categorie 1a, 1b en
2 toestaat en logies ook op de verdiepingen. In een ander plan kan dezelfde
naam iets anders betekenen. De tabel met planregels moet dus op de tekst zelf
rusten, niet op de naam.

WAT HET DOET. Elke link uit de verwijzingen (een plangebied heeft er soms
twee, met een komma) wordt zonder het #-deel een keer opgehaald, van HTML
naar tekst gezet en bewaard in planregels.json. Opnieuw na HERHAAL_DAGEN,
want een plan kan worden herzien; de bron is ruimtelijkeplannen.nl.

  python3 planregels.py --minuten 10   # ophalen, hervatbaar
  python3 planregels.py --proef
"""
import argparse
import datetime as dt
import html as _html
import json
import os
import re
import sys
import time
import urllib.request
from html.parser import HTMLParser

BESTEMMINGEN = "bestemmingen.json"
UIT_PAD = "planregels.json"
VERSLAG = "planregels_verslag.md"
HERHAAL_DAGEN = 183
PAUZE = 0.5
BRON = "https://ruimtelijkeplannen.nl/documents/"


def links_uit(bestemmingen):
    """
    {link zonder #-deel: [(laag, naam, plan)]} uit de verwijzingen van alle
    panden. Alleen links naar ruimtelijkeplannen.nl/documents.
    """
    uit = {}
    for rec in (bestemmingen.get("panden") or {}).values():
        for laag, verw in (rec.get("verwijzingen") or {}).items():
            for v in verw or []:
                for deel in (v.get("tekst") or "").split(","):
                    u = deel.strip().split("#")[0]
                    if not u.startswith(BRON):
                        continue
                    sleutel = (laag, v.get("naam") or "", v.get("plan") or "")
                    lijst = uit.setdefault(u, [])
                    if sleutel not in lijst:
                        lijst.append(sleutel)
    return uit


class _Tekst(HTMLParser):
    """HTML naar tekst, met een regelovergang na elk blokelement."""
    BLOK = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
            "br", "table", "ul", "ol", "section", "article"}
    WEG = {"script", "style", "nav", "header", "footer", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.delen, self.titel, self._weg, self._kop = [], "", 0, None

    def handle_starttag(self, tag, attrs):
        if tag in self.WEG:
            self._weg += 1
        if tag in ("h1", "h2", "h3") and not self.titel:
            self._kop = []
        if tag in self.BLOK:
            self.delen.append("\n")

    def handle_endtag(self, tag):
        if tag in self.WEG and self._weg:
            self._weg -= 1
        if tag in ("h1", "h2", "h3") and self._kop is not None:
            self.titel = " ".join("".join(self._kop).split())
            self._kop = None
        if tag in self.BLOK:
            self.delen.append("\n")

    def handle_data(self, data):
        if self._weg:
            return
        self.delen.append(data)
        if self._kop is not None:
            self._kop.append(data)


def tekst_uit(html):
    """(titel, tekst) uit een HTML-pagina; lege regels samengevoegd."""
    p = _Tekst()
    p.feed(html or "")
    regels = [" ".join(r.split()) for r in "".join(p.delen).split("\n")]
    tekst = "\n".join(r for r in regels if r)
    titel = p.titel
    if not titel:
        m = re.search(r"<title>(.*?)</title>", html or "", re.S)
        titel = " ".join(_html.unescape(m.group(1)).split()) if m else ""
    return titel, tekst


def te_halen(link, opgeslagen, vandaag=None):
    """Of een link (opnieuw) gehaald moet worden."""
    rec = opgeslagen.get(link)
    if not rec or not rec.get("tekst"):
        return True
    vandaag = vandaag or dt.date.today()
    try:
        gehaald = dt.date.fromisoformat(rec.get("gehaald") or "")
    except ValueError:
        return True
    return (vandaag - gehaald).days > HERHAAL_DAGEN


def _haal(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "NijmegenVastgoedMonitor/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def lees(pad=UIT_PAD):
    try:
        with open(pad, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def ophalen(minuten, bestemmingen_pad=BESTEMMINGEN, uit_pad=UIT_PAD,
            verslag_pad=VERSLAG, haal=None):
    haal = haal or _haal
    with open(bestemmingen_pad, encoding="utf-8") as f:
        links = links_uit(json.load(f))
    opgeslagen = lees(uit_pad)
    artikelen = opgeslagen.setdefault("artikelen", {})
    wachtrij = [u for u in sorted(links) if te_halen(u, artikelen)]
    begin, gedaan, fouten = time.monotonic(), 0, []
    for u in wachtrij:
        if minuten and time.monotonic() - begin > minuten * 60:
            break
        try:
            titel, tekst = tekst_uit(haal(u))
        except Exception as e:
            # Een mislukte ophaling laat een oud antwoord staan: niet
            # opgehaald is geen lege tekst.
            fouten.append(f"{u}: {type(e).__name__} {e}")
            continue
        if not tekst:
            fouten.append(f"{u}: lege tekst")
            continue
        artikelen[u] = {"titel": titel, "tekst": tekst,
                        "gehaald": dt.date.today().isoformat(),
                        "gebruik": [list(x) for x in links[u]]}
        gedaan += 1
        time.sleep(PAUZE)
    # Het gebruik bijwerken voor wat al stond: welke bestemmingen en plannen
    # naar een artikel wijzen, verandert met elke ronde van bestemming.py.
    for u, rec in artikelen.items():
        if u in links:
            rec["gebruik"] = [list(x) for x in links[u]]
    opgeslagen["bijgewerkt"] = dt.date.today().isoformat()
    with open(uit_pad, "w", encoding="utf-8") as f:
        json.dump(opgeslagen, f, ensure_ascii=False, indent=1)
    rest = len(wachtrij) - gedaan - len(fouten)
    r = ["# Planregels", "",
         f"- links in bestemmingen.json: {len(links)}",
         f"- deze ronde opgehaald: {gedaan}",
         f"- mislukt: {len(fouten)}",
         f"- nog te doen (tijd op): {max(rest, 0)}",
         f"- artikelen in {uit_pad}: {len(artikelen)}", ""]
    if fouten:
        r.append("## Mislukt")
        r.append("")
        r.extend(f"- {x}" for x in fouten[:50])
        r.append("")
    r.append("## Titels")
    r.append("")
    for u in sorted(artikelen):
        a = artikelen[u]
        r.append(f"- {a.get('titel') or '(geen titel)'}: "
                 f"{len(a.get('tekst') or '')} tekens, `{u}`")
    with open(verslag_pad, "w", encoding="utf-8") as f:
        f.write("\n".join(r) + "\n")
    print("\n".join(r[:8]))
    return 0


def proef():
    import tempfile
    afw = []
    best = {"panden": {"P1": {"verwijzingen": {
        "enkelbestemming": [{"naam": "Gemengd - 3", "plan": "BP5000",
                             "tekst": BRON + "BP5000/r_BP5000_2.10.html"}],
        "dubbelbestemming": [{"naam": "Archeologie 2", "plan": "FBP",
                              "tekst": BRON + "FBP/r_FBP.html#_6_A2"}],
        "bestemmingsplangebied": [{"naam": "Binnenstad", "plan": "BP5000",
                                   "tekst": BRON + "BP5000/r_BP5000.html,"
                                   + BRON + "BP5000/t_BP5000.html"}],
        "functieaanduiding": [{"naam": "horeca", "plan": "BP5000",
                               "tekst": ""}]}},
        "P2": {"verwijzingen": {"dubbelbestemming": [
            {"naam": "Archeologie 3", "plan": "FBP",
             "tekst": BRON + "FBP/r_FBP.html#_6_A3"}]}}}}
    links = links_uit(best)
    if sorted(links) != sorted([BRON + "BP5000/r_BP5000_2.10.html",
                                BRON + "FBP/r_FBP.html",
                                BRON + "BP5000/r_BP5000.html",
                                BRON + "BP5000/t_BP5000.html"]):
        afw.append(f"links: kommalijst gesplitst en #-deel eraf? {sorted(links)}")
    if len(links.get(BRON + "FBP/r_FBP.html", [])) != 2:
        afw.append("twee bestemmingen die naar hetzelfde artikel wijzen, "
                   "staan niet allebei in het gebruik")

    titel, tekst = tekst_uit(
        "<html><head><title>Ruimtelijke plannen</title><style>x{}</style>"
        "</head><body><nav>menu</nav><h2>Artikel 10 Gemengd - 3</h2>"
        "<p>10.1 Bestemmingsomschrijving</p><ul><li>a. wonen;</li>"
        "<li>b. horeca  categorie 1b</li></ul><script>var a=1;</script>"
        "</body></html>")
    if titel != "Artikel 10 Gemengd - 3":
        afw.append(f"titel: {titel!r}")
    if tekst.splitlines() != ["Artikel 10 Gemengd - 3",
                              "10.1 Bestemmingsomschrijving", "a. wonen;",
                              "b. horeca categorie 1b"]:
        afw.append(f"tekst: menu, script of opmaak niet weg: {tekst!r}")

    vandaag = dt.date(2026, 11, 28)
    if not te_halen("x", {}, vandaag):
        afw.append("een nieuwe link wordt niet gehaald")
    if te_halen("x", {"x": {"tekst": "t", "gehaald": "2026-11-01"}}, vandaag):
        afw.append("een verse tekst wordt opnieuw gehaald")
    if not te_halen("x", {"x": {"tekst": "t", "gehaald": "2026-01-01"}},
                    vandaag):
        afw.append("een tekst ouder dan HERHAAL_DAGEN wordt niet ververst")

    # Ophalen met een nagebootste bron: een link mislukt en laat de oude
    # tekst staan, de rest komt binnen.
    d = tempfile.mkdtemp()
    bp, up, vp = (os.path.join(d, n) for n in ("b.json", "u.json", "v.md"))
    with open(bp, "w", encoding="utf-8") as f:
        json.dump(best, f)
    oud = {"artikelen": {BRON + "FBP/r_FBP.html": {
        "titel": "oud", "tekst": "oude tekst", "gehaald": "2026-01-01"}}}
    with open(up, "w", encoding="utf-8") as f:
        json.dump(oud, f)

    def nep(u):
        if "FBP" in u:
            raise OSError("403")
        return f"<h2>{u.rsplit('/', 1)[-1]}</h2><p>tekst</p>"
    global PAUZE
    pauze, PAUZE = PAUZE, 0
    try:
        stdout, sys.stdout = sys.stdout, open(os.devnull, "w")
        try:
            ophalen(0, bp, up, vp, haal=nep)
        finally:
            sys.stdout.close()
            sys.stdout = stdout
    finally:
        PAUZE = pauze
    u = lees(up).get("artikelen", {})
    if u.get(BRON + "FBP/r_FBP.html", {}).get("tekst") != "oude tekst":
        afw.append("een mislukte ophaling overschrijft de oude tekst")
    if u.get(BRON + "BP5000/r_BP5000_2.10.html", {}).get("titel") != \
            "r_BP5000_2.10.html":
        afw.append(f"een gelukte ophaling staat er niet in: {sorted(u)}")
    if "- mislukt: 1" not in open(vp, encoding="utf-8").read():
        afw.append("het verslag telt de mislukte ophaling niet")

    for a in afw:
        print("AFWIJKING: " + a, file=sys.stderr)
    print(f"Proef planregels: {len(afw)} afwijkingen", file=sys.stderr)
    return 1 if afw else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proef", action="store_true")
    ap.add_argument("--minuten", type=float, default=10)
    a = ap.parse_args()
    if a.proef:
        return proef()
    return ophalen(a.minuten)


if __name__ == "__main__":
    sys.exit(main())
