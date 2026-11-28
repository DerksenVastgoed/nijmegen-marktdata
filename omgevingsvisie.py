#!/usr/bin/env python3
"""
De Omgevingsvisie gemeente Nijmegen per stadsdeel, en welke ringbuurt bij
welk stadsdeel hoort, uit de tekst van de visie zelf.

WAAROM (28 november 2026). De visie (gemeenteblad 2025 nr. 401292,
CVDR744138) bindt niet op pandniveau, maar zegt per stadsdeel wat de gemeente
wil: bij Nijmegen-Oost "de balans tussen groei van het aantal inwoners en
leefbaarheid, vooral in de wijken rond het centrum", bij Oud-West minder
ruimte voor inbreiding. Haar werkingsgebieden (GIO's) bleken de stadsdelen
te zijn (dc-2025-14234 "Stadsdeel Nijmegen-Centrum", dc-2025-14235 "Stadsdeel
Nijmegen-Zuid"), en die waren vanaf GitHub niet op te halen: op 28 november
gaf identifier.officielebekendmakingen.nl 403 op elke JOIN-identificatie
(zie stadsbeeld.verken_regeling). Maar de tekst van paragraaf 6.4 tot en met
6.12 noemt per stadsdeel zijn wijken en buurten, en die tekst is wel te
halen. Een kaart is dus niet nodig: het stadsdeel van een buurt volgt uit
waar de visie de buurt noemt.

WAAR DE KOPPELING OP RUST. Elke stadsdeelparagraaf heeft een subparagraaf
"6.N.2 ... - Kwaliteiten en kenmerken" die opsomt welke wijken erbij horen:
"Nijmegen-Oost ... bestaat uit de wijken Bottendaal, Galgenveld, Altrade,
Hunnerberg, Hengstdal, Kwakkenberg en Groenewoud." Een buurt hoort bij een
stadsdeel als precies één zo'n opsommingszin haar noemt. Staat ze in geen of
in meer dan één opsommingszin, dan blijft ze zonder stadsdeel, en staat in
het verslag waarom. Losse vermeldingen tellen niet.

DE EERSTE VERSIE MAT EEN VERZONNEN TEKST (28 november 2026). Die zocht koppen
als "6.4 Nijmegen-Centrum" op een regel en telde elke vermelding van een
buurt. De proef draaide op een tekst die ik zelf had geschreven en was groen;
de eerste echte ronde vond in 330.848 tekens geen enkele paragraaf. Gemeten
op de pagina zelf: de koppen staan in hoofdletters en de pagina zet nummer
en naam in twee <span>s, dus "6.4" en "NIJMEGEN-CENTRUM" op twee regels.
En tellen was fout geweest: "Benedenstad" staat er alleen als "benedenstad",
"Stadscentrum" nergens met hoofdletter, "binnenstad" ook in 6.9 Dukenburg
("bezoekers aan de binnenstad"), en "De Biezen" ook in 6.6 Nieuw-West, waar
het om rioolgemaal De Biezen in het Westerpark gaat. De opsommingszin noemt
alle acht ringbuurten precies één keer. De proef gebruikt nu de opmaak en de
zinnen van de pagina, letterlijk.

  python3 omgevingsvisie.py            # ophalen en vastleggen
  python3 omgevingsvisie.py --proef
"""
import argparse
import datetime as dt
import json
import re
import sys
import urllib.request

import planregels
import ring

REGELING = "https://lokaleregelgeving.overheid.nl/CVDR744138"
UIT_PAD = "omgevingsvisie.json"
VERSLAG = "omgevingsvisie_verslag.md"
# De koppen van hoofdstuk 6 zoals de pagina ze geeft (gemeten 28 november):
# "6.4 NIJMEGEN-CENTRUM" tot en met "6.12 NIJMEGEN-OOST", in hoofdletters.
# Nummer en naam staan op twee regels; _regels voegt ze samen.
_KOP = re.compile(r"^6\.(\d{1,2})\s+(nijmegen-[a-z-]+|dukenburg|lindenholt)"
                  r"\s*$", re.I)
_NUMMER = re.compile(r"^\d+(\.\d+)*$")
# De zin die de wijken van een stadsdeel opsomt. Gemeten 28 november:
# "bestaat uit de wijken", "bestaat officieel uit de wijken", "bestaat uit
# twee woonwijken". Nieuw-West ("In Nieuw West liggen de woonwijken"), Noord
# en Dukenburg hebben geen zin met "bestaat uit"; geen ringbuurt ligt daar.
_WIJKZIN = re.compile(r"bestaat (?:officieel )?uit (?:de |twee )?(?:woon)?wijken",
                      re.I)
