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
    # De eerste kop op ruimtelijkeplannen.nl is de plannaam (gemeten 28
    # november: 61 keer de plannaam als titel). De artikelnaam staat als
    # regel "Artikel 10 Gemengd - 3"; die heeft voorrang.
    artikel = artikel_uit_tekst(tekst)
    titel = artikel or p.titel
    if not titel:
        m = re.search(r"<title>(.*?)</title>", html or "", re.S)
        titel = " ".join(_html.unescape(m.group(1)).split()) if m else ""
    return titel, tekst


# DE BEPALINGEN PER AANDUIDING (28 november 2026). Gemeten op de 61
# artikelen na de eerste ronde: de vorm "x. ter plaatse van de aanduiding
# 'naam' tevens voor ..." komt in elk plan voor, maar het plan Oost (BP13000)
# gebruikt dubbele of ongelijke aanhalingstekens, afkortingen ("b", "prr")
# en een tikfout ("specfieke"), en PDOK schrijft de naam anders dan de tekst
# ("horeca van categorie .1a" tegen 'horeca van horecacategorie 1a',
# "specifieke vorm van dienstverlening - .50%" tegen '...-50%'). Zonder deze
# gelijkmaking koppelden 165 van de 240 aanduidingen.
_BEPALING = re.compile(
    r"^(?P<lid>[a-z]{1,2})\.\s*ter plaats(?:e)? van de (?:middels de "
    r"aanduiding \S+ verbonden )?aanduiding(?:en)?\s+"
    r"[\'\"\u2018\u2019\u201c\u201d](?P<naam>[^\'\"\u2018\u2019\u201c\u201d]+)"
    r"[\'\"\u2018\u2019\u201c\u201d]+\s*(?P<rest>.*)$", re.I)
# Afkortingen zoals ze in de tekst staan, alleen wat gemeten is.
AFKORTINGEN = {"b": "bedrijf", "prr": "praktijkruimte"}


def gelijk(naam):
    """Een naam van een aanduiding gelijkgemaakt voor de koppeling."""
    n = (naam or "").lower().replace("specfieke", "specifieke")
    n = n.replace("horecacategorie", "categorie")
    n = re.sub(r"\(.*?\)", "", n)
    n = re.sub(r"[^a-z0-9%]", "", n)
    return AFKORTINGEN.get(n, n)


def bepalingen(tekst):
    """{gelijke naam: {"lid", "naam", "tekst"}} uit een artikeltekst."""
    uit = {}
    for regel in (tekst or "").splitlines():
        m = _BEPALING.match(regel.strip())
        if not m:
            continue
        sleutel = gelijk(m.group("naam"))
        uit.setdefault(sleutel, {"lid": m.group("lid"),
                                 "naam": m.group("naam").strip(),
                                 "tekst": m.group("rest").strip()})
    return uit


def artikel_uit_tekst(tekst):
    """
    De naam van het artikel uit de tekst van de pagina.

    Eerst de regel "direct naar inhoud van Artikel 10 Gemengd - 3", die
    bovenaan elke pagina staat. De eerste regel die met "Artikel" begint, kan
    uit het menu komen: gemeten 28 november, een paar pagina's kregen zo
    "Artikel 1 Begrippen".
    """
    for r in (tekst or "").splitlines():
        m = re.match(r"^direct naar inhoud van (Artikel \d+[a-z]?\b.*)$", r)
        if m:
            return m.group(1).strip()
    for r in (tekst or "").splitlines():
        if re.match(r"^Artikel \d+[a-z]?\b", r):
            return r
    return ""


def artikel_deel(tekst, fragment):
    """
    Het stuk van een pagina dat bij een artikel hoort, voor plannen die al
    hun regels op een pagina hebben. Het #-deel van de link noemt het
    artikel: "_15_Wonen" is artikel 15. None als het niet te vinden is.

    WAAROM (28 november 2026). De links worden zonder #-deel opgehaald, zodat
    een pagina een keer komt. Bij de plannen BPa1000, BPa2000 en BPa3000
    staat alles op een pagina, en las de functieruimte daar de eerste
    bestemming van de pagina (Bedrijf) in plaats van Wonen: 145 panden met
    Wonen kregen zo 'bedrijven' als hoofdfunctie. Gemeten: 353 van de 1.295
    links naar een enkelbestemming hebben een #-deel.
    """
    m = re.match(r"^_(\d+[a-z]?)_", fragment or "")
    if not m:
        return None
    nr = m.group(1)
    regels = (tekst or "").splitlines()
    for i, r in enumerate(regels):
        if not re.match(rf"^Artikel {re.escape(nr)}\b", r):
            continue
        if i + 1 >= len(regels) or not re.match(
                rf"^{re.escape(nr)}\.1\b", regels[i + 1]):
            continue  # de inhoudsopgave, niet het artikel zelf
        uit = [r]
        for r2 in regels[i + 1:]:
            m2 = re.match(r"^Artikel (\d+[a-z]?)\b", r2)
            if m2 and m2.group(1) != nr:
                break
            uit.append(r2)
        return "\n".join(uit)
    return None


