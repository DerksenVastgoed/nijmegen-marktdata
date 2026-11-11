#!/usr/bin/env python3
"""
Loopafstand van een pand tot de dichtstbijzijnde OV-halte.

Waarom niet hemelsbreed: Nijmegen heeft twee barrières waar de rechte lijn
volstrekt misgaat. De spoorlijn snijdt de stad doormidden met een handvol
overgangen, dus een halte op driehonderd meter kan achthonderd meter lopen
zijn. En de stuwwal geeft hoogteverschillen van tientallen meters tussen de
Benedenstad en Galgenveld; een trap telt anders dan vlak lopen.

Daarom in twee stappen. Eerst hemelsbreed de drie dichtstbijzijnde haltes
zoeken, wat gratis is. Dan voor alleen die drie de werkelijke looproute
opvragen. Dat is een bevraging per pand in plaats van per halte.

Gebruik:
  python ov_haltes.py --verversen     # haal het haltebestand op, eens per jaar
  python ov_haltes.py --toon "Pontanusstraat 19"
"""

import argparse
import json
import math
import os
import sys
import time

import requests

HALTES_PAD = "ov_haltes.json"
CACHE_PAD = "ov_afstand_cache.json"

# Het zoekgebied: de ring rond het Keizer Karelplein, met wat marge
BBOX = (51.80, 5.78, 51.88, 5.92)      # zuid, west, noord, oost

# Publieke routeringsdienst. Voetgangersprofiel, want we lopen.
OSRM = "https://router.project-osrm.org/route/v1/foot"

# Overpass levert de haltes uit OpenStreetMap. Geen sleutel nodig.
OVERPASS = "https://overpass-api.de/api/interpreter"

HEADERS = {"User-Agent": "NijmegenVastgoedMonitor/1.0"}

# Hoeveel haltes we echt laten routeren. Drie is genoeg: de dichtstbijzijnde
# hemelsbreed is bijna altijd ook de dichtstbijzijnde te voet, maar bij een
# spoorbarriere kan nummer twee of drie alsnog winnen.
TE_ROUTEREN = 3

# Omwegfactor voor als de routering niet lukt. In stedelijk Nederland ligt de
# werkelijke loopafstand gemiddeld rond 1,35 keer de rechte lijn.
OMWEGFACTOR = 1.35