# Andere spelling waarmee de visie een ringbuurt kan noemen, alleen wat
# gemeten is.
SYNONIEMEN = {"St. Anna": ("St. Anna", "Sint Anna")}
# Zinnen met deze woorden komen letterlijk in het dossier: wat de gemeente
# wil met bouwen, functies en ruimte.
KERNWOORDEN = ("verdicht", "inbreiding", "intensiver", "transformatie",
               "hoogbouw", "woningbouw", "functiemenging", "horeca",
               "kantoren", "studenten", "kamer", "leefbaarheid")


def _regels(tekst):
    """Regels, met een los nummer ("6.4") samengevoegd met de regel erna."""
    uit, wacht = [], None
    for r in (tekst or "").splitlines():
        r = r.strip()
        if not r:
            continue
        if wacht is not None:
            r, wacht = f"{wacht} {r}", None
        elif _NUMMER.match(r):
            wacht = r
            continue
        uit.append(r)
    if wacht is not None:
        uit.append(wacht)
    return uit


def _naam(kop):
    """'NIJMEGEN-OUD-WEST' wordt 'Nijmegen-Oud-West'."""
    return "-".join(d.capitalize() for d in kop.split("-"))


# Zinnen splitsen, maar niet na "St." ("Goffert en St. Anna."): zonder deze
# uitzondering viel St. Anna op 28 november uit de opsomming van Midden.
_ZINSEINDE = re.compile(r"(?<=[.!?])(?<!\bSt\.)\s+")


# Een kopregel na _regels: "6.12.4 Oost - Prioriteiten".
_KOPREGEL = re.compile(r"^\d+(?:\.\d+)+\s+\S")


def zinnen(tekst):
    """Zinnen per regel. Over regels heen plakken liet de opsommingszin op
    28 november beginnen met de kop: "6.4.2 Centrum - Kwaliteiten en
    kenmerken Nijmegen-Centrum bestaat ..."."""
    uit = []
    for r in (tekst or "").splitlines():
        uit.extend(z for z in _ZINSEINDE.split(" ".join(r.split())) if z)
    return uit


# Zinnen over meer bewoners of woningen in de bestaande bebouwing.
_INTENSIVERING = re.compile(r"inbreiding|intensiver|splits|verkamer", re.I)


def prioriteiten(deel):
    """De lijst onder "6.N.4 ... - Prioriteiten", letterlijk, een per punt."""
    regels = [" ".join(r.split()) for r in (deel or "").splitlines()]
    uit, bezig = [], False
    for r in regels:
        if re.match(r"^6\.\d+\.4\s+.*Prioriteiten$", r, re.I):
            bezig = True
            continue
        if bezig:
            if _KOPREGEL.match(r):
                break
            if r:
                uit.append(r)
    return uit


def _genoemd(zin, buurten=None):
    buurten = buurten if buurten is not None else ring.BUURTEN
    return [b for b in buurten
            if any(re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", zin, re.I)
                   for n in SYNONIEMEN.get(b, (b,)))]


def intensivering(deel):
    """[{"zin", "buurten"}]: wat de paragraaf zegt over inbreiding,
    intensivering, splitsen of verkameren, letterlijk, met de ringbuurten die
    de zin zelf noemt."""
    # Een tussenkop ("Leefbaarheid, cultuurhistorie en inbreiding", 6.12.3.3)
    # eindigt niet op een leesteken; een punt uit de prioriteitenlijst soms
    # ook niet, en telt wel.
    lijst = set(prioriteiten(deel))
    return [{"zin": z, "buurten": _genoemd(z)} for z in zinnen(deel)
            if _INTENSIVERING.search(z) and len(z) < 500
            and (z[-1] in ".!?:;" or z in lijst)]


def buurtzinnen(deel):
    """[{"zin", "buurten"}]: elke zin die een ringbuurt bij naam noemt,
    behalve de opsommingszin. Zo komt "In sommige gebieden van Bottendaal,
    Galgenveld en Altrade is de leefbaarheid een aandachtspunt." (6.12.3.3)
    mee, die geen woord over intensivering bevat."""
    wz = wijkzin(deel)
    return [{"zin": z, "buurten": b} for z in zinnen(deel)
            for b in [_genoemd(z)] if b and z != wz and z[-1] in ".!?:;"]