def tekst_voor(link, artikelen):
    """
    (titel, tekst) van het artikel waar een link naar wijst, of (None, None)
    als het niet is opgehaald. Met een #-deel alleen dat artikel; is dat in
    de pagina niet te vinden, dan (titel van de pagina, None).
    """
    basis, _, frag = (link or "").partition("#")
    art = artikelen.get(basis)
    if not art or not art.get("tekst"):
        return None, None
    if frag and re.match(r"^_\d", frag):
        deel = artikel_deel(art["tekst"], frag)
        if deel is None:
            return artikeltitel(art), None
        return deel.splitlines()[0], deel
    return artikeltitel(art), art["tekst"]


def artikeltitel(art):
    """De naam van het artikel uit de tekst, anders de opgeslagen titel.
    Teksten van voor 28 november hebben de plannaam als titel, en worden pas
    na HERHAAL_DAGEN opnieuw gehaald."""
    return artikel_uit_tekst(art.get("tekst") or "") or art.get("titel") or ""


def bepaling_aanduiding(rec, artikelen):
    """
    Per functieaanduiding van een pand de bepaling uit het artikel van zijn
    enkelbestemming: [(aanduiding, artikeltitel of None, bepaling of None)].
    None als bepaling: het artikel is er, maar de aanduiding staat er niet
    in (dan kan hij in een algemeen hoofdstuk staan); None als titel: het
    artikel is niet opgehaald. Die twee zeggen iets anders dan "geen".
    """
    links = [v.get("tekst") or ""
             for v in ((rec.get("verwijzingen") or {}).get("enkelbestemming")
                       or []) if v.get("tekst")]
    uit = []
    for naam in rec.get("functieaanduiding") or []:
        titel, gevonden = None, None
        for u in links:
            t, tekst = tekst_voor(u, artikelen)
            if t is None:
                continue
            titel = t
            if not tekst:
                continue
            b = bepalingen(tekst).get(gelijk(naam))
            if b:
                gevonden = b
                break
        uit.append((naam, titel, gevonden))
    return uit


# DE FUNCTIES VAN EEN BESTEMMING (28 november 2026). Lid 1 heeft in elk plan
# de vorm "De voor 'X' aangewezen gronden zijn bestemd voor:" met genummerde
# onderdelen. Gemeten op de 61 artikelen: wat geen aanduiding is, is een
# hoofdfunctie of een bijzaak. De bijzaken en de woordenlijst hieronder komen
# uit die meting, niet uit een aanname.
BIJZAAK = ("bijbehorende", "wadi", "ondergeschikte", "ondersteunende",
           "aan huis verbonden", "ontsluitingswegen", "opslag en uitstalling")
FUNCTIES = ("wonen", "detailhandel", "dienstverlening", "horeca", "kantoren",
            "maatschappelijke voorzieningen", "cultuur en ontspanning",
            "bedrijven", "hotel")
# Een hotel noemt een bepaling letterlijk; 'pension' en 'logies' tellen mee.
_HOTEL = re.compile(r"hotel|pension|logies", re.I)


def lid_een(tekst):
    """De onderdelen van de bestemmingsomschrijving, of None zonder lid 1."""
    regels = (tekst or "").splitlines()
    for i, r in enumerate(regels):
        m = re.match(r"^(\d+[a-z]?)\.1\s+Bestemmingsomschrijving$", r, re.I)
        if m and i + 1 < len(regels) and regels[i + 1].startswith("De voor"):
            uit = []
            for r2 in regels[i + 2:]:
                if re.match(rf"^{re.escape(m.group(1))}\.2\b", r2):
                    break
                uit.append(r2)
            return uit
    return None


