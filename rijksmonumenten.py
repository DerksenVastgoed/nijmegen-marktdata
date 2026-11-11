#!/usr/bin/env python3
"""
Haalt de rijksmonumenten van Nijmegen op uit het Rijksmonumentenregister
en bewaart ze per adres, zodat marktprijzen_bag.py bij een pand kan tonen
of het een rijksmonument is.

Bron: Rijksdienst voor het Cultureel Erfgoed (RCE), Linked Open Data API.
Geen registratie of key nodig. De RCE vraagt wel om bronvermelding.

Gebruik:
  python rijksmonumenten.py                 # haalt Nijmegen op en schrijft het bestand
  python rijksmonumenten.py --debug         # toont ook welke velden de API teruggeeft
  python rijksmonumenten.py --plaats Lent   # andere woonplaats

Het bestand hoeft niet dagelijks ververst te worden; het register verandert
zelden. Eens per kwartaal meedraaien is ruim voldoende.
"""

import argparse
import json
import os
import re
import sys
import time

import requests


import pandsleutel as _psl
API = "https://api.linkeddata.cultureelerfgoed.nl/queries/rce/rest-api-rijksmonumenten/run"
UIT_PAD = "rijksmonumenten_nijmegen.json"
PAGINA_GROOTTE = 200
HEADERS = {"Accept": "application/json",
           "User-Agent": "NijmegenVastgoedMonitor/1.0"}

# Mogelijke veldnamen in de respons. De API is JSON-LD, dus de sleutels kunnen
# per query verschillen. We proberen ze op volgorde.
VELD_ADRES = ["volledigAdres", "adres", "volledigadres", "adresLabel",
              "heeftAdres", "fullAddress", "adresseringLabel"]
VELD_STRAAT = ["straat", "straatnaam", "openbareRuimteNaam", "straatLabel",
               "openbareRuimte", "thoroughfare"]
VELD_POSTCODE = ["postcode", "postcodeLabel", "postalCode"]
VELD_NUMMER = ["rijksmonumentnummer", "monumentnummer", "monumentnummerLabel",
               "identificatie", "nummer"]
VELD_FUNCTIE = ["oorspronkelijkeFunctie", "functie", "oorspronkelijkeFunctieLabel",
                "heeftOorspronkelijkeFunctie"]
VELD_AARD = ["monumentaard", "aard", "monumentaardLabel", "type"]