def labeldoel(tekst):
    """[{"paragraaf", "zin"}]: zinnen over een energielabel met een jaartal,
    uit de hele visie, met de paragraaf waarin ze staan."""
    uit, kop = [], ""
    for r in _regels(tekst):
        m = re.match(r"^(\d+(?:\.\d+)+)\s+\S", r)
        if m:
            kop = m.group(1)
            continue
        for z in _ZINSEINDE.split(r):
            if re.search(r"energielabel|label [A-G]\b", z) and \
                    re.search(r"\b20[3-5]\d\b", z):
                uit.append({"paragraaf": kop, "zin": z})
    return uit


def wijkzin(deel):
    """De zin die de wijken van het stadsdeel opsomt, of ''."""
    for z in zinnen(deel):
        if _WIJKZIN.search(z):
            return z
    return ""


def stadsdelen(tekst):
    """
    {stadsdeel: {"paragraaf": "6.12", "tekst": ..., "wijkzin": ...}} uit de
    tekst van de visie. Komt een kop twee keer voor (inhoudsopgave en
    tekst), dan telt de langste paragraaf.
    """
    regels = _regels(tekst)
    koppen = [(i, m.group(1), _naam(m.group(2))) for i, r in enumerate(regels)
              for m in [_KOP.match(r)] if m]
    uit = {}
    for n, (i, nr, naam) in enumerate(koppen):
        eind = len(regels)
        for j in range(i + 1, len(regels)):
            r = regels[j].strip()
            if _KOP.match(r) or re.match(r"^(7|8|9)(\.\d+)*\s+\S", r) or \
                    re.match(r"^Hoofdstuk \d", r):
                eind = j
                break
        deel = "\n".join(regels[i + 1:eind]).strip()
        if len(deel) > len((uit.get(naam) or {}).get("tekst", "")):
            uit[naam] = {"paragraaf": f"6.{nr}", "tekst": deel,
                         "wijkzin": wijkzin(deel),
                         "prioriteiten": prioriteiten(deel),
                         "intensivering": intensivering(deel),
                         "buurtzinnen": buurtzinnen(deel)}
    return uit


def buurt_naar_stadsdeel(delen, buurten=ring.BUURTEN):
    """
    ({buurt: stadsdeel}, {buurt: reden zonder stadsdeel}). Een buurt hoort
    bij het enige stadsdeel waarvan de opsommingszin haar (of een andere
    spelling) noemt, ongeacht hoofdletters: de visie schrijft "stadscentrum
    en benedenstad".
    """
    koppel, zonder = {}, {}
    for b in buurten:
        namen = SYNONIEMEN.get(b, (b,))
        treffers = [sd for sd, d in delen.items()
                    if any(re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])",
                                     d.get("wijkzin") or "", re.I)
                           for n in namen)]
        if len(treffers) == 1:
            koppel[b] = treffers[0]
        elif not treffers:
            zonder[b] = "staat in geen opsomming van wijken van een stadsdeel"
        else:
            zonder[b] = "genoemd in " + ", ".join(sorted(treffers))
    return koppel, zonder


def kernzinnen(tekst, maximum=8):
    """Zinnen met een kernwoord, letterlijk, in volgorde."""
    uit = [z for z in zinnen(tekst)
           if any(k in z.lower() for k in KERNWOORDEN) and 20 < len(z) < 400]
    return uit[:maximum]