def functies_in(tekst):
    """De functies uit de woordenlijst die in een tekst staan, op volgorde."""
    t = (tekst or "").lower()
    # Als heel woord: 'horecabedrijven' is horeca, geen 'bedrijven' (gemeten
    # 28 november: zonder woordgrens telde 'bedrijven' 389 keer als extra).
    uit = [f for f in FUNCTIES
           if f != "hotel" and re.search(rf"\b{re.escape(f)}\b", t)]
    if "horecabedrijven" in t and "horeca" not in uit:
        uit.append("horeca")
    if _HOTEL.search(t):
        uit.append("hotel")
    return uit


def hoofdfuncties(tekst):
    """
    De functies die de bestemming zelf toestaat (zonder aanduiding en
    zonder bijzaken), of None als het artikel geen lid 1 heeft.
    """
    lid = lid_een(tekst)
    if lid is None:
        return None
    uit = []
    for r in lid:
        m = re.match(r"^[a-z]{1,2}\.\s*(.*)$", r)
        if not m:
            continue
        x = m.group(1)
        if re.search(r"ter plaats", x, re.I):
            continue
        x = re.split(r",?\s*met dien verstande", x)[0]
        if x.lower().startswith(BIJZAAK):
            continue
        for f in functies_in(x):
            if f not in uit:
                uit.append(f)
    return uit


# HUIDIG GEBRUIK UIT DE BAG, naar dezelfde woorden. Alleen de doelen die
# eenduidig zijn; een bijeenkomstfunctie kan horeca, cultuur of
# maatschappelijk zijn en blijft daarom zonder vertaling.
BAG_NAAR_FUNCTIE = {"woonfunctie": "wonen", "winkelfunctie": "detailhandel",
                    "kantoorfunctie": "kantoren", "logiesfunctie": "hotel",
                    "industriefunctie": "bedrijven"}


def functieruimte(rec, artikelen, bag_doelen=()):
    """
    Wat het plan op dit pand toestaat, naast wat er nu is.

    Geeft None als marktdata het pand nog niet heeft opgehaald of het
    artikel van de bestemming niet heeft; anders een dict met
    bestemming, artikel, hoofdfuncties, aanduidingen [(naam, functies,
    bepaling)], toegestaan (alle functies), huidig (uit de BAG, vertaald
    waar eenduidig), extra (toegestaan min huidig) en hotel (letterlijk).

    WAAROM (28 november 2026). Mark: een pand dat te koop staat en meer
    functies kan hebben, hoort zichtbaar te zijn, ook als het niet in een
    verhuur- of splitsingsscenario past. Dit kijkt vanuit het plan in
    plaats van vanuit de verhuursom.
    """
    if not rec or "verwijzingen" not in rec:
        return None
    eb = ((rec.get("verwijzingen") or {}).get("enkelbestemming") or [])
    tekst = titel = None
    for v in eb:
        titel, tekst = tekst_voor(v.get("tekst") or "", artikelen)
        if tekst:
            naam = v.get("naam") or ""
            break
    if not tekst:
        return None
    hf = hoofdfuncties(tekst) or []
    aand = []
    for n, _titel, bep in bepaling_aanduiding(rec, artikelen):
        aand.append((n, functies_in(bep["tekst"]) if bep else [],
                     bep["tekst"].rstrip(" ;") if bep else None))
    toegestaan = list(hf)
    for _n, fs, _b in aand:
        for f in fs:
            if f not in toegestaan:
                toegestaan.append(f)
    huidig = []
    for d in bag_doelen or ():
        f = BAG_NAAR_FUNCTIE.get(d)
        if f and f not in huidig:
            huidig.append(f)
    extra = [f for f in toegestaan if f not in huidig]
    return {"bestemming": naam, "artikel": titel,
            "hoofdfuncties": hf, "aanduidingen": aand,
            "toegestaan": toegestaan, "huidig": huidig,
            "huidig_bag": list(bag_doelen or ()), "extra": extra,
            "hotel": any("hotel" in fs for _n, fs, _b in aand)
            or "hotel" in hf}


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


