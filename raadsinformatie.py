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

WAT ER NIET IN ZIT. Dit leest titels, beleidsveld en stand van zaken, niet de
tekst van raadsvoorstellen of notulen. Een woord dat alleen in een bijlage
valt, ziet dit niet. Dat staat in VERBETERLIJST als volgende stap.

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

    stand, regels = verwerk(_lees(STAND_PAD, {}), resultaten, nu)
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
    if regels:
        from regelgeving_monitor import voeg_melding_toe
        kop = ("**Gemeenteraad Nijmegen: nieuw over wonen en vastgoed** "
               "(op titel en beleidsveld geselecteerd; tussen haken staat "
               "waarop)")
        voeg_melding_toe(MELDINGEN_PAD, kop + "\n" + "\n".join(regels))
    print(f"Raadsinformatie: {len(regels)} nieuwe stukken over wonen en "
          f"vastgoed", file=sys.stderr)

    mislukt = [n for n, u in resultaten.items() if isinstance(u, Exception)]
    if mislukt:
        leg_vast("raadsinformatie",
                 "Niet gelezen: " + "; ".join(
                     f"{n}: {stand[n].get('fout')}" for n in mislukt))
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

    for f in fouten:
        print(f"FOUT {f}", file=sys.stderr)
    print(f"Proef raadsinformatie: {len(fouten)} fouten", file=sys.stderr)
    return 1 if fouten else 0


if __name__ == "__main__":
    if "--proef" in sys.argv:
        sys.exit(proef())
    sys.exit(main() or 0)