def _haal(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "NijmegenVastgoedMonitor/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def ophalen(haal=None, uit_pad=UIT_PAD, verslag_pad=VERSLAG):
    haal = haal or _haal
    r = ["# Omgevingsvisie per stadsdeel", "", f"Regeling: `{REGELING}`", ""]
    try:
        _titel, tekst = planregels.tekst_uit(haal(REGELING))
    except Exception as e:
        # Niet opgehaald is geen lege visie: het vorige bestand blijft staan.
        r.append(f"- niet opgehaald: {type(e).__name__} {e}; {uit_pad} is "
                 f"niet overschreven")
        with open(verslag_pad, "w", encoding="utf-8") as f:
            f.write("\n".join(r) + "\n")
        print("\n".join(r))
        return 0
    delen = stadsdelen(tekst)
    if not delen:
        r.append(f"- geen enkele stadsdeelparagraaf gevonden in {len(tekst)} "
                 f"tekens; {uit_pad} is niet overschreven")
        zes = [x for x in _regels(tekst) if x.startswith("6.")][:12]
        r.append("- regels die met 6. beginnen: " +
                 ("; ".join(f"`{x[:60]}`" for x in zes) if zes else "geen"))
        with open(verslag_pad, "w", encoding="utf-8") as f:
            f.write("\n".join(r) + "\n")
        print("\n".join(r))
        return 0
    koppel, zonder = buurt_naar_stadsdeel(delen)
    uit = {"regeling": REGELING, "bijgewerkt": dt.date.today().isoformat(),
           "stadsdelen": {sd: dict(d, kern=kernzinnen(d["tekst"]))
                          for sd, d in delen.items()},
           "buurten": koppel, "buurten_zonder_stadsdeel": zonder,
           "labeldoel": labeldoel(tekst)}
    with open(uit_pad, "w", encoding="utf-8") as f:
        json.dump(uit, f, ensure_ascii=False, indent=1)
    r.append(f"- {len(tekst)} tekens, {len(delen)} stadsdeelparagrafen")
    for sd, d in sorted(delen.items(), key=lambda x: float(x[1]["paragraaf"]
                                                            .split(".")[1])):
        r.append(f"  - {d['paragraaf']} {sd}: {len(d['tekst'])} tekens, "
                 f"{len(kernzinnen(d['tekst']))} kernzinnen; opsomming: "
                 + (f"\u201c{d['wijkzin']}\u201d" if d["wijkzin"]
                    else "geen zin met 'bestaat uit ... wijken'"))
        r.append(f"    - prioriteiten: {len(d['prioriteiten'])}; zinnen over "
                 f"inbreiding, intensivering of splitsen: "
                 f"{len(d['intensivering'])}")
        for i in d["intensivering"]:
            r.append(f"      - {', '.join(i['buurten']) or 'stadsdeel'}: "
                     f"\u201c{i['zin']}\u201d")
        for i in d["buurtzinnen"]:
            r.append(f"    - noemt {', '.join(i['buurten'])}: "
                     f"\u201c{i['zin']}\u201d")
    r.append("")
    ld = uit["labeldoel"]
    r.append("## Labeldoel")
    r.append("")
    r.extend([f"- {x['paragraaf']}: \u201c{x['zin']}\u201d" for x in ld]
             or ["- geen zin over een energielabel met een jaartal gevonden"])
    r.append("")
    r.append("## Ringbuurten")
    r.append("")
    for b in ring.BUURTEN:
        r.append(f"- {b}: " + (koppel[b] if b in koppel
                               else f"geen stadsdeel ({zonder[b]})"))
    with open(verslag_pad, "w", encoding="utf-8") as f:
        f.write("\n".join(r) + "\n")
    print("\n".join(r))
    return 0


def lees(pad=UIT_PAD):
    try:
        with open(pad, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def dossierregels(buurt, pad=UIT_PAD):
    """
    [(onderwerp, tekst, bron)] voor het dossier van een pand in deze buurt:
    het stadsdeel met paragraaf en de kernzinnen, letterlijk. Leeg als de
    visie nog niet is opgehaald; een buurt zonder stadsdeel zegt waarom.
    """
    v = lees(pad)
    if not v.get("stadsdelen"):
        return []
    bron = "Omgevingsvisie gemeente Nijmegen (CVDR744138)"
    sd = (v.get("buurten") or {}).get(buurt)
    if not sd:
        reden = (v.get("buurten_zonder_stadsdeel") or {}).get(
            buurt, "buurt buiten de ring")
        return [("omgevingsvisie", f"geen stadsdeel toe te wijzen: {reden}",
                 bron)]
    d = v["stadsdelen"].get(sd) or {}
    kern = " ".join(f"\u201c{z}\u201d" for z in (d.get("kern") or [])[:4])
    return [("omgevingsvisie",
             f"{sd} (paragraaf {d.get('paragraaf')}; de visie noemt {buurt} "
             f"in de opsomming \u201c{d.get('wijkzin', '')}\u201d)"
             + (f": {kern}" if kern else ""),
             bron)]


def _kop(tag, nr, naam):
    """Een kop zoals lokaleregelgeving.overheid.nl hem opmaakt (28 nov)."""
    return (f'<{tag} class="docDivisie"><a id="div_{nr}"></a>\n'
            f'                           \t\t<span>{nr} </span>\n'
            f'                           \t\t<span>{naam}</span>\n'
            f'                           \t      </{tag}>')


def _lijst(*punten):
    return "<ul>" + "".join(f'<li><a id="i"></a> <p>{p}</p> </li>'
                            for p in punten) + "</ul>"


# Zinnen letterlijk uit de visie van 28 november, in de opmaak van de pagina.
PROEF_HTML = "".join([
    _kop("h5", "4.6.4.2", "Hoe gaan we dit doel bereiken?"),
    "<p> <strong>Gebouwde omgeving</strong> </p> <p>Dit doen we op de eerste "
    "plaats door woningen te isoleren op basis van het programma Energie "
    "Besparen Woningen 2023-2030. Doel van dit programma is om in 2030 geen "
    "woningen meer te hebben met een energielabel E, F of G en het aantal "
    "woningen met label D met de helft te verlagen. In het programma is het "
    "einddoel dat in 2045 alle woningen in Nijmegen minimaal label B "
    "hebben.&nbsp;</p>",
    _kop("h3", "6.4", "NIJMEGEN-CENTRUM"),
    _kop("h4", "6.4.2", "Centrum - Kwaliteiten en kenmerken"),
    "<p>Nijmegen-Centrum bestaat officieel uit de wijken stadscentrum en "
    "benedenstad. Beleidsmatig spreken we ook vaak van de binnenstad en het "
    "Stationsdistrict.</p>",
    _kop("h3", "6.6", "NIJMEGEN-NIEUW-WEST"),
    _kop("h4", "6.6.2", "Nieuw-West - Kwaliteiten en kenmerken"),
    "<p>In Nieuw West liggen de woonwijken Neerbosch Oost, Heseveld en Hees "
    "en een groot deel van het bedrijventerrein TPN West aan de haven en de "
    "Waal.</p><p>Grote delen van Nijmegen en omgeving voeren af naar "
    "rioolgemaal De Biezen in het Westerpark, vandaaruit gaat het water naar "
    "de rioolwaterzuivering.</p>",
    _kop("h3", "6.7", "NIJMEGEN-OUD-WEST"),
    _kop("h4", "6.7.2", "Oud-West - Kwaliteiten en kenmerken"),
    "<p>Nijmegen-Oud-West bestaat uit twee woonwijken, Wolfskuil en "
    "Waterkwartier, ook wel De Biezen genoemd. Afgelopen jaren zijn in het "
    "Waalfront bedrijven vervangen door woningbouw met hoog- en laagbouw in "
    "retro- en moderne stijl.</p>",
    _kop("h4", "6.7.4", "Oud-West - Prioriteiten"),
    _lijst("Meer groene beweegroutes en sociale knooppunten (BOSS).",
           "Behoud diversiteit voorzieningen.",
           "Meer groen en leefbaarheid krijgen in dit stadsdeel prioriteit "
           "boven inbreiding en intensivering van bewoning."),
    _kop("h3", "6.8", "NIJMEGEN-MIDDEN"),
    _kop("h4", "6.8.2", "Midden - Kwaliteiten en kenmerken"),
    "<p>Nijmegen-Midden bestaat uit de wijken: Nije Veld, Heijendaal, "
    "Hazenkamp, Goffert en St. Anna.</p>",
    _kop("h3", "6.9", "DUKENBURG"),
    "<p>Bij de A73 is een zoekgebied voor een transferium waar bezoekers aan "
    "de binnenstad hun reis met het ov kunnen vervolgen, waardoor er minder "
    "autoverkeer door de stad hoeft te gaan.</p>",
    _kop("h3", "6.12", "NIJMEGEN-OOST"),
    _kop("h4", "6.12.2", "Oost - Kwaliteiten en kenmerken"),
    "<p>Nijmegen-Oost is eind 19e eeuw, begin 20e eeuw ontstaan. Het "
    "stadsdeel bestaat uit de wijken Bottendaal, Galgenveld, Altrade, "
    "Hunnerberg, Hengstdal, Kwakkenberg en Groenewoud. Het is een populair "
    "stadsdeel om te wonen. Tegelijkertijd spelen er vraagstukken over "
    "leefbaarheid, klimaatadaptatie en vergroening en de "
    "energietransitie.</p>",
    _kop("h5", "6.12.3.3", "Oost - Aantrekkelijke stad"),
    "<p><strong>Leefbaarheid, cultuurhistorie en inbreiding</strong></p>"
    "<p>Over het algemeen is de leefbaarheid in Nijmegen-Oost goed en dat "
    "willen we zo houden. In sommige gebieden van Bottendaal, Galgenveld en "
    "Altrade is de leefbaarheid een aandachtspunt.</p><p>We zetten daarbij "
    "inbreiding en intensivering niet op slot.</p>",
    _kop("h4", "6.12.4", "Oost - Prioriteiten"),
    _lijst("Balans houden tussen groei van het aantal inwoners en "
           "leefbaarheid, met name in de wijken rondom het centrum",
           "Behoud van de cultuurhistorische waarden en karakteristieke "
           "wijken&nbsp;",
           "Verduurzamen van de woningvoorraad"),
    _kop("h4", "6.12.5", "Oost - Belangrijkste elementen op kaart"),
    "<figure> <figcaption>Deelgebiedskaart: Nijmegen-Oost</figcaption>"
    "<figcaption>Belangrijkste elementen op kaart<span "
    'class="figure__source">Studio D / gemeente Nijmegen</span></figcaption>'
    " </figure>",
    _kop("h2", "7", "STURINGSFILOSOFIE"),
    _kop("h3", "7.1", "INLEIDING"),
    "<p>Ook in Galgenveld en de benedenstad sturen we op doelen.</p>"])


def proef():
    import os
    import tempfile
    afw = []
    _t, tekst = planregels.tekst_uit(PROEF_HTML)
    d = stadsdelen(tekst)
    verwacht_sd = ["Dukenburg", "Nijmegen-Centrum", "Nijmegen-Midden",
                   "Nijmegen-Nieuw-West", "Nijmegen-Oost", "Nijmegen-Oud-West"]
    if sorted(d) != verwacht_sd:
        afw.append(f"stadsdelen uit de opmaak van de pagina: {sorted(d)}")
    if d.get("Nijmegen-Oost", {}).get("paragraaf") != "6.12" or \
            "sturen we" in d.get("Nijmegen-Oost", {}).get("tekst", ""):
        afw.append(f"de laatste paragraaf loopt door in hoofdstuk 7: "
                   f"{d.get('Nijmegen-Oost')}")
    if d.get("Dukenburg", {}).get("wijkzin") or \
            d.get("Nijmegen-Nieuw-West", {}).get("wijkzin"):
        afw.append("een paragraaf zonder 'bestaat uit' krijgt toch een "
                   "opsomming")
    wz = d.get("Nijmegen-Centrum", {}).get("wijkzin", "")
    if not wz.startswith("Nijmegen-Centrum bestaat officieel"):
        afw.append(f"de opsommingszin begint niet bij de zin zelf: {wz}")
    po = d.get("Nijmegen-Oost", {}).get("prioriteiten")
    if po != ["Balans houden tussen groei van het aantal inwoners en "
              "leefbaarheid, met name in de wijken rondom het centrum",
              "Behoud van de cultuurhistorische waarden en karakteristieke "
              "wijken", "Verduurzamen van de woningvoorraad"]:
        afw.append(f"prioriteiten van Oost: {po}")
    iw = d.get("Nijmegen-Oud-West", {}).get("intensivering") or []
    if [i["zin"] for i in iw] != [
            "Meer groen en leefbaarheid krijgen in dit stadsdeel prioriteit "
            "boven inbreiding en intensivering van bewoning."]:
        afw.append(f"intensivering in Oud-West: {iw}")
    io = d.get("Nijmegen-Oost", {}).get("intensivering") or []
    if [i["zin"] for i in io] != [
            "We zetten daarbij inbreiding en intensivering niet op slot."]:
        afw.append(f"intensivering in Oost: {io}")
    bz = d.get("Nijmegen-Oost", {}).get("buurtzinnen") or []
    if [(b["zin"][:26], b["buurten"]) for b in bz] != [
            ("In sommige gebieden van Bo", ["Bottendaal", "Galgenveld",
                                            "Altrade"])]:
        afw.append(f"buurtzinnen van Oost (zonder de opsommingszin): {bz}")
    ld = labeldoel(tekst)
    if [x["paragraaf"] for x in ld] != ["4.6.4.2", "4.6.4.2"] or \
            "E, F of G" not in ld[0]["zin"]:
        afw.append(f"labeldoel: {ld}")
    k, z = buurt_naar_stadsdeel(d)
    verwacht = {"Stadscentrum": "Nijmegen-Centrum",
                "Benedenstad": "Nijmegen-Centrum",
                "Bottendaal": "Nijmegen-Oost", "Galgenveld": "Nijmegen-Oost",
                "Altrade": "Nijmegen-Oost", "Hunnerberg": "Nijmegen-Oost",
                "Biezen": "Nijmegen-Oud-West", "St. Anna": "Nijmegen-Midden"}
    if k != verwacht or z:
        afw.append(f"buurt naar stadsdeel: {k}, zonder: {z}")
    k2, z2 = buurt_naar_stadsdeel(
        {"A": {"wijkzin": "A bestaat uit de wijken Altrade en X."},
         "B": {"wijkzin": "B bestaat uit de wijken Altrade en Y."}},
        ("Altrade",))
    if k2 or "genoemd in A, B" not in z2.get("Altrade", ""):
        afw.append(f"een buurt in twee stadsdelen krijgt toch een stadsdeel: "
                   f"{k2}, {z2}")
    k3, z3 = buurt_naar_stadsdeel(
        {"A": {"tekst": "Altrade ligt hier.", "wijkzin": ""}}, ("Altrade",))
    if k3 or "geen opsomming" not in z3.get("Altrade", ""):
        afw.append(f"een losse vermelding buiten de opsomming koppelt toch: "
                   f"{k3}, {z3}")
    kz = kernzinnen(d.get("Nijmegen-Oost", {}).get("tekst", ""))
    if not kz or "leefbaarheid" not in kz[0]:
        afw.append(f"kernzinnen: {kz}")
    # Ophalen: mislukt laat het oude bestand staan.
    m = tempfile.mkdtemp()
    up, vp = os.path.join(m, "u.json"), os.path.join(m, "v.md")
    with open(up, "w", encoding="utf-8") as f:
        json.dump({"oud": True}, f)

    def mis(_u):
        raise OSError("403")
    stdout, sys.stdout = sys.stdout, open(os.devnull, "w")
    try:
        ophalen(mis, up, vp)
        if lees(up) != {"oud": True}:
            afw.append("een mislukte ophaling overschrijft het oude bestand")
        ophalen(lambda _u: "<p>geen visie</p>", up, vp)
        if lees(up) != {"oud": True}:
            afw.append("een pagina zonder stadsdelen overschrijft het oude "
                       "bestand")
        if "regels die met 6. beginnen: geen" not in open(
                vp, encoding="utf-8").read():
            afw.append("het verslag zegt niet wat er wel stond als er geen "
                       "stadsdeel gevonden is")
        ophalen(lambda _u: PROEF_HTML, up, vp)
    finally:
        sys.stdout.close()
        sys.stdout = stdout
    if lees(up).get("buurten", {}).get("Bottendaal") != "Nijmegen-Oost":
        afw.append(f"ophalen legt de koppeling niet vast: {lees(up)}")
    dr = dossierregels("Biezen", up)
    if not dr or "Nijmegen-Oud-West (paragraaf 6.7" not in dr[0][1] or \
            "ook wel De Biezen genoemd" not in dr[0][1]:
        afw.append(f"dossierregel zegt niet waarop de koppeling rust: {dr}")
    v = lees(up)
    v.setdefault("buurten", {}).pop("Altrade", None)
    v["buurten_zonder_stadsdeel"] = {
        "Altrade": "staat in geen opsomming van wijken van een stadsdeel"}
    with open(up, "w", encoding="utf-8") as f:
        json.dump(v, f)
    dz = dossierregels("Altrade", up)
    if not dz or "geen stadsdeel" not in dz[0][1] or \
            "opsomming" not in dz[0][1]:
        afw.append("een buurt zonder stadsdeel zegt niet waarom")
    if dossierregels("Biezen", os.path.join(m, "bestaat-niet.json")):
        afw.append("zonder opgehaalde visie komt er toch een dossierregel")
    for a in afw:
        print("AFWIJKING: " + a, file=sys.stderr)
    print(f"Proef omgevingsvisie: {len(afw)} afwijkingen", file=sys.stderr)
    return 1 if afw else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proef", action="store_true")
    a = ap.parse_args()
    if a.proef:
        return proef()
    return ophalen()


if __name__ == "__main__":
    sys.exit(main())
