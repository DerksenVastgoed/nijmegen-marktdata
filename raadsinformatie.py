#!/usr/bin/env python3
"""
Wat er in de gemeenteraad van Nijmegen speelt over wonen en vastgoed.

WAAROM DIT BESTAAT. De bekendmakingen laten een besluit zien als het genomen
is. In de raad is het dan al maanden een onderwerp: een motie, schriftelijke
vragen, een voorstel op de termijnagenda. Op 25 september 2026 misten we een
aangekondigde wijziging van het omgevingsplan over short stay, omdat we geen
raadsstukken volgden (VERBETERLIJST 7aa en de feed "Short stay"). Een
koppeling op het raadsinformatiesysteem werd toen niet gebouwd, omdat er geen
ingang was die te testen was.

DE INGANG. Nijmegen publiceert via iBabs op nijmegen.bestuurlijkeinformatie.nl.
De lijsten op dat portaal (moties, termijnagenda, schriftelijke vragen) laden
hun rijen met een POST naar /Reports/GetReportData/<lijst-id>, in de vorm van
DataTables: draw, start, length. Gemeten op 24 november 2026, vanuit een
browser zonder cookies:
  - het antwoord is JSON met recordsTotal en data;
  - length is aan de serverkant begrensd op 100, dus we bladeren met start;
  - start=0 en start=100 overlappen niet;
  - elke rij heeft een DT_RowId, en /Reports/Item/<DT_RowId> is de pagina van
    dat stuk, met bijlagen en de stemming.
robots.txt staat alles toe met "Crawl-delay: 5", dus we wachten vijf seconden
tussen twee verzoeken. Een volledige ronde over zes lijsten is daarmee ruim
vijf minuten; dat mag, want het is een keer per dag in een openbare repo.

WAT HIJ MAAKT.
  raadsinformatie_stand.json      per lijst: welke stukken we al zagen, wanneer
                                  we keken, en of dat lukte
  raadsinformatie_meldingen.json  nieuwe stukken over wonen en vastgoed, met
                                  datum; de brief zet ze een keer in de brief
                                  (meldingen.py daar)

ALLES OPHALEN, NIET ALLEEN DE BOVENSTE PAGINA. De termijnagenda staat
gesorteerd op raadsdatum (2029 bovenaan), niet op wanneer een punt erbij kwam.
Een nieuw punt kan dus overal staan. We halen elke lijst helemaal op en
vergelijken op DT_RowId; dat hangt niet af van een volgorde die we niet in de
hand hebben.

DE EERSTE KEER IS EEN NULMETING. Een lijst die nog niet in de stand staat,
wordt helemaal als gezien genoteerd zonder melding. Anders staan er op dag een
1.625 moties in de brief.

NIET GEKEKEN IS GEEN NIETS. Lukt het ophalen van een lijst niet, dan blijft
wat we al zagen staan, komt de reden onder "fout" in de stand en in
diagnose/raadsinformatie.txt, en eindigt het script met een foutcode. Een
lijst die niet gelezen kon worden, telt nooit als "geen nieuwe stukken".

DE VOLLEDIGE TEKST. Sinds 24 november 2026 zoekt hij daarnaast met de
zoekfunctie van het portaal in de volledige tekst van alle documenten
(raadsvoorstellen, woordelijke verslagen, raadsbrieven, bijlagen), op een
korte lijst termen. Zie ZOEKTERMEN en verwerk_zoeken() verderop.

WAT ER NIET IN ZIT. Verschuivingen op de termijnagenda en de stemming bij een
motie. Een woord buiten ZOEKTERMEN in een document dat geen lijststuk is.

Gebruik:
  python raadsinformatie.py            # een ronde
  python raadsinformatie.py --proef    # zonder netwerk nameten
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import time

try:
    from diagnose import leg_vast, wis
except Exception:  # noqa
    def leg_vast(*_a):
        pass

    def wis(*_a):
        pass

BASIS = "https://nijmegen.bestuurlijkeinformatie.nl"
STAND_PAD = "raadsinformatie_stand.json"
MELDINGEN_PAD = "raadsinformatie_meldingen.json"
PAUZE = 5          # robots.txt: Crawl-delay: 5
PAGINA = 100       # de server geeft er nooit meer dan 100 per keer
HEADERS = {"User-Agent": "NijmegenVastgoedMonitor/1.0",
           "X-Requested-With": "XMLHttpRequest",
           "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}

# naam: (lijst-id op het portaal, hoe het in de brief heet)
# De id's komen van /Reports op het portaal, gelezen op 24 november 2026.
LIJSTEN = {
    "termijnagenda": ("7be7b3a0-bec8-4c43-88d5-f71fda79e03c",
                      "Termijnagenda van de raad"),
    "moties": ("079ee2f4-3d8c-4119-97c7-ab7f8387e76c", "Motie"),
    "amendementen": ("2b6e70ad-9f59-4638-adf5-9eadaa968969", "Amendement"),
    "schriftelijke_vragen": ("23843e3c-a39c-4ff0-a2cf-d173297f7d6a",
                             "Schriftelijke vragen"),
    "initiatiefvoorstellen": ("42e2617c-7ce9-461e-9d1d-bb57b20c99ec",
                              "Initiatiefvoorstel"),
    "toezeggingen": ("1140c380-bd7a-4e86-b9b8-0b78962e3fcc",
                     "Toezegging van het college"),
}

# Het beleidsveld dat het portaal zelf aan termijnagenda, toezeggingen en
# schriftelijke vragen hangt. Moties en amendementen hebben er geen.
BELEIDSVELD_WONEN = "wonen en stedelijke ontwikkeling"

# Woorden in titel of stand van zaken waarop een stuk meetelt. Een woord is
# een begin van een woord (\b ervoor, niet erna), zodat "verkamer" ook
# "verkamerde" en "verkamering" vindt en "huur" ook "huurders".
# AFGELEID UIT ECHTE TITELS, zie proef(): elke regel hieronder heeft een echte
# titel van het portaal die hij vangt.
TREFWOORDEN = (
    "splits", "verkamer", "kamerverhuur", "kamerbewon", "onzelfstandig",
    "huur", "verhuur", "woning", "woonruimte", "wonen ", "appartement",
    "huisvestingsverordening", "huisvestingsbeleid",
    "opkoop", "transformat", "optop", "omgevingsplan", "omgevingsvisie",
    "bestemmingsplan", "short stay", "vakantieverhuur", "airbnb",
    "vastgoed", "ozb", "onroerendezaak", "erfpacht", "grondbeleid",
    "grondexploitatie", "monument", "erfgoed", "energielabel",
    "blokverwarming",
    "studentenhuisvesting", "middenhuur", "leegstand", "volkshuisvest",
    "woningbouw", "nieuwbouw", "binnenstad",
)

# Vaste woordgroepen die een trefwoord bevatten maar over zorg gaan, niet over
# de woningmarkt. Ze worden uit de tekst gehaald voordat we zoeken; een stuk
# met daarnaast een ander trefwoord telt nog gewoon mee.
#
# GEMETEN OP 24 NOVEMBER 2026, over 2.366 stukken (termijnagenda,
# amendementen, schriftelijke vragen, initiatiefvoorstellen):
#   - "wonen " ving 15 stukken buiten het beleidsveld Wonen, waarvan 7 over
#     beschermd wonen, Wonen Eerst of dakloosheid;
#   - "huisvesting" ving 6 stukken, waarvan 4 over onderwijs, asiel en de
#     dierenambulance. Daarom staan nu alleen huisvestingsverordening en
#     huisvestingsbeleid erin; de huurders van het Vasim vangt "huur";
#   - "bouwen" ving 7 stukken, vooral leuzen in amendementstitels. Weg;
#     woningbouw en nieuwbouw blijven.
UITSLUITEN = ("beschermd wonen", "wonen eerst")
_PATROON = re.compile(r"\b(" + "|".join(re.escape(w) for w in TREFWOORDEN) + ")",
                      re.IGNORECASE)


def _schoon(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def waarom_relevant(rij):
    """
    Waarom dit stuk over wonen of vastgoed gaat, of "" als het dat niet doet.

    De reden gaat mee naar de brief. Een treffer op een woord is een filter en
    geen inhoudelijk oordeel, en dat moet de lezer kunnen zien.
    """
    veld = _schoon(rij.get("beleidsveld") or rij.get("beleidsveldnieuw")).lower()
    if veld == BELEIDSVELD_WONEN:
        return "beleidsveld Wonen en Stedelijke ontwikkeling"
    tekst = " ".join(_schoon(rij.get(k)) for k in ("title", "standvanzaken"))
    for w in UITSLUITEN:
        tekst = re.sub(re.escape(w), " ", tekst, flags=re.IGNORECASE)
    m = _PATROON.search(tekst + " ")
    if m:
        return f"woord: {m.group(1).strip().lower()}"
    return ""


def regel(naam, rij, reden):
    """Een stuk als regel voor de brief."""
    _, kop = LIJSTEN[naam]
    titel = _schoon(rij.get("title")) or "(zonder titel)"
    url = f"{BASIS}/Reports/Item/{rij.get('DT_RowId')}"
    wanneer = ""
    if naam == "termijnagenda":
        delen = []
        if _schoon(rij.get("datumraad")):
            delen.append(f"in de raad gepland {_schoon(rij['datumraad'])}")
        if _schoon(rij.get("portefeuillehouder")):
            delen.append(f"wethouder {_schoon(rij['portefeuillehouder'])}")
        wanneer = ", ".join(delen)
    elif _schoon(rij.get("registrationdate")):
        wanneer = _schoon(rij["registrationdate"])[:110]
    stand = _schoon(rij.get("standvanzaken"))
    tekst = f"- {kop}"
    if wanneer:
        tekst += f" ({wanneer})"
    tekst += f": {titel}."
    if stand:
        tekst += f" Stand van zaken: {stand[:300]}"
    tekst += f" [{reden}] {url}"
    return tekst


def _bladzijde(s, lijst_id, start, pauze, pogingen=3):
    """
    Een bladzijde, met herhaalpogingen.

    WAAROM. De tweede ronde op 24 november 2026 (run 45409724212) verloor
    moties en schriftelijke vragen aan "Remote end closed connection without
    response", midden in een lijst, terwijl de ronde ervoor alles las. Een
    hele lijst opgeven om een losse verbroken verbinding is te veel; drie
    keer proberen met oplopende pauze, en pas daarna opgeven.
    """
    laatste = None
    for poging in range(1, pogingen + 1):
        try:
            r = s.post(f"{BASIS}/Reports/GetReportData/{lijst_id}",
                       data={"draw": 1, "start": start, "length": PAGINA},
                       headers=HEADERS, timeout=(15, 60))
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code} bij start={start}: "
                                   f"{r.text[:120]!r}")
            try:
                return r.json()
            except Exception:
                raise RuntimeError(f"geen JSON bij start={start}: "
                                   f"{r.text[:120]!r}")
        except Exception as e:
            laatste = e
            if poging < pogingen:
                time.sleep(pauze * 2 * poging)
    raise RuntimeError(f"na {pogingen} pogingen: {laatste}")


def haal_lijst(lijst_id, sessie=None, pauze=PAUZE):
    """
    Alle rijen van een lijst, bladzijde voor bladzijde.

    Gooit een fout als een bladzijde mislukt of als het aantal niet klopt met
    recordsTotal. Een halve lijst als hele lijst lezen zou de ontbrekende
    stukken later als nieuw melden.
    """
    import requests
    s = sessie or requests.Session()
    rijen, totaal, start = [], None, 0
    while True:
        j = _bladzijde(s, lijst_id, start, pauze)
        totaal = j.get("recordsTotal")
        deel = j.get("data") or []
        rijen.extend(deel)
        start += PAGINA
        if not deel or (totaal is not None and len(rijen) >= totaal):
            break
        time.sleep(pauze)
    if totaal is not None and len(rijen) != totaal:
        raise RuntimeError(f"{len(rijen)} rijen gelezen, het portaal zegt "
                           f"{totaal}")
    return rijen


def verwerk(stand, resultaten, nu):
    """
    Nieuwe stand en meldregels uit wat er is opgehaald.

    resultaten: {lijst: rijen} voor wat lukte, of {lijst: Exception} voor wat
    mislukte. Zuiver, zonder netwerk of bestanden, zodat de proef het kan
    nameten.
    """
    stand = json.loads(json.dumps(stand or {}))
    regels = []
    for naam, uitkomst in resultaten.items():
        oud = stand.get(naam) or {}
        if isinstance(uitkomst, Exception):
            oud["fout"] = str(uitkomst)[:300]
            oud["laatste_poging"] = nu
            stand[naam] = oud
            continue
        gezien = set(oud.get("gezien") or [])
        nulmeting = "gezien" not in oud
        ids = [r.get("DT_RowId") for r in uitkomst if r.get("DT_RowId")]
        if not nulmeting:
            for rij in uitkomst:
                if rij.get("DT_RowId") in gezien:
                    continue
                reden = waarom_relevant(rij)
                if reden:
                    regels.append(regel(naam, rij, reden))
        stand[naam] = {
            "gezien": sorted(gezien | set(ids)),
            "aantal_op_portaal": len(ids),
            "opgehaald": nu,
            "laatste_poging": nu,
            "nulmeting": nu if nulmeting else oud.get("nulmeting"),
        }
    return stand, regels


# ---------------------------------------------------------------------------
# DE VOLLEDIGE TEKST (24 november 2026)
#
# De lijsten hierboven geven titels. Een woord dat alleen in een raadsvoorstel,
# een woordelijk verslag of een bijlage valt, zien ze niet. Het portaal heeft
# een zoekfunctie over de volledige tekst van alle documenten: een POST naar
# /Search/Results met Query, Page, OrderBy en een __RequestVerificationToken
# die met een cookie bij GET /Search hoort. OrderBy 1 is "Datum (aflopend)".
# Tien treffers per pagina, elk met titel, soort (Document, Overzichtsitem,
# Agenda, Agendapunt), een datum en een tekstfragment rond de treffer. Een "*"
# werkt als jokerteken. Gemeten vanaf GitHub Actions op 24 november 2026, met
# vijf tijdelijke probe-rondes; een fout token geeft HTTP 400.
#
# DE DATUM is die van de vergadering waar het document aan hangt, niet die van
# publicatie: een raadsbrief van 6 oktober staat onder 11 november, en een
# stuk voor een raad in december staat in november al bovenaan. Daarom
# vergelijken we op document-id en niet op datum, en lezen we per term drie
# pagina's: een nieuw stuk bij een oudere vergadering staat niet bovenaan.
#
# DE TERMEN, GEMETEN over 26 augustus tot 24 november 2026 (146 unieke
# documenten bij elf termen, ontdubbeld over termen):
#   - "splitsen" ving 16 documenten die geen andere term had, vooral
#     rekenkamerrapporten, een burgerpeiling en archeologie. Weg; het splitsen
#     van woningen vangen "woningsplitsing", "verkamer*" en "onzelfstandig*".
#   - "transformatie" (3.249 treffers in totaal), "leegstand" (1.938) en
#     "omgevingsplan" (2.344) gaven meer dan vijftig documenten in drie
#     maanden over van alles. Niet opgenomen.
#   - "vakantieverhuur" gaf 7 treffers sinds 2020. Niet opgenomen.
# De documenten komen in golven: 41 in week 36 en 34 in week 42, de weken van
# de huisvestingsverordening en wijziging 2026-01 van het omgevingsplan.
ZOEKTERMEN = (
    "verkamer*", "kamerverhuur", "onzelfstandig*", "woningsplitsing",
    "opkoopbescherming", "short stay", "middenhuur", "optoppen", "plint*",
    "huisvestingsverordening",
)
ZOEK_PAGINAS = 3
MAX_DOCUMENTEN = 12   # daarna alleen titels, zodat een golf de brief niet vult
# Hoe lang een melding hooguit is. De brief leest dit getal hier uit voor de
# grens waarop hij het digest afkapt (brief_verhalend.py daar), zodat de twee
# niet uiteenlopen. pas_in() dwingt het af, ook bij titels die het portaal
# niet inkort.
MAX_TEKENS = 7000
_MAANDEN = {m: i + 1 for i, m in enumerate(
    "januari februari maart april mei juni juli augustus september oktober "
    "november december".split())}


def lees_resultaten(html):
    """
    Treffers uit een antwoord van /Search/Results.

    Gooit een fout als het antwoord geen treffers heeft en ook niet zegt dat
    er niets is gevonden. Een andere pagina (een foutpagina, een nieuw
    ontwerp) als "geen treffers" lezen is "niet gekeken" noemen "niets".
    """
    import html as H
    panelen = re.split(r'<div class="panel" aria-live', html)[1:]
    if not panelen:
        if "Geen resultaten gevonden" in html:
            return []
        raise RuntimeError("antwoord zonder treffers en zonder 'Geen "
                           f"resultaten gevonden': {_schoon(html)[:120]!r}")
    uit = []
    for p in panelen:
        href = re.search(r'href="([^"]+)"', p)
        kop = re.search(r"<h3.*?</h3>", p, re.S)
        if not (href and kop):
            continue
        url = H.unescape(href.group(1))
        if url.startswith("/"):
            url = BASIS + url
        m = re.search(r"id=([0-9a-f-]{36})", url) or re.search(
            r"/Item/([0-9a-f-]{36})", url)
        soort = re.search(r'aria-label="([^"]+)"', p)
        kop_tekst = re.sub(r'<span class="subTitle">.*?</span>', " ",
                           kop.group(0), flags=re.S)
        titel = _schoon(H.unescape(re.sub(r"<[^>]+>", " ", kop_tekst)))
        alinea = re.search(r"<p>(.*?)</p>", p, re.S)
        tekst = _schoon(H.unescape(re.sub(r"<[^>]+>", " ",
                                          alinea.group(1)))) if alinea else ""
        datum = ""
        d = re.match(r"(\d{1,2}) (\w+) (\d{4}) --\s*", tekst)
        if d and d.group(2) in _MAANDEN:
            datum = f"{int(d.group(1)):02d}-{_MAANDEN[d.group(2)]:02d}-{d.group(3)}"
            tekst = tekst[d.end():]
        uit.append({"sleutel": m.group(1) if m else url, "url": url,
                    "titel": titel, "soort": soort.group(1) if soort else "",
                    "datum": datum, "tekst": tekst})
    return uit


def _token(sessie):
    import requests  # noqa
    r = sessie.get(f"{BASIS}/Search", timeout=(15, 60),
                   headers={"User-Agent": HEADERS["User-Agent"]})
    m = re.search(r'name="__RequestVerificationToken" type="hidden" '
                  r'value="([^"]+)"', r.text)
    if r.status_code != 200 or not m:
        raise RuntimeError(f"geen zoektoken (HTTP {r.status_code})")
    return m.group(1)


def zoek(term, sessie, token, pauze=PAUZE, paginas=ZOEK_PAGINAS):
    """De nieuwste treffers op een term, nieuwste vergadering eerst."""
    uit = []
    for pagina in range(1, paginas + 1):
        time.sleep(pauze)
        r = sessie.post(f"{BASIS}/Search/Results",
                        data={"Page": pagina, "Query": term, "OrderBy": "1",
                              "__RequestVerificationToken": token},
                        headers=HEADERS, timeout=(15, 60))
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code} bij '{term}' pagina "
                               f"{pagina}")
        deel = lees_resultaten(r.text)
        uit.extend(deel)
        if len(deel) < 10:
            break
    return uit


def titelsleutel(titel):
    """
    Een titel zonder de voorvoegsels waarmee hetzelfde stuk op meer plekken
    hangt. Gemeten op 24 november 2026: "Raadsvoorstel definitief
    wijzigingsbesluit huisvestingsverordening ..." stond onder drie
    document-id's (1 september, 14 oktober twee keer), de motie "De rust rond
    verkamerde panden kwam niet vanzelf" als Overzichtsitem en als document
    "M De rust rond ...".
    """
    t = _schoon(titel).lower()
    t = re.sub(r"^(m|a|rv bijlage|cv bijlage( \d+)?|voorblad -)\s+", "", t)
    return re.sub(r"[^a-z0-9]+", "", t)[:80]


def _fragment(tekst, termen, breedte=240):
    stammen = [t.rstrip("*").lower() for t in termen]
    laag = tekst.lower()
    posities = [laag.find(s) for s in stammen if laag.find(s) >= 0]
    if not posities:
        return tekst[:breedte]
    begin = max(0, min(posities) - breedte // 3)
    stuk = tekst[begin:begin + breedte]
    return ("..." if begin else "") + stuk + ("..." if begin + breedte < len(tekst) else "")


def verwerk_zoeken(stand, resultaten, nu, al_gemeld=()):
    """
    Nieuwe documenten uit de zoekresultaten, ontdubbeld.

    resultaten: {term: treffers} of {term: Exception}. al_gemeld: titels die
    deze ronde al uit de lijsten komen. Geeft (stand, regels).
    """
    stand = json.loads(json.dumps(stand or {}))
    zk = stand.setdefault("zoeken", {})
    titels = set(stand.get("zoeken_titels") or [])
    nieuw = {}
    for term, uitkomst in resultaten.items():
        oud = zk.get(term) or {}
        if isinstance(uitkomst, Exception):
            oud["fout"] = str(uitkomst)[:300]
            oud["laatste_poging"] = nu
            zk[term] = oud
            continue
        gezien = set(oud.get("gezien") or [])
        nulmeting = "gezien" not in oud
        for t in uitkomst:
            if nulmeting:
                titels.add(titelsleutel(t["titel"]))
            elif t["sleutel"] not in gezien and t["soort"] != "Overzichtsitem":
                nieuw.setdefault(t["sleutel"], dict(t, termen=[]))["termen"].append(term)
        zk[term] = {"gezien": sorted(gezien | {t["sleutel"] for t in uitkomst}),
                    "opgehaald": nu, "laatste_poging": nu,
                    "nulmeting": nu if nulmeting else oud.get("nulmeting")}

    andere = {titelsleutel(t) for t in al_gemeld}
    docs = []
    volgorde = sorted(nieuw.values(), reverse=True,
                      key=lambda d: d["datum"][6:] + d["datum"][3:5] + d["datum"][:2])
    volgorde.sort(key=lambda d: -len(d["termen"]))   # stabiel: daarbinnen nieuwste eerst
    for d in volgorde:
        k = titelsleutel(d["titel"])
        if k in titels or k in andere:
            continue
        titels.add(k)
        docs.append(d)
    stand["zoeken_titels"] = sorted(titels)[-3000:]

    regels = []
    for d in docs[:MAX_DOCUMENTEN]:
        woorden = ", ".join(t.rstrip("*") for t in d["termen"])
        regels.append(f"- {d['titel']}" + (f" ({d['datum']})" if d["datum"] else "")
                      + f" [woorden: {woorden}] \"{_fragment(d['tekst'], d['termen'])}\" "
                      + d["url"])
    rest = docs[MAX_DOCUMENTEN:]
    if rest:
        namen = "; ".join(d["titel"][:70] for d in rest)
        regels.append(f"- En nog {len(rest)} documenten met dezelfde woorden: "
                      f"{namen[:700]}")
    return stand, regels


def pas_in(regels, budget):
    """
    Regels tot ze samen in budget passen; wat niet past wordt een slotregel
    met het aantal. Een regel die alleen al te lang is, wordt ingekort.
    """
    uit, lengte = [], 0
    for i, r in enumerate(regels):
        r = r if len(r) <= budget // 2 else r[:budget // 2 - 3] + "..."
        if lengte + len(r) + 1 > budget - 80:
            uit.append(f"- En nog {len(regels) - i} regels die niet meer in "
                       f"deze melding passen; zie het raadsportaal {BASIS}")
            return uit
        uit.append(r)
        lengte += len(r) + 1
    return uit


def nieuwe_titels(stand, resultaten):
    """Titels van lijststukken die deze ronde nieuw zijn, voor het ontdubbelen."""
    uit = []
    for naam, rijen in resultaten.items():
        if isinstance(rijen, Exception) or "gezien" not in (stand.get(naam) or {}):
            continue
        gezien = set(stand[naam]["gezien"])
        uit += [r.get("title") or "" for r in rijen if r.get("DT_RowId") not in gezien]
    return uit


KOP_LIJSTEN = ("**Gemeenteraad Nijmegen: nieuw over wonen en vastgoed** (op "
               "titel en beleidsveld geselecteerd; tussen haken staat waarop)")
KOP_DOCUMENTEN = ("**Raadsdocumenten waarin deze woorden staan** (gezocht in de "
                  "volledige tekst; een treffer zegt dat het woord erin staat, "
                  "niet dat het stuk erover gaat; de datum is die van de "
                  "vergadering)")


def melding_tekst(regels, docregels):
    """De tekst van een melding, nooit langer dan MAX_TEKENS. Leeg als er niets is."""
    if not (regels or docregels):
        return ""
    vrij = MAX_TEKENS - len(KOP_LIJSTEN) - len(KOP_DOCUMENTEN) - 10
    # De lijststukken krijgen hooguit de helft als er ook documenten zijn: een
    # motie is schaarser en zegt meer dan een treffer in een bijlage.
    deel_l = vrij // 2 if docregels else vrij
    l = pas_in(regels, deel_l) if regels else []
    d = pas_in(docregels, vrij - sum(len(x) + 1 for x in l)) if docregels else []
    blokken = []
    if l:
        blokken.append(KOP_LIJSTEN + "\n" + "\n".join(l))
    if d:
        blokken.append(KOP_DOCUMENTEN + "\n" + "\n".join(d))
    return "\n\n".join(blokken)


def _lees(pad, standaard):
    try:
        with open(pad, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return standaard


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pauze", type=float, default=PAUZE)
    args = ap.parse_args()
    import requests

    wis("raadsinformatie")
    nu = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    sessie = requests.Session()
    resultaten = {}
    for i, (naam, (lijst_id, _)) in enumerate(LIJSTEN.items()):
        if i:
            time.sleep(args.pauze)
        try:
            resultaten[naam] = haal_lijst(lijst_id, sessie, args.pauze)
            print(f"  {naam}: {len(resultaten[naam])} stukken", file=sys.stderr)
        except Exception as e:
            resultaten[naam] = e
            print(f"  {naam}: MISLUKT {e}", file=sys.stderr)

    zoekresultaten = {}
    try:
        time.sleep(args.pauze)
        token = _token(sessie)
        for term in ZOEKTERMEN:
            try:
                zoekresultaten[term] = zoek(term, sessie, token, args.pauze)
                print(f"  zoeken '{term}': {len(zoekresultaten[term])} treffers",
                      file=sys.stderr)
            except Exception as e:
                zoekresultaten[term] = e
                print(f"  zoeken '{term}': MISLUKT {e}", file=sys.stderr)
    except Exception as e:
        zoekresultaten = {t: e for t in ZOEKTERMEN}
        print(f"  zoeken: MISLUKT {e}", file=sys.stderr)

    oude_stand = _lees(STAND_PAD, {})
    al_gemeld = nieuwe_titels(oude_stand, resultaten)
    # In het log welke lijststukken nieuw waren, ook als het filter ze liet
    # liggen: dan is na te gaan of het filter iets mist. Op 24 november stonden
    # er twee nieuwe punten op de termijnagenda en kwam er niets in de
    # meldingen, en was niet te zien welke het waren.
    for titel in al_gemeld:
        print(f"  nieuw op een lijst: {_schoon(titel)[:100]}", file=sys.stderr)
    stand, regels = verwerk(oude_stand, resultaten, nu)
    stand, docregels = verwerk_zoeken(stand, zoekresultaten, nu, al_gemeld)
    with open(STAND_PAD, "w", encoding="utf-8") as f:
        json.dump(stand, f, ensure_ascii=False, indent=1, sort_keys=True)

    # HET BESTAND IS ER OOK ZONDER MELDING. De brief leest een ontbrekend
    # meldingenbestand als "niet gekeken" (meldingen.py daar). Na de nulmeting
    # zijn er nog geen meldingen; zonder dit lege bestand stond de brief dan
    # elke ochtend "overgeslagen" te melden terwijl alles goed ging.
    if not os.path.exists(MELDINGEN_PAD) and not all(
            isinstance(u, Exception) for u in resultaten.values()):
        with open(MELDINGEN_PAD, "w", encoding="utf-8") as f:
            json.dump([], f)
    blokken = melding_tekst(regels, docregels)
    if blokken:
        from regelgeving_monitor import voeg_melding_toe
        voeg_melding_toe(MELDINGEN_PAD, blokken)
    print(f"Raadsinformatie: {len(regels)} nieuwe lijststukken, "
          f"{len(docregels)} regels met documenten", file=sys.stderr)

    mislukt = [n for n, u in resultaten.items() if isinstance(u, Exception)]
    zoek_mislukt = [t for t, u in zoekresultaten.items() if isinstance(u, Exception)]
    if mislukt or zoek_mislukt:
        leg_vast("raadsinformatie",
                 "Niet gelezen: " + "; ".join(
                     [f"{n}: {stand[n].get('fout')}" for n in mislukt]
                     + [f"zoeken '{t}': {stand['zoeken'][t].get('fout')}"
                        for t in zoek_mislukt]))
        return 1
    return 0


# Echte rijen van het portaal, overgenomen op 24 november 2026, met alleen de
# velden die het portaal teruggaf.
_ECHT = {
    "motie_kamers": {
        "DT_RowId": "echt-1",
        "registrationdate": "Besluitronde (raadsvergadering) 14-10-2026 7.",
        "title": "De rust rond verkamerde panden kwam niet vanzelf",
        "raadsleden": "", "portefeuillehouder": "", "status": ""},
    "motie_opkoop": {
        "DT_RowId": "echt-2",
        "registrationdate": "Besluitronde (raadsvergadering) 14-10-2026 7.",
        "title": "Onderzoek hogere grens opkoopbescherming",
        "raadsleden": "", "portefeuillehouder": "", "status": ""},
    "motie_onderhoud": {
        "DT_RowId": "echt-3",
        "registrationdate": "Besluitronde (raadsvergadering) 11-11-2026 7.1. "
                            "Raadsvoorstel Stadsbegroting 2027-2030 (92/2026)",
        "title": "M3 Onderhoud is geen sluitpost, beslispunten 4 en 5",
        "raadsleden": "", "portefeuillehouder": "", "status": ""},
    "termijn_talis": {
        "DT_RowId": "echt-4", "title": "BOPA Neerbosch-Oost Talis",
        "beleidsveld": "Wonen en Stedelijke ontwikkeling",
        "datumraad": "21-04-2027",
        "standvanzaken": "Anterieure overeenkomst wordt voorbereid. Wacht op "
                         "definitieve plan Talis",
        "afgedaan": "Nee", "portefeuillehouder": "K.A. Lokker"},
    "termijn_sport": {
        "DT_RowId": "echt-5", "title": "Onderzoek naar binnensportaccommodaties  ",
        "beleidsveld": "Sport ", "datumraad": "01-05-2029",
        "standvanzaken": "Nog niet gestart. In 2028 laten we onderzoeken of de "
                         "capaciteit van onze binnensportaccommodaties nog "
                         "aansluit bij de sportbehoeften van de stad. ",
        "afgedaan": "Nee", "portefeuillehouder": "E.H Lamers"},
    "vraag_zorg": {
        "DT_RowId": "echt-6", "registrationdate": "19-11-2026",
        "title": "Zorg en opvang voor iedereen",
        "beleidsveldnieuw": "Welzijn, Wijkontwikkeling en Zorg",
        "datumantwoord": None},
    "amendement_verkamering": {
        "DT_RowId": "echt-8", "registrationdate": "2026",
        "title": "Geen versoepeling op verkamering",
        "raadsleden": "", "portefeuillehouder": "", "status": ""},
    "termijn_broerstraat": {
        "DT_RowId": "echt-9",
        "title": "BOPA Broerstraat 32 (toevoegen 3 appartementen)",
        "beleidsveld": "Wonen en Stedelijke ontwikkeling", "datumraad": "",
        "standvanzaken": "", "afgedaan": "Nee", "portefeuillehouder": ""},
    "termijn_binnenstad": {
        "DT_RowId": "echt-10", "title": "Koers voor de Binnenstad",
        "beleidsveld": "", "datumraad": "", "standvanzaken": "",
        "afgedaan": "Nee", "portefeuillehouder": ""},
    "termijn_onderwijs": {
        "DT_RowId": "echt-11", "title": "Integraal Huisvestingsplan Onderwijs",
        "beleidsveld": "Onderwijs", "datumraad": "", "standvanzaken": "",
        "afgedaan": "Nee", "portefeuillehouder": ""},
    "termijn_beschermd": {
        "DT_RowId": "echt-12", "title": "Regioplan beschermd wonen",
        "beleidsveld": "Welzijn, Wijkontwikkeling en Zorg", "datumraad": "",
        "standvanzaken": "", "afgedaan": "Nee", "portefeuillehouder": ""},
    "amendement_blok": {
        "DT_RowId": "echt-7",
        "registrationdate": "Besluitronde (raadsvergadering) 11-11-2026 7.1. "
                            "Raadsvoorstel Stadsbegroting 2027-2030 (92/2026)",
        "title": "A12 Zet huurders met blokverwarming niet voor het blok, "
                 "deel II",
        "raadsleden": "", "portefeuillehouder": "", "status": ""},
}


def proef():
    """Zonder netwerk, op echte rijen van het portaal."""
    fouten = []
    E = _ECHT

    # Het filter op echte titels: wat erin hoort en wat niet.
    moet = ["motie_kamers", "motie_opkoop", "termijn_talis", "amendement_blok",
            "amendement_verkamering", "termijn_broerstraat",
            "termijn_binnenstad"]
    niet = ["motie_onderhoud", "termijn_sport", "vraag_zorg",
            "termijn_onderwijs", "termijn_beschermd"]
    for k in moet:
        if not waarom_relevant(E[k]):
            fouten.append(f"filter mist een echt vastgoedstuk: {E[k]['title']}")
    for k in niet:
        if waarom_relevant(E[k]):
            fouten.append(f"filter neemt een stuk mee dat er niet over gaat: "
                          f"{E[k]['title']} ({waarom_relevant(E[k])})")
    if "beleidsveld" not in waarom_relevant(E["termijn_talis"]):
        fouten.append("de Talis-overeenkomst telt niet via het beleidsveld, "
                      "terwijl de titel geen trefwoord heeft")

    # De eerste keer is een nulmeting: alles gezien, niets gemeld.
    st, r = verwerk({}, {"moties": [E["motie_kamers"], E["motie_onderhoud"]]},
                    "2026-11-24T04:41Z")
    if r:
        fouten.append(f"de nulmeting meldt {len(r)} stukken")
    if st["moties"]["gezien"] != ["echt-1", "echt-3"]:
        fouten.append(f"de nulmeting noteert niet alles als gezien: "
                      f"{st['moties']['gezien']}")

    # De tweede keer: alleen het nieuwe vastgoedstuk, niet het nieuwe andere.
    st2, r2 = verwerk(st, {"moties": [E["motie_opkoop"], E["motie_kamers"],
                                      E["motie_onderhoud"]]},
                      "2026-11-25T04:41Z")
    if len(r2) != 1 or "opkoopbescherming" not in r2[0]:
        fouten.append(f"een nieuw vastgoedstuk komt niet precies een keer: {r2}")
    if r2 and "/Reports/Item/echt-2" not in r2[0]:
        fouten.append("de regel linkt niet naar de pagina van het stuk")
    if r2 and "[woord: opkoop]" not in r2[0]:
        fouten.append(f"de regel zegt niet waarop hij is geselecteerd: {r2[0]}")

    # Een mislukte lijst is niet gekeken: wat we zagen blijft, de fout staat er.
    st3, r3 = verwerk(st2, {"moties": RuntimeError("HTTP 403")},
                      "2026-11-26T04:41Z")
    if st3["moties"].get("gezien") != st2["moties"]["gezien"]:
        fouten.append("een mislukte ronde wist wat we al zagen")
    if "403" not in (st3["moties"].get("fout") or ""):
        fouten.append("een mislukte ronde schrijft zijn reden niet op")
    if st3["moties"].get("opgehaald") != st2["moties"]["opgehaald"]:
        fouten.append("een mislukte ronde doet alsof hij heeft opgehaald")
    st4, r4 = verwerk(st3, {"moties": [E["motie_opkoop"], E["motie_kamers"],
                                       E["motie_onderhoud"]]},
                      "2026-11-27T04:41Z")
    if r4:
        fouten.append("na een mislukte ronde komt alles opnieuw als nieuw")
    if "fout" in st4["moties"]:
        fouten.append("na een geslaagde ronde blijft de oude fout staan")

    # Een lijst die er later bij komt, begint met een eigen nulmeting en
    # stort zijn hele inhoud niet in de brief.
    st5, r5 = verwerk(st4, {"termijnagenda": [E["termijn_talis"]]},
                      "2026-11-27T04:41Z")
    if r5:
        fouten.append("een nieuwe lijst meldt zijn hele inhoud")

    # Een termijnagendaregel zegt wanneer het in de raad komt.
    t = regel("termijnagenda", E["termijn_talis"], "beleidsveld")
    if "21-04-2027" not in t or "Stand van zaken" not in t:
        fouten.append(f"de termijnagendaregel mist datum of stand: {t}")

    fouten += proef_zoeken()
    for f in fouten:
        print(f"FOUT {f}", file=sys.stderr)
    print(f"Proef raadsinformatie: {len(fouten)} fouten", file=sys.stderr)
    return 1 if fouten else 0



def proef_zoeken():
    """
    Op echte antwoorden van /Search/Results, vastgelegd op 24 november 2026 in
    proefdata/ (zoekterm "verkamer*", en een zoekterm zonder treffers).
    """
    fouten = []
    hier = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(hier, "proefdata", "raadsinformatie_zoeken.html"),
              encoding="utf-8") as f:
        vol = f.read()
    with open(os.path.join(hier, "proefdata", "raadsinformatie_zoeken_leeg.html"),
              encoding="utf-8") as f:
        leeg = f.read()

    t = lees_resultaten(vol)
    if [x["soort"] for x in t] != ["Document", "Document", "Overzichtsitem"]:
        fouten.append(f"zoekresultaten verkeerd gelezen: {[x['soort'] for x in t]}")
    else:
        if t[0]["datum"] != "11-11-2026" or t[0]["titel"] != \
                "Woordelijk verslag besluitronde 14 oktober 2026":
            fouten.append(f"titel of datum van een treffer verkeerd: {t[0]['titel']} "
                          f"{t[0]['datum']}")
        if t[2]["titel"] != "De rust rond verkamerde panden kwam niet vanzelf":
            fouten.append(f"de lijstnaam plakt aan de titel: {t[2]['titel']}")
        if t[0]["sleutel"] != "da7f7bbc-f998-42ad-ac07-b55e56d3ecee":
            fouten.append(f"document-id verkeerd: {t[0]['sleutel']}")
        if "335.000" not in t[1]["tekst"] or t[1]["tekst"].startswith("14 oktober"):
            fouten.append("het tekstfragment is verkeerd gelezen")
    if lees_resultaten(leeg) != []:
        fouten.append("'Geen resultaten gevonden' wordt niet als leeg gelezen")
    try:
        lees_resultaten("<html><title>Foutpagina - iBabs</title></html>")
        fouten.append("een foutpagina telt als 'geen treffers'")
    except RuntimeError:
        pass

    nu1, nu2 = "2026-11-24T04:41Z", "2026-11-25T04:41Z"
    st, r = verwerk_zoeken({}, {"verkamer*": t}, nu1)
    if r:
        fouten.append(f"de nulmeting van het zoeken meldt {len(r)} regels")

    import copy
    nieuw_doc = dict(copy.deepcopy(t[1]), sleutel="nieuw-1",
                     titel="Raadsbrief splitsen in de binnenstad")
    kopie = dict(copy.deepcopy(t[0]), sleutel="kopie-1")      # zelfde titel, ander id
    nieuw_item = dict(copy.deepcopy(t[2]), sleutel="item-1",
                      titel="Nieuwe motie over kamers")       # Overzichtsitem
    motie_doc = dict(copy.deepcopy(t[1]), sleutel="motie-1",
                     titel="M Onderzoek hogere grens opkoopbescherming")
    st2, r2 = verwerk_zoeken(st, {"verkamer*": [nieuw_doc, kopie, nieuw_item,
                                                motie_doc] + t}, nu2,
                             al_gemeld=["Onderzoek hogere grens opkoopbescherming"])
    if len(r2) != 1 or "Raadsbrief splitsen in de binnenstad" not in r2[0]:
        fouten.append(f"een nieuw document komt niet precies een keer: {r2}")
    if r2 and ("[woorden: verkamer]" not in r2[0] or "335.000" not in r2[0]
               or "publicdownload.aspx" not in r2[0]):
        fouten.append(f"de documentregel mist woord, fragment of link: {r2[0]}")

    st3, r3 = verwerk_zoeken(st2, {"verkamer*": RuntimeError("HTTP 400")}, nu2)
    if st3["zoeken"]["verkamer*"].get("gezien") != st2["zoeken"]["verkamer*"]["gezien"] \
            or "400" not in st3["zoeken"]["verkamer*"].get("fout", ""):
        fouten.append("een mislukte zoekronde wist wat we zagen of zwijgt over de fout")

    golf = [dict(copy.deepcopy(t[1]), sleutel=f"g{i}", titel=f"Document nummer {i}")
            for i in range(MAX_DOCUMENTEN + 3)]
    _, r4 = verwerk_zoeken(st2, {"verkamer*": golf}, nu2)
    if len(r4) != MAX_DOCUMENTEN + 1 or "En nog 3 documenten" not in r4[-1]:
        fouten.append(f"een golf documenten wordt niet afgekapt: {len(r4)} regels")

    a = dict(copy.deepcopy(t[1]), sleutel="x1", titel="Een", datum="01-09-2026")
    b = dict(copy.deepcopy(t[1]), sleutel="x2", titel="Twee", datum="14-10-2026")
    c = dict(copy.deepcopy(t[1]), sleutel="x3", titel="Drie", datum="01-09-2026")
    st5, _ = verwerk_zoeken(st2, {"verkamer*": [], "kamerverhuur": []}, nu2)
    _, r5 = verwerk_zoeken(st5, {"verkamer*": [a, b, c], "kamerverhuur": [c]}, nu2)
    volg = [x.split(" (")[0][2:] for x in r5]
    if volg != ["Drie", "Twee", "Een"]:
        fouten.append(f"volgorde is niet: meeste woorden, dan nieuwste: {volg}")
    # De melding blijft binnen MAX_TEKENS, hoe lang de titels ook zijn.
    lang = [f"- {'Een heel lange titel ' * 40} {i}" for i in range(40)]
    m = melding_tekst(lang, lang)
    if len(m) > MAX_TEKENS:
        fouten.append(f"de melding is {len(m)} tekens, langer dan MAX_TEKENS")
    if "En nog" not in m or KOP_DOCUMENTEN not in m or KOP_LIJSTEN not in m:
        fouten.append("een te lange melding verliest een kop of zegt niet "
                      "hoeveel er wegviel")
    if melding_tekst(["- kort"], []) != KOP_LIJSTEN + "\n- kort":
        fouten.append("een korte melding wordt verbouwd")
    return fouten


if __name__ == "__main__":
    if "--proef" in sys.argv:
        sys.exit(proef())
    sys.exit(main() or 0)