def hemelsbreed(lat1, lon1, lat2, lon2):
    """Afstand in meters over het aardoppervlak, formule van Haversine."""
    R = 6_371_000
    f1, f2 = math.radians(lat1), math.radians(lat2)
    df = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(df / 2) ** 2
         + math.cos(f1) * math.cos(f2) * math.sin(dl / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def haal_haltes():
    """
    Alle bus-, tram- en treinhaltes in het zoekgebied, uit OpenStreetMap.

    Dit hoeft maar zelden: haltes verplaatsen niet vaak. Het bestand wordt
    bewaard en meegecommit.
    """
    zuid, west, noord, oost = BBOX
    query = f"""
    [out:json][timeout:90];
    (
      node["highway"="bus_stop"]({zuid},{west},{noord},{oost});
      node["railway"="tram_stop"]({zuid},{west},{noord},{oost});
      node["railway"="station"]({zuid},{west},{noord},{oost});
      node["railway"="halt"]({zuid},{west},{noord},{oost});
      node["public_transport"="platform"]["bus"="yes"]({zuid},{west},{noord},{oost});
    );
    out body;
    """

    for poging in range(1, 4):
        try:
            r = requests.post(OVERPASS, data={"data": query},
                              headers=HEADERS, timeout=(20, 180))
            r.raise_for_status()
            data = r.json()
            break
        except Exception as e:
            if poging == 3:
                print(f"Haltes ophalen mislukt: {e}", file=sys.stderr)
                return []
            print(f"  poging {poging} mislukt, opnieuw over {poging * 20}s",
                  file=sys.stderr)
            time.sleep(poging * 20)

    haltes, gezien = [], set()
    for el in data.get("elements", []):
        lat, lon = el.get("lat"), el.get("lon")
        if lat is None or lon is None:
            continue
        tags = el.get("tags", {})
        naam = tags.get("name") or "halte zonder naam"
        soort = ("station" if tags.get("railway") in ("station", "halt")
                 else "tram" if tags.get("railway") == "tram_stop"
                 else "bus")
        # Haltes aan weerszijden van de weg staan dubbel, soms tientallen
        # meters uit elkaar. Op drie decimalen is dat ongeveer honderd meter,
        # en dat maakt voor de looptijd niet uit. Scheelt wel routeringen.
        sleutel = (naam, soort, round(lat, 3), round(lon, 3))
        if sleutel in gezien:
            continue
        gezien.add(sleutel)
        haltes.append({"naam": naam, "soort": soort,
                       "lat": lat, "lon": lon})
    return haltes


def lees_haltes():
    if not os.path.exists(HALTES_PAD):
        return []
    try:
        with open(HALTES_PAD, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _cache():
    try:
        with open(CACHE_PAD, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _bewaar_cache(cache):
    try:
        with open(CACHE_PAD, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
    except Exception:
        pass


def looproute(lat1, lon1, lat2, lon2):
    """
    Werkelijke loopafstand in meters over het wegennet.

    Geeft None als de routering niet lukt; de aanroeper valt dan terug op de
    rechte lijn maal de omwegfactor.
    """
    url = f"{OSRM}/{lon1},{lat1};{lon2},{lat2}?overview=false"
    try:
        r = requests.get(url, headers=HEADERS, timeout=(10, 30))
        if r.status_code != 200:
            return None
        body = r.json()
        routes = body.get("routes") or []
        if not routes:
            return None
        return routes[0].get("distance")
    except Exception:
        return None


def dichtstbijzijnde_halte(lat, lon, haltes=None, routeren=True):
    """
    De dichtstbijzijnde halte te voet, met de afstand in meters.

    Eerst hemelsbreed de kandidaten zoeken, dan alleen die paar laten routeren.
    Het resultaat wordt bewaard, want een pand verhuist niet.
    """
    if lat is None or lon is None:
        return None
    haltes = haltes if haltes is not None else lees_haltes()
    if not haltes:
        return None

    sleutel = f"{lat:.5f},{lon:.5f}"
    cache = _cache()
    if sleutel in cache:
        return cache[sleutel]

    # Kandidaten op rechte lijn, dat kost niets
    kandidaten = sorted(
        ((hemelsbreed(lat, lon, h["lat"], h["lon"]), h) for h in haltes),
        key=lambda x: x[0])[:TE_ROUTEREN]
    if not kandidaten:
        return None

    beste = None
    for recht, halte in kandidaten:
        meters = looproute(lat, lon, halte["lat"], halte["lon"]) if routeren else None
        geschat = meters is None
        if geschat:
            meters = recht * OMWEGFACTOR
        if beste is None or meters < beste["meters"]:
            beste = {"naam": halte["naam"], "soort": halte["soort"],
                     "meters": round(meters), "hemelsbreed": round(recht),
                     "geschat": geschat}
        if routeren:
            time.sleep(0.4)          # de publieke dienst niet overvragen

    # Een omweg van meer dan het dubbele wijst op een barriere, zoals het spoor
    if beste and beste["hemelsbreed"]:
        beste["omweg"] = round(beste["meters"] / beste["hemelsbreed"], 2)

    cache[sleutel] = beste
    _bewaar_cache(cache)
    return beste


def looptijd(meters):
    """Looptijd in minuten bij vijf kilometer per uur."""
    return round(meters / 5000 * 60) if meters else None


def omschrijf(halte):
    """Een leesbare zin bij het resultaat."""
    if not halte:
        return ""
    minuten = looptijd(halte["meters"])
    soort = {"station": "station", "tram": "tramhalte"}.get(halte["soort"], "bushalte")
    zin = (f"{soort} {halte['naam']} op {halte['meters']} m lopen"
           + (f", ongeveer {minuten} minuten" if minuten else ""))
    if halte.get("geschat"):
        zin += " (geschat, routering lukte niet)"
    elif halte.get("omweg", 1) >= 2.0:
        zin += (f". De route is {halte['omweg']}x zo lang als de rechte lijn, "
                f"wat op een barriere wijst zoals het spoor of een hoogteverschil")
    return zin


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verversen", action="store_true",
                    help="haal het haltebestand opnieuw op")
    args = ap.parse_args()

    if args.verversen or not os.path.exists(HALTES_PAD):
        print("Haltes ophalen uit OpenStreetMap", file=sys.stderr)
        haltes = haal_haltes()
        if not haltes:
            print("Niets opgehaald; het haltebestand blijft zoals het was",
                  file=sys.stderr)
            return
        with open(HALTES_PAD, "w", encoding="utf-8") as f:
            json.dump(haltes, f, ensure_ascii=False, indent=1)
        per_soort = {}
        for h in haltes:
            per_soort[h["soort"]] = per_soort.get(h["soort"], 0) + 1
        print(f"  {len(haltes)} haltes bewaard: "
              + ", ".join(f"{n} {s}" for s, n in sorted(per_soort.items())),
              file=sys.stderr)


if __name__ == "__main__":
    main()