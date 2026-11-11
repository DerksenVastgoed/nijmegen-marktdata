#!/usr/bin/env python3
"""
Bouwt een archief van Nijmeegse bekendmakingen die iets zeggen over
kamerverhuur, omzetting, splitsing, transformatie of brandveilig gebruik.

Het archief wordt per adres doorzoekbaar gemaakt, zodat marktprijzen_bag.py
bij een pand kan tonen of daar ooit iets over gepubliceerd is.

BELANGRIJK: een treffer is een SIGNAAL, geen bewijs van een geldige vergunning.
Het archief van officiele bekendmakingen gaat maar enkele jaren terug, en een
gepubliceerde aanvraag zegt niets over de uitkomst. Geen treffer betekent dus
uitdrukkelijk NIET dat er geen vergunning is.

Gebruik:
  python bekendmakingen_archief.py --vanaf 2026-05-01              # test, korte periode
  python bekendmakingen_archief.py --vanaf 2012-01-01              # volledige backfill

Voor de leefbaarheidstoets is een korte terugblik te weinig. De verordening
noemt geen termijn; de ambtelijke adviesgroep beoordeelt of het woonmilieu al
onder druk staat, en daar telt de opbouw over jaren in mee. Ga daarom zo ver
terug als de bron toelaat. De officiele bekendmakingen van gemeenten lopen
ongeveer terug tot 2012; eerder is er niets digitaal. Loopt de backfill
vast, dan kun je hem in stukken draaien: eerst 2012 tot 2016, dan verder.
Het archief wordt samengevoegd, dus meerdere keren draaien is veilig.
  python bekendmakingen_archief.py --vanaf 2026-08-01 --stil       # dagelijks bijwerken

Het archief wordt samengevoegd, niet overschreven. Meerdere keren draaien is veilig.
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import time

import pandsleutel as _psl
import sru

ARCHIEF_PAD = "bekendmakingen_archief.json"

# Pauze tussen twee bevragingen. Bij een volledige backfill loopt dit op tot
# honderden verzoeken; te snel achter elkaar levert 503-fouten op.
PAUZE = float(os.environ.get("SRU_PAUZE", "1.0"))

# Alleen bekendmakingen die iets zeggen over het gebruik van een pand.
SIGNAALWOORDEN = {
    "kamerverhuur": ["kamerverhuur", "kamerbewoning", "onzelfstandige woonruimte",
                     "onzelfstandige wooneenhe", "verkamer"],
    "brandveilig gebruik": ["brandveilig gebruik"],
    "omzetting": ["omzetten", "omzetting", "omgezet"],
    "splitsing": ["splits", "woningvorming", "wooneenhe", "appartementsrecht"],
    "samenvoeging": ["samenvoeg"],
    "transformatie": ["transformatie", "herbestemm", "logiesfunctie",
                      "kantoorfunctie naar", "winkelfunctie naar"],
    "onttrekking": ["onttrekking", "onttrekken"],
    "tijdelijke verhuur": ["tijdelijk verhuren", "tijdelijke verhuur"],

    # Gewone verbouwingen. Die zeggen niets over de voorraad, maar wel over het
    # pand: gekocht en daarna verbouwd is het spoor waar we naar zoeken, en een
    # pand dat in tien jaar niets heeft aangevraagd is waarschijnlijk niet
    # aangepakt. Bewust zonder kap-, inrit-, evenement- en standplaatsberichten.
    "verbouwing": ["verbouwen", "het bouwen van", "uitbreiden van de woning",
                   "aanbouw", "dakkapel", "dakopbouw", "gevelwijziging",
                   "constructieve", "interne verbouwing", "renovatie"],

    # Handhaving per adres. De politiecijfers gaan niet dieper dan de buurt,
    # maar handhavingsbesluiten worden wel per pand gepubliceerd. Voor de
    # leefbaarheidstoets en voor het risico bij aankoop is dat het enige
    # openbare signaal op objectniveau.
    "sluiting": ["sluiting van de woning", "sluiting van het pand", "woningsluiting",
                 "artikel 13b", "13b opiumwet", "sluitingsbevel", "gesloten verklaard"],
    "handhaving": ["last onder dwangsom", "last onder bestuursdwang", "bestuursdwang",
                   "bestuurlijke boete", "invordering dwangsom", "handhavingsbesluit",
                   "voornemen tot handhaving"],
    "onrechtmatig gebruik": ["onrechtmatige bewoning", "illegale bewoning",
                             "zonder vergunning verhuurd", "strijdig gebruik",
                             "in strijd met het bestemmingsplan"],
    "geluidsoverlast": ["geluidsoverlast", "geluidhinder", "geluidsklacht",
                        "akoestisch onderzoek", "hogere waarde", "geluidsnorm",
                        "wet geluidhinder", "geluidwerende", "geluidsisolatie",
                        "horecaoverlast", "overlastmelding", "sluitingstijd"],
}


def haal_periode(vanaf, tot, stil=False):
    """
    Records voor een periode, via sru.py.

    Tot 11 november stond hier een eigen kopie van de SRU-aanroep. Die gaf bij
    een pagina die na vier pogingen niet lukte een halve lijst terug, en dat zag
    eruit als een rustige maand. Nu gooit sru.haal() een fout; die vangen we
    hier per maandblok, zodat één slechte maand de rest niet tegenhoudt, maar
    de fout staat wel in de log en in het eindverslag.
    """
    try:
        records = sru.haal(sru.bouw_cql(vanaf, tot), pauze=PAUZE, stil=stil)
    except Exception as e:
        print(f"  FOUT {vanaf}..{tot}: {e}", file=sys.stderr)
        MISLUKT.append(f"{vanaf}..{tot}")
        return []
    if not stil:
        print(f"  {vanaf}..{tot}: {len(records)} records", file=sys.stderr)
    time.sleep(PAUZE * 2)   # adempauze voordat het volgende blok begint
    return records


MISLUKT = []


# DE TITELVORM VAN VOOR 2024. Tot de Omgevingswet publiceerde Nijmegen
# "de Kluijskamp 1159 Nijmegen: aanvraag kamerverhuurvergunning -
# onttrekkingsvergunning - Aanvraag ontvangen" (gmb-2023-3231): het adres
# vooraan, zonder postcode en zonder "aan". De backfill van 15 oktober 2026
# over oktober 2021 tot januari 2025 haalde de records wel op, maar deze
# functie vond in geen enkele titel een adres, en dus kwam er niets in het
# archief terwijl de stap groen was.
_OUDE_VORM = re.compile(r"^\s*(.+?)\s+(\d+)\s*([A-Za-z])?\s*(?:[-/]\s*\S+\s*)?"
                        r"Nijmegen\s*:")


def adres_uit_titel(titel):
    """Haalt (straat, huisnummer) uit een bekendmakingstitel. Neemt de laatste 'aan'."""
    oud = _OUDE_VORM.match(titel or "")
    pc = re.search(r",?\s+\d{4}\s?[A-Z]{2}\s+Nijmegen", titel)
    if oud and not pc:
        return oud.group(1).strip(), oud.group(2)
    if not pc:
        return None
    kop = titel[:pc.start()]
    delen = re.split(r"\baan\s+", kop, flags=re.IGNORECASE)
    if len(delen) < 2:
        return None
    straatdeel = delen[-1].strip().rstrip(",").strip()
    straatdeel = re.split(r"\s+en\s+\d", straatdeel)[0].strip()
    # Een bereik van twee huisnummers, zoals "Berg en Dalseweg 11-11A". Die
    # vorm komt juist voor bij woningvorming, waar twee adressen in het spel
    # zijn. Zonder deze regel leverde zo'n titel geen adres op en kwam de
    # bekendmaking in geen enkele pandgeschiedenis terecht.
    bereik = re.match(r"^(.+?\s+\d+\s*[A-Za-z]?)\s*[-/]\s*\d+\s*[A-Za-z]?\s*$",
                      straatdeel)
    if bereik:
        straatdeel = bereik.group(1).strip()
    a = re.match(r"^(.+?)\s+(\d+)\s*([A-Za-z])?\s*$", straatdeel)
    if not a:
        return None
    return a.group(1).strip(), a.group(2)


def sleutel(straat, huisnr):
    """De sleutel van dit archief: per publicatietitel.

    Die vorm laat het lidwoord staan en gooit accenten weg, want een titel
    als "aan de Pijnboomstraat 4" levert "de Pijnboomstraat" als straatnaam
    op. Dat is met opzet niet gelijkgetrokken met de sleutel per woning:
    pandsleutel.sleutel_archief() legt uit waarom. Hij stond hier en in
    marktprijzen_bag.py woordelijk uitgeschreven, en twee kopieen van een
    regel lopen uiteen."""
    return _psl.sleutel_archief(straat, huisnr)


def signalen_in(titel):
    """Welke soorten signalen zitten in deze titel?"""
    laag = titel.lower()
    gevonden = []
    for soort, woorden in SIGNAALWOORDEN.items():
        if any(w in laag for w in woorden):
            gevonden.append(soort)
    return gevonden


def lees_archief():
    if not os.path.exists(ARCHIEF_PAD):
        return {}
    try:
        with open(ARCHIEF_PAD, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def schrijf_archief(archief):
    with open(ARCHIEF_PAD, "w", encoding="utf-8") as f:
        json.dump(archief, f, ensure_ascii=False, indent=1, sort_keys=True)


def maanden(vanaf, tot):
    """Splitst een periode in maandblokken, zodat we onder de recordlimiet blijven."""
    d = dt.date.fromisoformat(vanaf)
    eind = dt.date.fromisoformat(tot)
    while d <= eind:
        if d.month == 12:
            volgende = dt.date(d.year + 1, 1, 1)
        else:
            volgende = dt.date(d.year, d.month + 1, 1)
        blok_eind = min(volgende - dt.timedelta(days=1), eind)
        yield d.isoformat(), blok_eind.isoformat()
        d = volgende


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vanaf", required=True, help="startdatum, bv 2023-01-01")
    ap.add_argument("--tot", default=dt.date.today().isoformat())
    ap.add_argument("--stil", action="store_true", help="minder logregels")
    args = ap.parse_args()

    archief = lees_archief()
    voor = sum(len(v) for v in archief.values())
    print(f"Archief bij start: {len(archief)} adressen, {voor} publicaties", file=sys.stderr)

    totaal_records = 0
    nieuw = 0
    for blok_van, blok_tot in maanden(args.vanaf, args.tot):
        records = haal_periode(blok_van, blok_tot, args.stil)
        totaal_records += len(records)
        for rec in records:
            titel = sru.eerste_tekst(rec, "title") or ""
            if not titel:
                continue
            soorten = signalen_in(titel)
            if not soorten:
                continue
            adres = adres_uit_titel(titel)
            if not adres:
                continue
            k = sleutel(*adres)
            datum = sru.eerste_tekst(rec, "date") or sru.eerste_tekst(rec, "available") or ""
            item = {
                "datum": datum,
                "titel": titel,
                "soorten": soorten,
                "url": sru.url_uit_record(rec),
            }
            bestaand = archief.setdefault(k, [])
            if not any(b.get("titel") == titel and b.get("datum") == datum for b in bestaand):
                bestaand.append(item)
                nieuw += 1

    for k in archief:
        archief[k].sort(key=lambda x: x.get("datum", ""), reverse=True)

    schrijf_archief(archief)
    na = sum(len(v) for v in archief.values())
    print(f"Doorzocht: {totaal_records} records", file=sys.stderr)
    print(f"Nieuw toegevoegd: {nieuw} publicaties", file=sys.stderr)
    print(f"Archief nu: {len(archief)} adressen, {na} publicaties", file=sys.stderr)
    if MISLUKT:
        print(f"NIET OPGEHAALD: {len(MISLUKT)} maandblok(ken): {', '.join(MISLUKT)}. "
              f"Die staan er bij de volgende ronde wel bij, want die kijkt "
              f"terug.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