def hotel(bestemmingen_pad=BESTEMMINGEN, uit_pad=UIT_PAD):
    """
    Panden waar de bepaling van een functieaanduiding letterlijk 'hotel',
    'pension' of 'logies' noemt. Letterlijk, omdat een horecacategorie per
    plan anders kan zijn ingevuld; die afleiding hoort niet in deze lijst.
    """
    with open(bestemmingen_pad, encoding="utf-8") as f:
        panden = json.load(f).get("panden") or {}
    artikelen = lees(uit_pad).get("artikelen") or {}
    rijen = []
    for p, rec in panden.items():
        for naam, titel, bep in bepaling_aanduiding(rec, artikelen):
            if bep and re.search(r"hotel|pension|logies", bep["tekst"], re.I):
                rijen.append((rec.get("adres") or p, naam, titel,
                              bep["tekst"].rstrip(" ;")))
    for r in sorted(rijen):
        print("\t".join(r))
    met = sum(1 for r in panden.values() if "verwijzingen" in r)
    print(f"{len(rijen)} panden, van {met} met verwijzingen (de rest is nog "
          f"niet opgehaald)", file=sys.stderr)
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

    # BEPALINGEN, op regels uit de echte artikelen van 28 november.
    echt = "\n".join([
        "Artikel 10 Gemengd - 3",
        "f. ter plaatse van de aanduiding 'horeca' tevens voor horecabedrijven "
        "voor zover deze voorkomen in categorie 1a, 1b of 2 van de Staat van "
        "horeca-activiteiten;",
        "h. ter plaatse van de aanduiding 'horeca van horecacategorie 1a' "
        "tevens voor horecabedrijven in categorie 1a;",
        "k. ter plaatse van de aanduiding 'specifieke vorm van "
        "dienstverlening-50%' is tevens dienstverlening toegestaan tot "
        "maximaal 50%;",
        "l. ter plaatse van de aanduiding 'specifieke vorm van horeca-2' "
        "tevens voor een hotel;",
        "b. ter plaatse van de aanduiding \"b\" tevens voor bedrijven zoals "
        "opgenomen in milieucategorie 1;",
        "b. ter plaatse van de aanduiding 'specfieke vorm van gemengd 1\" "
        "tevens voor horeca in categorie 1A, 1B en 2A;"])
    bp = bepalingen(echt)
    for pdok, lid in (("horeca", "f"), ("horeca van categorie .1a", "h"),
                      ("specifieke vorm van dienstverlening - .50%", "k"),
                      ("specifieke vorm van horeca - .2", "l"),
                      ("bedrijf", "b"),
                      ("specifieke vorm van gemengd - 1", "b")):
        if (bp.get(gelijk(pdok)) or {}).get("lid") != lid:
            afw.append(f"de PDOK-naam '{pdok}' vindt lid {lid} niet: "
                       f"{sorted(bp)}")
    if tekst_uit("<h1>Nijmegen Centrum - Binnenstad</h1><p>Artikel 10 "
                 "Gemengd - 3</p>")[0] != "Artikel 10 Gemengd - 3":
        afw.append("de titel is niet de artikelnaam")
    arts = {BRON + "a.html": {"titel": "Nijmegen Centrum - Binnenstad",
                              "tekst": echt}}
    rec = {"functieaanduiding": ["specifieke vorm van horeca - .2",
                                 "praktijkruimte"],
           "verwijzingen": {"enkelbestemming": [
               {"naam": "Gemengd - 3", "tekst": BRON + "a.html"}]}}
    ba = bepaling_aanduiding(rec, arts)
    if ba[0][2] is None or "hotel" not in ba[0][2]["tekst"]:
        afw.append(f"de bepaling voor horeca-2 wordt niet gevonden: {ba}")
    if ba[1][1] != "Artikel 10 Gemengd - 3" or ba[1][2] is not None:
        afw.append(f"een aanduiding die niet in het artikel staat: {ba[1]}")
    if bepaling_aanduiding(rec, {})[0][1] is not None:
        afw.append("een niet opgehaald artikel krijgt toch een titel")

    # FUNCTIERUIMTE, op lid 1 van echte artikelen (28 november).
    g3 = "\n".join([
        "direct naar inhoud van Artikel 10 Gemengd - 3",
        "Artikel 1 Begrippen",
        "10.1 Bestemmingsomschrijving",
        "10.1 Bestemmingsomschrijving",
        "De voor 'Gemengd - 3' aangewezen gronden zijn bestemd voor:",
        "a. cultuur en ontspanning, detailhandel en wonen, met dien verstande "
        "dat nieuwe geluidsgevoelige functies alleen zijn toegestaan;",
        "b. bedrijven voor zover deze voorkomen in categorie 1 of 2;",
        "l. ter plaatse van de aanduiding 'specifieke vorm van horeca-2' "
        "tevens voor een hotel;",
        "q. ondersteunende horeca zoals bedoeld in artikel 32.4;",
        "r. bijbehorende voorzieningen zoals verhardingen, parkeer- en "
        "groenvoorzieningen;",
        "10.2 Bouwregels",
        "a. hoofdgebouwen mogen uitsluitend worden opgericht binnen het "
        "bouwvlak, ook voor kantoren;"])
    if artikel_uit_tekst(g3) != "Artikel 10 Gemengd - 3":
        afw.append(f"artikelnaam uit het menu: {artikel_uit_tekst(g3)}")
    if hoofdfuncties(g3) != ["wonen", "detailhandel", "cultuur en ontspanning",
                             "bedrijven"]:
        afw.append(f"hoofdfuncties Gemengd - 3: {hoofdfuncties(g3)}")
    wonen = ("19.1 Bestemmingsomschrijving\nDe voor 'Wonen' aangewezen gronden "
             "zijn bestemd voor:\na. wonen;\nb. aan huis verbonden beroeps- "
             "en bedrijfsactiviteiten;\nc. bijbehorende voorzieningen;\n"
             "19.2 Bouwregels")
    if hoofdfuncties(wonen) != ["wonen"]:
        afw.append(f"bijzaken tellen als functie bij Wonen: "
                   f"{hoofdfuncties(wonen)}")
    if functies_in("tevens voor horecabedrijven in categorie 1a") != ["horeca"]:
        afw.append(f"horecabedrijven telt als bedrijven: "
                   f"{functies_in('tevens voor horecabedrijven in categorie 1a')}")
    if hoofdfuncties("geen lid een") is not None:
        afw.append("een artikel zonder lid 1 geeft toch functies")
    _a = {BRON + "g3.html": {"titel": "x", "tekst": g3}}
    _r = {"functieaanduiding": ["specifieke vorm van horeca - .2"],
          "verwijzingen": {"enkelbestemming": [
              {"naam": "Gemengd - 3", "tekst": BRON + "g3.html"}]}}
    fr = functieruimte(_r, _a, ["woonfunctie", "bijeenkomstfunctie"])
    if not fr or fr["extra"] != ["detailhandel", "cultuur en ontspanning",
                                 "bedrijven", "hotel"] or not fr["hotel"] \
            or fr["huidig"] != ["wonen"]:
        afw.append(f"functieruimte: {fr}")
    if functieruimte({"enkelbestemming": ["Wonen"]}, _a) is not None:
        afw.append("een niet opgehaald pand krijgt toch een functieruimte")

    # EEN PAGINA MET ALLE REGELS: het #-deel kiest het artikel.
    heel = "\n".join([
        "Artikel 3 Bedrijf", "Artikel 15 Wonen",  # inhoudsopgave
        "Artikel 3 Bedrijf", "3.1 bestemmingsomschrijving",
        "De voor 'Bedrijf' aangewezen gronden zijn bestemd voor:",
        "a. bedrijven voor zover deze zijn opgenomen in de Staat;",
        "3.2 bouwregels",
        "Artikel 15 Wonen", "15.1 bestemmingsomschrijving",
        "De voor 'Wonen' aangewezen gronden zijn bestemd voor:",
        "a. wonen;", "b. ter plaatse van de aanduiding 'praktijkruimte' "
        "tevens voor kantoren;", "15.2 bouwregels",
        "Artikel 16 Waarde - Archeologie"])
    _h = {BRON + "h.html": {"titel": "Oud West", "tekst": heel}}
    _hr = {"functieaanduiding": ["praktijkruimte"], "verwijzingen": {
        "enkelbestemming": [{"naam": "Wonen",
                             "tekst": BRON + "h.html#_15_Wonen"}]}}
    fh = functieruimte(_hr, _h, [])
    if not fh or fh["hoofdfuncties"] != ["wonen"] or \
            fh["artikel"] != "Artikel 15 Wonen":
        afw.append(f"op een pagina met alle regels wordt het verkeerde "
                   f"artikel gelezen: {fh}")
    if bepaling_aanduiding(_hr, _h)[0][2] is None:
        afw.append("de aanduiding in een artikel op een pagina met alle "
                   "regels wordt niet gevonden")
    if tekst_voor(BRON + "h.html#_99_Niets", _h)[1] is not None:
        afw.append("een artikel dat niet op de pagina staat, telt als "
                   "gevonden")

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
    ap.add_argument("--hotel", action="store_true",
                    help="panden waar een bepaling letterlijk hotel, "
                         "pension of logies noemt")
    a = ap.parse_args()
    if a.proef:
        return proef()
    if a.hotel:
        return hotel()
    return ophalen(a.minuten)


if __name__ == "__main__":
    sys.exit(main())