def lees(pad=UIT_PAD):
    """Het bestand per adres, of {} als het er niet is.

    EEN LEZER. Tot 18 oktober 2026 stond deze functie twee keer in de repo,
    als lees_monumenten() in marktprijzen_bag.py en in
    bekendmakingen_nijmegen.py, elk met een eigen kopie van het pad."""
    try:
        with open(pad, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _pak(rij, namen):
    for naam in namen:
        waarde = rij.get(naam)
        if isinstance(waarde, list) and waarde:
            waarde = waarde[0]
        if waarde not in (None, ""):
            return str(waarde).strip()
    return ""


def sleutel(straat, huisnr):
    """De sleutel van rijksmonumenten_nijmegen.json: per woning.

    Een van de veertien sleutelfuncties in elf bestanden die allemaal hetzelfde
    bedoelden en op drie punten uiteenliepen: of een titel werd afgekort,
    of een accent wegviel of bleef staan, en of "doctor" meedeed. Op de
    adressen die we volgen gaven twee van die veertien 41 keer een andere
    sleutel. De functie blijft staan omdat de aanroepers hem gebruiken, maar
    hij rekent niet meer zelf."""
    return _psl.sleutel(straat, huisnr)


def split_adres(volledig, straat_veld):
    """
    Haalt (straat, huisnummer) uit het adresveld.
    'Vondelstraat 77' -> ('Vondelstraat', '77')
    Valt terug op het losse straatveld als het nummer ontbreekt.
    """
    bron = (volledig or straat_veld or "").strip()
    if not bron:
        return None
    m = re.match(r"^(.+?)\s+(\d+)\s*[A-Za-z]?\s*$", bron)
    if not m:
        return None
    return m.group(1).strip(), m.group(2)


def haal_pagina(plaats, pagina, debug=False):
    params = {
        "woonplaatsnaam": plaats,
        "status": "rijksmonument",
        "page": pagina,
        "pageSize": PAGINA_GROOTTE,
    }
    laatste_fout = None
    for poging in range(1, 4):
        try:
            r = requests.get(API, params=params, headers=HEADERS, timeout=(20, 90))
            r.raise_for_status()
            data = r.json()
            break
        except Exception as e:
            laatste_fout = e
            if poging < 3:
                wacht = poging * 5
                print(f"  poging {poging} mislukt, opnieuw over {wacht}s", file=sys.stderr)
                time.sleep(wacht)
    else:
        print(f"  pagina {pagina} definitief mislukt: {laatste_fout}", file=sys.stderr)
        return None  # None = netwerkprobleem, [] = geen resultaten

    # De respons kan een lijst zijn, of een object met de lijst erin
    if isinstance(data, dict):
        for sleutelnaam in ("results", "data", "items", "@graph"):
            if isinstance(data.get(sleutelnaam), list):
                data = data[sleutelnaam]
                break
    if not isinstance(data, list):
        print(f"  onverwacht antwoord op pagina {pagina}: {type(data).__name__}", file=sys.stderr)
        return []

    if debug and data:
        print(f"  DEBUG velden in eerste record: {sorted(data[0].keys())}", file=sys.stderr)
        print(f"  DEBUG eerste record: "
              f"{json.dumps(data[0], ensure_ascii=False)[:600]}", file=sys.stderr)
    return data



def _waarde(term):
    """Haalt de waarde uit een RDF-term ({'termType':..., 'value':...})."""
    if isinstance(term, dict):
        return term.get("value", "")
    return str(term)


def groepeer_triples(rijen):
    """
    De API geeft RDF-tripletjes terug: [onderwerp, eigenschap, waarde].
    Hier groeperen we ze per onderwerp tot een object met eigenschappen,
    zodat we er alsnog adressen uit kunnen halen.
    """
    per_subject = {}
    eigenschappen = {}
    for rij in rijen:
        if not (isinstance(rij, (list, tuple)) and len(rij) >= 3):
            continue
        subject = _waarde(rij[0])
        predicaat = _waarde(rij[1])
        waarde = _waarde(rij[2])
        if not subject:
            continue
        kort = predicaat.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        eigenschappen[kort] = eigenschappen.get(kort, 0) + 1
        obj = per_subject.setdefault(subject, {})
        if kort in obj:
            if isinstance(obj[kort], list):
                obj[kort].append(waarde)
            else:
                obj[kort] = [obj[kort], waarde]
        else:
            obj[kort] = waarde
    return per_subject, eigenschappen


def is_triple_respons(rijen):
    return bool(rijen) and isinstance(rijen[0], (list, tuple))



def verzamel_uit_triples(rijen, alles):
    """
    De RCE levert linked data: het monument en zijn adres zijn losse objecten,
    verbonden via relatie-objecten. We groeperen alle tripletjes per object,
    zoeken de objecten die een adres dragen, en klimmen via de verwijzingen
    terug omhoog naar het monument om nummer en functie op te halen.
    Geeft het aantal toegevoegde adressen terug.
    """
    objecten, _ = groepeer_triples(rijen)

    # Wie verwijst naar wie? Nodig om van adres terug naar monument te lopen.
    verwijst_naar_mij = {}
    for subject, obj in objecten.items():
        for waarde in obj.values():
            for v in (waarde if isinstance(waarde, list) else [waarde]):
                if isinstance(v, str) and v.startswith("http"):
                    verwijst_naar_mij.setdefault(v, set()).add(subject)

    def monument_boven(subject, diepte=0):
        """Zoekt omhoog naar een object met een rijksmonumentnummer."""
        if diepte > 4:
            return None
        for ouder in verwijst_naar_mij.get(subject, ()):
            obj = objecten.get(ouder, {})
            if "rijksmonumentnummer" in obj:
                return obj
            gevonden = monument_boven(ouder, diepte + 1)
            if gevonden:
                return gevonden
        return None

    def enkel(waarde):
        if isinstance(waarde, list):
            for v in waarde:
                if v and not str(v).startswith("http"):
                    return str(v)
            return str(waarde[0]) if waarde else ""
        return str(waarde or "")

    toegevoegd = 0
    for subject, obj in objecten.items():
        straat = enkel(obj.get("openbareRuimte"))
        huisnr = enkel(obj.get("huisnummer"))
        if not straat or not huisnr:
            # Soms staat het volledige adres in een enkel veld
            volledig = enkel(obj.get("volledigAdres"))
            gesplitst = split_adres(volledig, "")
            if not gesplitst:
                continue
            straat, huisnr = gesplitst
        if not huisnr.isdigit():
            continue

        mon = monument_boven(subject) or {}
        letter = enkel(obj.get("huisletter"))
        adres_tekst = f"{straat} {huisnr}{letter}".strip()

        item = {
            "adres": adres_tekst,
            "nummer": enkel(mon.get("rijksmonumentnummer")),
            "postcode": enkel(obj.get("postcode")),
            "functie": enkel(mon.get("heeftFunctieNaam")) or enkel(mon.get("hoofdfunctie")),
            "naam": enkel(mon.get("naam")) or enkel(mon.get("prefLabel")),
        }
        k = sleutel(straat, huisnr)
        alles.setdefault(k, [])
        if not any(b.get("adres") == item["adres"] and b.get("nummer") == item["nummer"]
                   for b in alles[k]):
            alles[k].append(item)
            toegevoegd += 1
    return toegevoegd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plaats", default="Nijmegen")
    ap.add_argument("--uit", default=UIT_PAD)
    ap.add_argument("--debug", action="store_true",
                    help="toon de velden die de RCE-API teruggeeft")
    args = ap.parse_args()

    alles = {}
    zonder_adres = 0
    geen_object = 0
    totaal = 0
    eerste_record = None
    gemeld_triples = False

    netwerkfout = False
    for pagina in range(1, 200):
        rijen = haal_pagina(args.plaats, pagina, args.debug and pagina == 1)
        if rijen is None:
            netwerkfout = True
            break
        if not rijen:
            break
        totaal += len(rijen)

        if is_triple_respons(rijen):
            if not gemeld_triples:
                gemeld_triples = True
                objecten, eigenschappen = groepeer_triples(rijen)
                print(f"  Linked data: {len(rijen)} feiten over {len(objecten)} objecten "
                      f"op pagina 1", file=sys.stderr)
            nieuw_op_pagina = verzamel_uit_triples(rijen, alles)
            print(f"  pagina {pagina}: {len(rijen)} feiten, "
                  f"{nieuw_op_pagina} nieuwe adressen (totaal {len(alles)})", file=sys.stderr)
        else:
            for rij in rijen:
                if eerste_record is None:
                    eerste_record = rij
                if not isinstance(rij, dict):
                    geen_object += 1
                    continue
                volledig = _pak(rij, VELD_ADRES)
                straat_veld = _pak(rij, VELD_STRAAT)
                gesplitst = split_adres(volledig, straat_veld)
                if not gesplitst:
                    zonder_adres += 1
                    continue
                k = sleutel(*gesplitst)
                item = {
                    "adres": volledig or f"{gesplitst[0]} {gesplitst[1]}",
                    "nummer": _pak(rij, VELD_NUMMER),
                    "postcode": _pak(rij, VELD_POSTCODE),
                    "functie": _pak(rij, VELD_FUNCTIE),
                    "aard": _pak(rij, VELD_AARD),
                }
                alles.setdefault(k, [])
                if not any(b.get("nummer") == item["nummer"] for b in alles[k]):
                    alles[k].append(item)
            print(f"  pagina {pagina}: {len(rijen)} records", file=sys.stderr)

        time.sleep(0.4)

    if netwerkfout and not alles:
        print("De RCE-API was niet bereikbaar. Bestaand bestand blijft ongewijzigd.",
              file=sys.stderr)
        print("Tip: draai dit script een keer op je eigen computer en commit het "
              "resultaat. Het monumentenregister verandert nauwelijks.", file=sys.stderr)
        sys.exit(0)

    with open(args.uit, "w", encoding="utf-8") as f:
        json.dump(alles, f, ensure_ascii=False, indent=1, sort_keys=True)

    print(f"Opgehaald: {totaal} records voor {args.plaats}", file=sys.stderr)
    print(f"Zonder bruikbaar huisnummer: {zonder_adres}", file=sys.stderr)
    if geen_object:
        print(f"Records die geen object waren: {geen_object}", file=sys.stderr)
    print(f"Weggeschreven: {len(alles)} adressen naar {args.uit}", file=sys.stderr)
    if totaal and not alles and eerste_record is not None:
        print("", file=sys.stderr)
        print("LET OP: records opgehaald maar geen adressen herkend.", file=sys.stderr)
        print("De veldnamen wijken af van wat dit script verwacht. Hieronder het "
              "eerste record, zodat de juiste namen zichtbaar zijn:", file=sys.stderr)
        print(f"  TYPE: {type(eerste_record).__name__}", file=sys.stderr)
        if isinstance(eerste_record, dict):
            print(f"  VELDNAMEN: {sorted(eerste_record.keys())}", file=sys.stderr)
        try:
            inhoud = json.dumps(eerste_record, ensure_ascii=False)
        except Exception:
            inhoud = repr(eerste_record)
        print(f"  INHOUD: {inhoud[:1200]}", file=sys.stderr)


if __name__ == "__main__":
    main()
