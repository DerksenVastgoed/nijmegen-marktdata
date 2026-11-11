#!/usr/bin/env python3
"""
Haalt de geregistreerde misdrijven per buurt op uit het politiedataportaal van
het CBS en bewaart ze per buurt.

Bron: dataderden.cbs.nl, tabel 47018NED (jaarcijfers per wijk en buurt).
Open data, geen sleutel nodig, licentie CC-BY.

Er zijn ruim zestig misdrijfsoorten. We halen er een selectie op die voor een
verhuurder telt: wat de leefbaarheidstoets bij een omzettingsvergunning weegt,
wat de verhuurbaarheid raakt, en wat een risico is in het eigen pand.

Gebruik:
  python misdrijven_buurt.py            # laatste twee jaar
  python misdrijven_buurt.py --jaren 4  # meer historie, voor de trend
"""

import argparse
import json
import os
import sys
import time
import urllib.parse

import requests

BASIS = "https://dataderden.cbs.nl/ODataApi/OData/47018NED"
UIT = "misdrijven_per_buurt.json"
GEMEENTE = "Nijmegen"
HEADERS = {"Accept": "application/json",
           "User-Agent": "NijmegenVastgoedMonitor/1.0"}

# De soorten die ertoe doen, met een leesbare naam en waarom ze meetellen.
SOORTEN = {
    "0.0.0 ": ("totaal", "alle geregistreerde misdrijven"),
    "1.1.1 ": ("woninginbraak", "raakt verhuurbaarheid en verzekering"),
    "1.1.2 ": ("inbraak schuur of garage", "raakt bijgebouwen"),
    "1.2.3 ": ("fietsendiefstal", "hoog in studentenbuurten"),
    "1.4.5 ": ("mishandeling", "straatveiligheid"),
    "1.4.6 ": ("straatroof", "straatveiligheid"),
    "1.6.1 ": ("brand of ontploffing", "brandstichting, raakt verzekering"),
    "2.1.1 ": ("drugs- en drankoverlast", "weegt in de leefbaarheidstoets"),
    "2.2.1 ": ("vernieling", "weegt in de leefbaarheidstoets"),
    "2.4.1 ": ("burengerucht", "weegt in de leefbaarheidstoets"),
    "2.4.2 ": ("huisvredebreuk", "kraak en overlast"),
    "3.1.1 ": ("drugshandel", "risico op kwekerij in een huurpand"),
}


def haal(pad, filter_=None, select=None):
    """Haalt een deel van de OData-tabel op, met paginering."""
    params = {}
    if filter_:
        params["$filter"] = filter_
    if select:
        params["$select"] = select
    url = f"{BASIS}/{pad}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    uit = []
    while url:
        for poging in range(1, 4):
            try:
                r = requests.get(url, headers=HEADERS, timeout=(15, 90))
                r.raise_for_status()
                body = r.json()
                break
            except Exception as e:
                if poging == 3:
                    print(f"  ophalen mislukt: {e}", file=sys.stderr)
                    return uit
                time.sleep(poging * 5)
        uit.extend(body.get("value", []))
        url = body.get("odata.nextLink") or body.get("@odata.nextLink")
        if url:
            time.sleep(0.3)
    return uit


def buurtcodes():
    """De buurten van Nijmegen met hun code, uit de dimensie WijkenEnBuurten."""
    rijen = haal("WijkenEnBuurten")
    if not rijen:
        return {}
    codes = {}
    in_nijmegen = False
    for rij in rijen:
        key = (rij.get("Key") or "").strip()
        titel = (rij.get("Title") or "").strip()
        if key.startswith("GM"):
            in_nijmegen = titel.lower() == GEMEENTE.lower()
            continue
        if key.startswith("BU") and in_nijmegen:
            codes[titel] = key
    return codes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jaren", type=int, default=2)
    ap.add_argument("--uit", default=UIT)
    args = ap.parse_args()

    print("Buurtcodes ophalen", file=sys.stderr)
    codes = buurtcodes()
    if not codes:
        print("Geen buurten gevonden. De opzet van de tabel is mogelijk "
              "gewijzigd; controleer dataderden.cbs.nl/ODataApi/OData/47018NED",
              file=sys.stderr)
        return
    print(f"  {len(codes)} buurten in {GEMEENTE}", file=sys.stderr)

    perioden = haal("Perioden")
    jaren = sorted((p.get("Key") or "").strip() for p in perioden
                   if (p.get("Key") or "").strip())[-args.jaren:]
    print(f"Perioden: {', '.join(jaren)}", file=sys.stderr)

    # Filter opbouwen: onze buurten, onze misdrijfsoorten, deze jaren
    def of_(veld, waarden):
        return "(" + " or ".join(f"{veld} eq '{w}'" for w in waarden) + ")"

    resultaat = {}
    # Per jaar ophalen houdt de verzoeken klein genoeg
    for jaar in jaren:
        filter_ = " and ".join([
            of_("WijkenEnBuurten", codes.values()),
            of_("SoortMisdrijf", SOORTEN.keys()),
            f"Perioden eq '{jaar}'",
        ])
        rijen = haal("TypedDataSet", filter_)
        print(f"  {jaar}: {len(rijen)} regels", file=sys.stderr)
        omgekeerd = {v: k for k, v in codes.items()}
        for rij in rijen:
            buurt = omgekeerd.get((rij.get("WijkenEnBuurten") or "").strip())
            soort = SOORTEN.get(rij.get("SoortMisdrijf") or "")
            aantal = rij.get("GeregistreerdeMisdrijven_1")
            if not buurt or not soort or aantal is None:
                continue
            resultaat.setdefault(buurt, {}).setdefault(jaar.strip(), {})[soort[0]] = aantal
        time.sleep(0.5)

    if not resultaat:
        print("Niets opgehaald. Controleer de veldnamen in TypedDataSet.",
              file=sys.stderr)
        proef = haal("TypedDataSet", f"Perioden eq '{jaren[-1]}'")[:1]
        if proef:
            print(f"  velden in een regel: {sorted(proef[0].keys())}", file=sys.stderr)
        return

    with open(args.uit, "w", encoding="utf-8") as f:
        json.dump(resultaat, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"\nWeggeschreven naar {args.uit}: {len(resultaat)} buurten", file=sys.stderr)

    laatste = jaren[-1].strip()
    print(f"\nWoninginbraken in {laatste}:", file=sys.stderr)
    top = sorted(((b, d.get(laatste, {}).get("woninginbraak", 0))
                  for b, d in resultaat.items()), key=lambda x: -x[1])[:8]
    for buurt, n in top:
        print(f"  {n:>4}  {buurt}", file=sys.stderr)


if __name__ == "__main__":
    main()
