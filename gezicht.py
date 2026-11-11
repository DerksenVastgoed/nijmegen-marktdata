#!/usr/bin/env python3
"""
Rijksbeschermde stads- en dorpsgezichten, per pand in de ring.

WAAROM DIT BESTAAT. Tot 17 oktober 2026 stond het beschermd gezicht in de
dossiers per BUURT, als vaste tekst in marktprijzen_bag.BESCHERMD_GEZICHT:
"rijksbeschermd stadsgezicht Benedenstad", "deels de negentiende-eeuwse
schil", en voor Hunnerberg en St. Anna "niet nagekeken". De grenzen van een
gezicht volgen de buurtgrenzen niet, dus "deels" zei bij een pand niets, en
het rustte op een aanname en niet op een meting. Voor een aankoop raakt het
gevelisolatie, kozijnen en zonnepanelen aan de voorzijde.

DE BRON. "Beschermde Gebieden - Cultuurhistorie (INSPIRE geharmoniseerd)"
van de Rijksdienst voor het Cultureel Erfgoed, via PDOK als OGC API
Features, collectie rce_inspire_polygons. Licentie CC BY 4.0. Die collectie
bevat rijksmonumenten en gezichten door elkaar; de gezichten herken je aan
namespace "nlps-stadsendorpsgezichten". Twee voorbehouden:
- Alleen RIJKSbeschermde gezichten. Een gemeentelijk beschermd gezicht staat
  er niet in, dus "niet in deze bron" is nooit "niet beschermd".
- De vlakken staan erin "mits beschikbaar", zegt de bron zelf.

HOE. Eén keer de vlakken in en rond de ring ophalen (geen aanroep per pand),
bewaren in gezichten.json, en dan per pand lokaal toetsen of het punt uit de
voorraad binnen een vlak valt. De verkenning schrijft per buurt hoeveel
panden binnen welk gezicht vallen, zodat te zien is of de Benedenstad er
inderdaad in ligt voordat het dossier hierop leunt.

  python3 gezicht.py --ophalen   # de vlakken en het verslag
  python3 gezicht.py --proef
"""
import argparse
import collections
import datetime as dt
import json
import re
import sys
import time
import urllib.parse
import urllib.request

BASIS = ("https://api.pdok.nl/rce/beschermde-gebieden-cultuurhistorie/ogc/v1/"
         "collections/rce_inspire_polygons/items")
NAAMRUIMTE = "nlps-stadsendorpsgezichten"
UIT_PAD = "gezichten.json"
VERSLAG = "gezicht_verslag.md"
# De ring is 5,837 tot 5,897 oost en 51,817 tot 51,855 noord (voorraad, 17
# oktober). Een marge eromheen, want een gezicht dat de ring raakt kan zijn
# hoekpunten erbuiten hebben.
BBOX = (5.80, 51.80, 5.93, 51.87)
MAX_PAGINAS = 60
BRON = ("Beschermde Gebieden - Cultuurhistorie, RCE via PDOK, CC BY 4.0; "
        "alleen rijksbeschermde gezichten, vlakken mits beschikbaar")


def _vraag(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "NijmegenVastgoedMonitor/1.0",
        "Accept": "application/geo+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _in_bbox(geom, bbox=BBOX):
    """Raakt de omhullende van deze geometrie de bbox? Om te zien of de bron
    de bbox-parameter respecteert, want een proefvraag op 17 oktober gaf
    monumenten uit heel Nederland terug."""
    xs, ys = [], []
    for ring in _ringen(geom):
        for x, y in ring:
            xs.append(x)
            ys.append(y)
    if not xs:
        return False
    return not (max(xs) < bbox[0] or min(xs) > bbox[2]
                or max(ys) < bbox[1] or min(ys) > bbox[3])


def _ringen(geom):
    if not geom:
        return
    soort, c = geom.get("type"), geom.get("coordinates") or []
    if soort == "Polygon":
        yield from c
    elif soort == "MultiPolygon":
        for poly in c:
            yield from poly


def _in_ring(x, y, ring):
    """Ray casting: ligt (x, y) binnen deze ring?"""
    binnen = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > y) != (y2 > y):
            xs = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xs:
                binnen = not binnen
    return binnen


def in_vlak(lon, lat, geom):
    """Ligt het punt in het vlak, met gaten als gaten?"""
    if not geom:
        return False
    if geom.get("type") == "Polygon":
        polys = [geom.get("coordinates") or []]
    elif geom.get("type") == "MultiPolygon":
        polys = geom.get("coordinates") or []
    else:
        return False
    for poly in polys:
        if poly and _in_ring(lon, lat, poly[0]) and not any(
                _in_ring(lon, lat, gat) for gat in poly[1:]):
            return True
    return False


def ophalen():
    params = {"f": "json", "limit": "1000",
              "bbox": ",".join(str(v) for v in BBOX)}
    url = BASIS + "?" + urllib.parse.urlencode(params)
    gezichten, totaal, buiten, paginas = [], 0, 0, 0
    namen = collections.Counter()
    while url and paginas < MAX_PAGINAS:
        d = _vraag(url)
        paginas += 1
        for f in d.get("features") or []:
            totaal += 1
            p = f.get("properties") or {}
            namen[p.get("namespace")] += 1
            if not _in_bbox(f.get("geometry")):
                buiten += 1
                continue
            if p.get("namespace") != NAAMRUIMTE:
                continue
            gezichten.append({
                "id": f.get("id"), "naam": p.get("text"),
                "aangewezen": p.get("legalfoundationdate"),
                "bron": p.get("ci_citation"),
                "geometry": f.get("geometry")})
        url = next((l.get("href") for l in d.get("links") or []
                    if l.get("rel") == "next"), None)
        time.sleep(0.2)
    uit = {"bron": BRON, "bijgewerkt": dt.date.today().isoformat(),
           "volledig": url is None, "gezichten": gezichten,
           "meting": {"objecten": totaal, "buiten_bbox": buiten,
                      "paginas": paginas,
                      "naamruimtes": dict(namen)}}
    with open(UIT_PAD, "w", encoding="utf-8") as f:
        json.dump(uit, f, ensure_ascii=False)
    print(f"Gezichten: {len(gezichten)} in de bbox, van {totaal} objecten op "
          f"{paginas} pagina's; {buiten} buiten de bbox; "
          f"{'volledig' if url is None else 'NIET VOLLEDIG, paginaplafond'}",
          file=sys.stderr)
    return uit


def per_pand(gezichten, punten):
    """pand-id -> lijst van gezichtsnamen waarin het punt ligt."""
    uit = {}
    for pid, pt in punten.items():
        uit[pid] = [g.get("naam") or g.get("id") for g in gezichten
                    if in_vlak(pt["lon"], pt["lat"], g.get("geometry"))]
    return uit


def verslag(uit):
    import bestemming
    with open("voorraad.json", encoding="utf-8") as f:
        v = json.load(f)
    buurt = {}
    for r in (v.get("adressen") or {}).values():
        if r.get("herkomst") == "focusbuurt" and r.get("pand"):
            bb = r.get("buurten")
            buurt.setdefault(r["pand"], bb[0] if isinstance(bb, list) and bb
                             else bb)
    punten = bestemming.punten_per_pand()
    pp = per_pand(uit["gezichten"], punten)
    tel = collections.defaultdict(collections.Counter)
    for pid, namen in pp.items():
        b = buurt.get(pid) or "?"
        tel[b]["panden"] += 1
        for n in namen:
            tel[b][n] += 1
    r = ["# Verkenning rijksbeschermde gezichten", "",
         f"Op {uit['bijgewerkt']}, bron: {BRON}.", "",
         f"Meting: {json.dumps(uit['meting'], ensure_ascii=False)}", "",
         "## Gezichten in de bbox", ""]
    for g in uit["gezichten"]:
        r.append(f"- {g.get('naam')} (aangewezen {g.get('aangewezen')}, "
                 f"{g.get('bron')})")
    if not uit["gezichten"]:
        r.append("- geen")
    r += ["", "## Panden per buurt binnen een gezicht", ""]
    for b in sorted(tel):
        rest = {k: n for k, n in tel[b].items() if k != "panden"}
        r.append(f"- {b}: {tel[b]['panden']} panden; "
                 + (", ".join(f"{k} {n}" for k, n in sorted(rest.items()))
                    or "in geen enkel gezicht"))
    with open(VERSLAG, "w", encoding="utf-8") as f:
        f.write("\n".join(r) + "\n")
    print("\n".join(r))


# WGS84 NAAR RIJKSDRIEHOEK. De benadering van Schreutelkamp en Strang van
# Hees, nauwkeurig tot ongeveer een meter in Nederland. Nodig omdat de
# GIO's van het omgevingsplan in RD staan en de punten in de voorraad in
# WGS84. Proef op het nulpunt van RD, de Onze Lieve Vrouwetoren in
# Amersfoort.
_R = [(0, 1, 190094.945), (1, 1, -11832.228), (2, 1, -114.221),
      (0, 3, -32.391), (1, 0, -0.705), (3, 1, -2.340), (1, 3, -0.608),
      (0, 2, -0.008), (2, 3, 0.148)]
_S = [(1, 0, 309056.544), (0, 2, 3638.893), (2, 0, 73.077),
      (1, 2, -157.984), (3, 0, 59.788), (0, 1, 0.433), (2, 2, -6.439),
      (1, 1, -0.032), (0, 4, 0.092), (1, 4, -0.054)]


def wgs84_naar_rd(lat, lon):
    dp = 0.36 * (lat - 52.15517440)
    dl = 0.36 * (lon - 5.38720621)
    x = 155000 + sum(c * dp ** p * dl ** q for p, q, c in _R)
    y = 463000 + sum(c * dp ** p * dl ** q for p, q, c in _S)
    return x, y


STADSBEELD_SINDS = "4 september 2026"
STADSBEELD_BRON = ("Voorbeschermingsregels stadsbeeld Wederopbouwcentrum, "
                   "CVDR766239, GIO dc-2026-27212 en dc-2026-27213")
_cache = {}


# HET ERFGOEDREGISTER VAN DE GEMEENTE. Gevonden op 18 oktober 2026 via de
# KaartViewer (kaartviewer.py, monumenten.py --wfs): extern_Monumenten op de
# GeoServer van de gemeente, met 2.781 objecten (rijksmonumenten, gemeentelijke
# monumenten, stadsbeeldobjecten, panden in procedure, aandachtspanden) en 10
# beschermde gebieden (8 gemeentelijke stadsbeelden, 2 rijksgezichten). In RD.
REGISTER = "monumenten_his_mon_monument.geojson"
REGISTER_GEBIEDEN = "monumenten_his_mon_beschermde_geb.geojson"
REGISTER_BRON = ("erfgoedregister gemeente Nijmegen, GeoServer "
                 "extern_Monumenten")


def _register(pad):
    """[(eigenschappen, polygoon, omhullende)] uit een GeoJSON in RD, en de
    datum van bijwerken. (None, None) als het bestand er niet is: dat is
    niet nagekeken, geen leeg register."""
    try:
        with open(pad, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None, None
    uit, datum = [], None
    for ft in d.get("features") or []:
        g = ft.get("geometry") or {}
        props = ft.get("properties") or {}
        datum = datum or props.get("DD_BIJGEWERKT")
        if g.get("type") == "Polygon":
            polys = [g]
        elif g.get("type") == "MultiPolygon":
            polys = [{"type": "Polygon", "coordinates": c}
                     for c in g.get("coordinates") or []]
        else:
            continue
        for poly in polys:
            ring = (poly["coordinates"] or [[]])[0]
            if not ring:
                continue
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            uit.append((props, poly, (min(xs), min(ys), max(xs), max(ys))))
    return uit, datum


def _raak(register, x, y):
    return [props for props, poly, (a, b, c, d) in register
            if a <= x <= c and b <= y <= d and in_vlak(x, y, poly)]


def _laad():
    if "geladen" in _cache:
        return _cache
    import bestemming
    import stadsbeeld
    _cache["punten"] = bestemming.punten_per_pand()
    try:
        with open(UIT_PAD, encoding="utf-8") as f:
            _cache["gezichten"] = json.load(f).get("gezichten")
    except (OSError, ValueError):
        _cache["gezichten"] = None
    _cache["register"], _cache["register_datum"] = _register(REGISTER)
    _cache["gem_gebieden"], _ = _register(REGISTER_GEBIEDEN)
    _cache["gebied"] = stadsbeeld.vlakken(stadsbeeld.WERKINGSGEBIED)
    _cache["objecten"] = stadsbeeld.vlakken(stadsbeeld.OBJECTEN)
    _cache["geladen"] = True
    return _cache


def bescherming(pand_id):
    """
    Wat er aan erfgoedbescherming op het punt van dit pand ligt.

    Geeft None als het pand niet in de ring ligt (dan is er niets gemeten),
    anders een dict met:
      rijks: lijst gezichtsnamen, of None als gezichten.json ontbreekt
      stadsbeeld: "object", "gebied", "" (gemeten, erbuiten) of None
                  (niet gemeten)
    """
    c = _laad()
    pt = c["punten"].get(str(pand_id or ""))
    if not pt:
        return None
    rijks = None
    if c["gezichten"] is not None:
        rijks = [g.get("naam") or g.get("id") for g in c["gezichten"]
                 if in_vlak(pt["lon"], pt["lat"], g.get("geometry"))]
    x, y = wgs84_naar_rd(pt["lat"], pt["lon"])
    register = (None if c.get("register") is None
                else _raak(c["register"], x, y))
    gem_stadsbeeld = None
    if c.get("gem_gebieden") is not None:
        gem_stadsbeeld = any(
            (p.get("SOORT") or "").startswith("gembeschermd")
            for p in _raak(c["gem_gebieden"], x, y))
    stadsbeeld = None
    if c["gebied"] is not None and c["objecten"] is not None:
        if any(in_vlak(x, y, v) for v in c["objecten"]):
            stadsbeeld = "object"
        elif any(in_vlak(x, y, v) for v in c["gebied"]):
            stadsbeeld = "gebied"
        else:
            stadsbeeld = ""
    return {"rijks": rijks, "stadsbeeld": stadsbeeld, "register": register,
            "gem_stadsbeeld": gem_stadsbeeld}


RCE_PANDEN = "rijksmonumenten_rce_panden.json"


def _rce_per_pand():
    """pand-id -> [(nummer, naam)] uit de koppeling RCE-punt naar BAG-pand
    (monumenten.py --rce-panden), of None als die er niet is."""
    if "rce_per_pand" in _cache:
        return _cache["rce_per_pand"]
    try:
        with open(RCE_PANDEN, encoding="utf-8") as f:
            nummers = json.load(f).get("nummers") or {}
    except (OSError, ValueError):
        _cache["rce_per_pand"] = None
        return None
    uit = {}
    for n, v in nummers.items():
        for p in v.get("panden") or []:
            uit.setdefault(p, []).append(
                (n, v.get("naam"), "archaeological" in (v.get("klasse") or "")))
    _cache["rce_per_pand"] = uit
    return uit


REGISTER_PANDEN = "monumenten_register_panden.json"
OVERLAP_DREMPEL = 0.3


def _register_per_pand(soort="Rijksmonument"):
    """pand-id -> [(ID, aandeel_pand)] voor de vlakken van deze soort
    in het register, of None als de meting er niet is.

    WAAROM. 19 oktober 2026. Met een punt per pand viel St. Anthoniusplaats 16
    buiten het vlak van 31169 ("St. Anthoniusplaats 15-16"), terwijl het
    rijksmonumentenregister (via monumenten.nl, op Marks aanwijzing) 15 en 16
    als adressen noemt. Gemeten tegen de pandomtrek: pand 16 ligt voor 0,913
    in het vlak, pand 17 voor 0,006.

    DE DREMPEL, UIT DE METING. Per pand de som van aandeel_pand over alle
    rijksmonumentvlakken (een pand kan meer monumenten dragen: Ganzenheuvel 5
    ligt in vier vlakken van elk 0,22 tot 0,32). Van de 288 panden: 23 onder
    0,3, waarvan de hoogste 0,215 (Oostkanaaldijk 382, een groot pand waar
    het vlak een hoek van beslaat); geen enkel pand tussen 0,215 en 0,453; de
    laagste daarboven zijn Sterreschansweg 77 (0,453) en Lage Markt 47B
    (0,48), beide het pand uit de titel van het register. De drempel staat in
    het gat. Wat eronder valt, is een buurpand dat een rand van het vlak
    raakt, of een groot pand met een klein monument erin (Burchtstraat 20,
    0,11; Professor Cornelissenstraat 2, de poortjes, 0,012)."""
    sleutel = "register_per_pand" + ("" if soort == "Rijksmonument"
                                     else ":" + soort)
    if sleutel in _cache:
        return _cache[sleutel]
    try:
        with open(REGISTER_PANDEN, encoding="utf-8") as f:
            inhoud = json.load(f)
        objecten = inhoud.get("objecten") or {}
    except (OSError, ValueError):
        _cache[sleutel] = None
        return None
    # Een meting op OBJECTID (voor 19 oktober) is niet te koppelen: die
    # sleutel is niet uniek. Dan niet gemeten, en beslist het pandpunt.
    if inhoud.get("sleutel") != "ID":
        _cache[sleutel] = None
        return None
    # Voor 19 oktober stonden er alleen rijksmonumenten in, zonder "soort".
    if soort != "Rijksmonument" and not any(
            v.get("soort") == soort for v in objecten.values()):
        _cache[sleutel] = None
        return None
    uit = {}
    for o, v in objecten.items():
        if (v.get("soort") or "Rijksmonument") != soort:
            continue
        for x in v.get("panden") or []:
            uit.setdefault(x["pand"], []).append((o, x["aandeel_pand"]))
    _cache[sleutel] = uit
    return uit


# GEEN GAT BIJ GEMEENTELIJKE MONUMENTEN. 19 oktober 2026, 590 vlakken en 862
# panden. Bij de rijksmonumenten lag er een gat in de verdeling (geen pand
# tussen 0,215 en 0,453); hier niet: tussen 0,1 en 0,5 liggen 58 panden, en
# daaronder staan panden waarvan het adres in de titel van het register staat
# (Postweg 54, 0,257; Begijnenstraat 36, 0,29) naast panden met een ander
# adres (Karrengas 70 bij Molenstraat 66, 0,483). Een drempel daarin zou
# gekozen zijn, niet gemeten. Dus: vanaf de helft van het pand telt het als
# gemeentelijk monument (dan ligt het grootste deel erin), en tussen GEM_TWIJFEL
# en de helft noemt het dossier het aandeel zonder opslag te rekenen. Onder
# 0,05 lagen bij de rijksmonumenten alleen buurpanden die een rand raken.
GEM_DREMPEL = 0.5
GEM_TWIJFEL = 0.05


def gemeentelijk_aandeel(pand_id):
    """De som van aandeel_pand over de gemeentelijke monumentvlakken, of None
    als die niet gemeten is."""
    per_pand = _register_per_pand("Gemeentelijk monument")
    if per_pand is None or str(pand_id or "") not in per_pand:
        return None
    return round(sum(a for _o, a in per_pand[str(pand_id or "")]), 3)


def _huisnummer(tekst):
    """(nummer, letter, toevoeging) uit "12A2", "12 A 3" of "15"; toevoeging
    als getal waar dat kan, zodat 12A3 na 12A2 komt."""
    m = re.match(r"\s*(\d+)\s*([A-Za-z]?)\s*(\d*)\s*$", tekst or "")
    if not m:
        return None
    return (int(m.group(1)), m.group(2).upper(),
            int(m.group(3)) if m.group(3) else -1)


def titel_noemt(titel, adres):
    """Noemt de titel van het register dit adres? "Houtstraat 10-12A2,
    Houthof 51-53" noemt Houtstraat 12A1 wel en 12A3 niet; een reeks mag
    aflopen ("10-8"). Een straat zonder naam in een deel van de titel hoort
    bij de straat ervoor. Leest alleen een titel; geen bron voor de
    aanwijzing zelf."""
    m = re.match(r"(.*?)\s+(\d.*)$", (adres or "").strip())
    if not m:
        return False
    straat, nr = m.group(1).lower(), _huisnummer(m.group(2))
    if not nr:
        return False
    vorige = None
    for deel in (titel or "").split(","):
        t = re.match(r"\s*(.*?)\s*(\d+\s*[A-Za-z]?\s*\d*)"
                     r"(?:\s*-\s*(\d+\s*[A-Za-z]?\s*\d*))?\s*$", deel)
        if not t:
            continue
        naam = t.group(1).strip().lower() or vorige
        vorige = naam
        a = _huisnummer(t.group(2))
        b = _huisnummer(t.group(3)) if t.group(3) else a
        if not (a and b) or naam != straat:
            continue
        lo, hi = min(a, b), max(a, b)
        # Een eindpunt zonder letter staat voor het hele nummer.
        if hi[1] == "" and hi[2] == -1:
            hi = (hi[0], "~", 10 ** 6)
        if lo <= nr <= hi:
            return True
    return False


def vbo_in_gemeentelijk_monument(vbo_id):
    """Ligt deze woning in het monumentdeel van een pand dat maar deels in
    een gemeentelijk monumentvlak ligt? "binnen", "buiten", "twijfel" of
    None (niet gemeten).

    TWEE BRONNEN, EN ALLEEN SAMEN EEN UITKOMST. 19 oktober 2026, de 28
    deels-panden in de ring, 176 verblijfsobjecten. Het punt van het
    verblijfsobject (BAG, in RD) tegen het vlak, en of de titel van het
    register het adres noemt: 157 keer eens, 19 keer oneens. Oneens is
    bijvoorbeeld Stockumstraat 10 (de titel noemt het, het punt ligt buiten
    het vlak) en Karrengas 44B tot 54A (punt in het vlak van "Molenstraat
    94", de titel noemt alleen dat adres). Geen van beide is de aanwijzing
    zelf; zijn ze het oneens, dan "twijfel" en geen opslag."""
    if "vbo_gem" not in _cache:
        kaart = None
        try:
            with open(REGISTER_PANDEN, encoding="utf-8") as f:
                inhoud = json.load(f)
            if inhoud.get("sleutel") == "ID":
                kaart = {}
                for v in (inhoud.get("objecten") or {}).values():
                    if v.get("soort") != "Gemeentelijk monument":
                        continue
                    for x in v.get("panden") or []:
                        for b in x.get("vbo") or []:
                            oordeel = (bool(b.get("in_vlak")),
                                       titel_noemt(v.get("titel"),
                                                   b.get("adres")))
                            kaart.setdefault(b["vbo"], []).append(oordeel)
        except (OSError, ValueError):
            kaart = None
        _cache["vbo_gem"] = kaart
    kaart = _cache["vbo_gem"]
    if not kaart or not vbo_id or str(vbo_id) not in kaart:
        return None
    oordelen = kaart[str(vbo_id)]
    if any(a and b for a, b in oordelen):
        return "binnen"
    if all(not a and not b for a, b in oordelen):
        return "buiten"
    return "twijfel"


def gemeentelijk_monument(pand_id):
    """De vermeldingen "Gemeentelijk monument" uit het register die bij dit
    pand horen: per pandomtrek als die gemeten is, anders per pandpunt.
    "In procedure" (voorbescherming) telt niet: art. 8a lid 3 vraagt een
    aangewezen monument."""
    per_pand = _register_per_pand("Gemeentelijk monument")
    # ONBEKEND PAND IS NIET GEMETEN. Bij Molenstraat 55, Berg en Dalseweg 200
    # en van Berchenstraat 31 en 33 ligt het pandpunt in het vlak, maar
    # gaf de BAG voor dat vlak een ander pand-id terug dan de voorraad heeft
    # (Molenstraat 55: voorraad ...3577, BAG ...4125 voor 1,0). Een pand dat
    # in de meting niet voorkomt is niet gemeten, niet "nul"; dan beslist het
    # pandpunt, zoals voorheen. Een buurpand dat een rand raakt staat wel in
    # de meting, met zijn kleine aandeel.
    if per_pand is not None and str(pand_id or "") in per_pand:
        objs = per_pand.get(str(pand_id or "")) or []
        if sum(a for _o, a in objs) < GEM_DREMPEL:
            return []
        op_id = {str(t[0].get("ID")): t[0]
                 for t in (_laad().get("register") or [])}
        return [op_id[o] for o, _a in sorted(objs, key=lambda t: -t[1])
                if o in op_id]
    try:
        reg = (bescherming(pand_id) or {}).get("register") or []
    except Exception:
        return []
    return [p for p in reg if p.get("BESCHERMINGS_OMS") ==
            "Gemeentelijk monument"]


def monument_soort(pand_id, bouwjaar=None, rijks=None):
    """De soort voor de huuropslag van art. 8a Besluit huurprijzen
    woonruimte: "rijks", "gemeentelijk", "gezicht" of None.

    rijks: de uitkomst van monument_aanvullen, als de aanroeper die al heeft.
    "gezicht" vraagt een rijksbeschermd stadsgezicht EN een bouwjaar voor
    1965 (lid 5). Is het bouwjaar onbekend, dan geen opslag: het model neemt
    dan het lagere maximum, en zegt niet dat het pand ervoor in aanmerking
    komt zonder het te weten."""
    if rijks is None:
        rijks = bool(monument_aanvullen(pand_id))
    if rijks:
        return "rijks"
    if gemeentelijk_monument(pand_id):
        return "gemeentelijk"
    try:
        bs = bescherming(pand_id) or {}
    except Exception:
        bs = {}
    try:
        oud = bouwjaar is not None and int(bouwjaar) < 1965
    except (TypeError, ValueError):
        oud = False
    if bs.get("rijks") and oud:
        return "gezicht"
    return None


def _register_nummers():
    """Alle rijksmonumentnummers die het erfgoedregister ergens als vlak
    heeft, ongeacht in welk pand."""
    if "register_nummers" not in _cache:
        _cache["register_nummers"] = {
            n for t in (_laad().get("register") or [])
            for n in re.findall(r"\d{4,6}",
                                str((t[0] if isinstance(t, tuple) else t)
                                    .get("RIJKSOBJECTCODE") or ""))}
    return _cache["register_nummers"]


def archeologisch_rijksmonument(pand_id):
    """De archeologische rijksmonumenten waarvan het RCE-punt in dit pand
    ligt, als [(nummer, naam)]."""
    return [(n, naam) for n, naam, *arch in
            ((_rce_per_pand() or {}).get(str(pand_id or "")) or [])
            if arch and arch[0]]


def monument_aanvullen(pand_id):
    """
    Of een pand een rijksmonument is, uit de RCE en het erfgoedregister. Geeft
    een dict (adres, functie, nummer, bron, eventueel tegenspraak) of None.

    RIJKSMONUMENT UIT TWEE BRONNEN, EEN UITKOMST. 18 oktober 2026.
    - De RCE: de 261 rijksmonumenten van Nijmegen als punt (PDOK), per punt
      gekoppeld aan het BAG-pand waarvan de omtrek het punt bevat
      (monumenten.py --rce-panden). Getoetst tegen het register: van de 90
      gevallen waarin beide een pand noemen, 86 hetzelfde pand.
    - Het erfgoedregister van de gemeente, per geometrie (195 van de 261).
    Rijksmonument als een van de twee het zegt, met de bron erbij; een
    tegenspraak wordt genoemd in plaats van opgelost.

    NIET MEER HET RCE-BESTAND PER ADRES. Dat (rijksmonumenten.py) kende 76 van
    de 261, en koppelde op adres. Twee van de drie tegenspraken uit #166
    bleken daar vandaan te komen: Hoogstraat 3 kreeg het Spoorwegmonument
    (523055) en St. Jorisstraat 35 het beeld van Petrus Canisius (523056),
    twee monumenten die op een adres staan maar geen gebouw zijn. Die panden
    telden daardoor als rijksmonument in de huurpunten.
    """
    alle = (_rce_per_pand() or {}).get(str(pand_id or "")) or []
    # ARCHEOLOGIE IS HET TERREIN, NIET HET GEBOUW. Van de 261 RCE-punten zijn
    # er 8 een archeologisch rijksmonument (klasse "cultural; archaeological",
    # aanduiding b673c8c1), de andere 253 een gebouwd monument. Flavus 43 lag
    # op zo'n terrein en kreeg daardoor de vlag van een rijksmonument, ook in
    # de huurpunten. Een archeologisch rijksmonument geldt voor wie graaft en
    # niet voor de gevel, dus het telt hier niet en staat apart in het dossier.
    rce = [(n, naam) for n, naam, *arch in alle if not (arch and arch[0])]
    # HET VLAK GAAT VOOR HET PUNT. 19 oktober 2026. De RCE geeft een punt, het
    # register een vlak. Van de 8 panden die alleen via het RCE-punt
    # rijksmonument waren, droegen 7 een nummer dat het register zelf op een
    # ander pand legt: het transformatorhuisje Waldeck Pyrmontsingel 1A
    # (522985) kwam op nummer 7 en 13 terecht, De Tempelier Molenstraat 93-97
    # (523036) op 99B, Grote Markt 19 (31130) op St. Stevenskerkhof 1B. Vier
    # daarvan waren de tegenspraken in het dossier, en alle zeven telden als
    # rijksmonument in de huurpunten. Kent het register het nummer, dan zegt
    # het register welk pand het is; het RCE-punt telt alleen voor nummers
    # die het register niet heeft.
    # Voor de bron telt het punt wel: ligt het in een pand dat het register
    # ook rijksmonument noemt, dan zeggen beide bronnen het.
    rce_punt = rce
    bekend = _register_nummers()
    rce = [(n, naam) for n, naam in rce if n not in bekend]
    try:
        bs = bescherming(pand_id)
    except Exception:
        bs = None
    reg = None if not bs else bs.get("register")
    rijks = [p for p in (reg or []) if p.get("BESCHERMINGS_OMS") ==
             "Rijksmonument"]
    # DE PANDOMTREK GAAT VOOR HET PANDPUNT. Is de overlap van BAG-pand en
    # registervlak gemeten (monumenten.py --register-panden), dan beslist die.
    # Zie _register_per_pand voor de drempel en waar hij vandaan komt.
    per_pand = _register_per_pand()
    if per_pand is not None and str(pand_id or "") in per_pand:
        objs = per_pand.get(str(pand_id or "")) or []
        if sum(a for _o, a in objs) >= OVERLAP_DREMPEL:
            op_id = {str(t[0].get("ID")): t[0]
                     for t in (_laad().get("register") or [])}
            rijks = [op_id[o] for o, _a in sorted(objs, key=lambda t: -t[1])
                     if o in op_id]
        else:
            rijks = []
    if not rce and not rijks:
        return None
    if rijks:
        p = rijks[0]
        code = (re.findall(r"\d{4,6}", str(p.get("RIJKSOBJECTCODE") or ""))
                or [None])[0]
        mon = {"adres": p.get("TITEL"), "functie": p.get("OBJECTNAAM") or "",
               "nummer": code, "bron": "erfgoedregister gemeente"}
    else:
        mon = {"adres": None, "functie": rce[0][1] or "", "nummer": rce[0][0],
               "bron": "RCE"}
    if rce_punt and rijks:
        mon["bron"] = "RCE en erfgoedregister gemeente"
    elif rce and reg:
        ander = sorted({p.get("BESCHERMINGS_OMS") for p in reg
                        if p.get("BESCHERMINGS_OMS")})
        mon["tegenspraak"] = (
            "het erfgoedregister van de gemeente noemt dit "
            + ", ".join(a.lower() for a in ander)
            + "; de RCE een rijksmonument")
    if mon.get("nummer"):
        mon["nummer"] = (f"https://monumentenregister.cultureelerfgoed.nl/"
                         f"monumenten/{mon['nummer']}")
    if rce and not rijks:
        mon["bron"] += " (punt in de pandomtrek van de BAG)"
    return mon


# Wat een vermelding in het register betekent. Nagelezen in de
# Erfgoedverordening Nijmegen (CVDR731607): art. 14 voor het gemeentelijk
# monument, art. 19 voor een stadsbeeldobject (19 oktober 2026, de tekst
# staat in stadsbeeld_regels.md, stadsbeeld.py --regels).
# STADSBEELDOBJECT: NIET ALLEEN DE BUITENKANT. Tot 19 oktober stond hier
# "wijzigingen aan de buitenkant zijn vergunningplichtig". Art. 19 lid 1
# verbiedt zonder vergunning stadsbeeldobjecten "in enig opzicht te
# wijzigen", en lid 2 zondert alleen normaal onderhoud uit; een uitzondering
# voor inpandige wijzigingen, zoals art. 14 die bij het gemeentelijk
# monument wel kent, staat er niet. De toelichting bij art. 18 zegt zelf dat
# de gemeentelijke bescherming "verder reikt dan de rijks bescherming". Het
# aanwijzingsbesluit per stadsbeeld kan dit nog invullen; dat is niet
# nagelezen. Het omgevingsplan (CVDR696550) noemt het woord stadsbeeld
# nergens: 0 keer in 1.324 artikelen.
BETEKENIS = {
    "Rijksmonument": "elke wijziging, ook binnen, vraagt een omgevingsvergunning "
                     "voor een rijksmonumentenactiviteit",
    "Gemeentelijk monument": "slopen, verstoren, verplaatsen of in enig "
                             "opzicht wijzigen is vergunningplichtig; normaal "
                             "onderhoud zonder wijziging van detaillering, "
                             "vormgeving, materiaal of kleur en inpandige "
                             "wijzigingen zonder monumentale waarde niet "
                             "(Erfgoedverordening Nijmegen art. 14)",
    "Stadsbeeldobject": "afbreken, verstoren, verplaatsen of in enig opzicht "
                        "wijzigen is vergunningplichtig, ook de erfafscheiding "
                        "en erfinrichting; alleen normaal onderhoud zonder "
                        "wijziging van detaillering, profilering, vormgeving, "
                        "materiaal en kleur niet. Een uitzondering voor "
                        "inpandige wijzigingen kent dit artikel niet "
                        "(Erfgoedverordening Nijmegen art. 19); het "
                        "aanwijzingsbesluit van het stadsbeeld is niet "
                        "nagelezen",
    "In procedure": "voorbescherming: tijdens de procedure gelden de regels "
                    "al",
    "Aandachtspand": "door de gemeente als waardevol aangemerkt, maar niet "
                     "beschermd",
}


def _registerregels(b, datum):
    if b.get("register") is None:
        return [("erfgoedregister gemeente", "niet nagekeken", REGISTER_BRON)]
    uit, gezien = [], set()
    for p in b["register"]:
        soort = p.get("BESCHERMINGS_OMS") or "onbekende vermelding"
        sleutel = (soort, p.get("TITEL"))
        if sleutel in gezien:
            continue
        gezien.add(sleutel)
        status = p.get("STATUS_OMS") or "status niet ingevuld in het register"
        wat = ", ".join(x for x in (p.get("TITEL"), p.get("OBJECTNAAM"))
                        if x and x.strip().lower() != "zonder titel")
        tekst = (f"{soort} ({status}"
                 + (f", sinds {p['STATUS_DATUM']}" if p.get("STATUS_DATUM")
                    else "") + ")"
                 + (f": {wat}" if wat else "")
                 + (f", in {p['GEZICHTNAAM']}" if p.get("GEZICHTNAAM")
                    else ""))
        if BETEKENIS.get(soort):
            tekst += f". {BETEKENIS[soort][0].upper()}{BETEKENIS[soort][1:]}"
        uit.append(("erfgoedregister gemeente", tekst,
                    f"{REGISTER_BRON}, bijgewerkt {datum}"))
    if not uit:
        uit.append(("erfgoedregister gemeente",
                    "geen object in het register op dit punt"
                    + ("; het pand ligt wel in een gemeentelijk beschermd "
                       "stadsbeeld" if b.get("gem_stadsbeeld") else ""),
                    f"{REGISTER_BRON}, bijgewerkt {datum}"))
    elif b.get("gem_stadsbeeld") and not any(
            p.get("BESCHERMINGS_OMS") == "Stadsbeeldobject"
            for p in b["register"]):
        uit.append(("erfgoedregister gemeente",
                    "ligt in een gemeentelijk beschermd stadsbeeld",
                    f"{REGISTER_BRON}, bijgewerkt {datum}"))
    return uit


# De dubbelbestemming die bij een rijksgezicht hoort. AFGELEID, niet uit de
# planregels: gemeten op 17 oktober per buurt, en de tellingen vielen op twee
# panden na samen (Benedenstad 634 tegen 634, Galgenveld 465 tegen 465,
# Altrade 438 tegen 438, Bottendaal 353 tegen 353, Hunnerberg 159 tegen 159).
# De planregels zelf waren niet automatisch op te halen.
BIJ_GEZICHT = {"Nijmegen": "Cultuurhistorie 1",
               "Nijmegen - De 19de-eeuwse Stadsuitleg": "Cultuurhistorie 2"}


def dossierregels(pand_id):
    """[(onderwerp, tekst, bron)] voor het dossier van een pand."""
    b = bescherming(pand_id)
    if b is None:
        return [("beschermd gezicht", "niet nagekeken: dit pand ligt niet in "
                 "de ring, of de voorraad kent er geen punt van", "eigen meting")]
    uit = []
    if b["rijks"] is None:
        uit.append(("rijksbeschermd gezicht", "niet nagekeken", BRON))
    elif b["rijks"]:
        namen = ", ".join(b["rijks"])
        dub = [BIJ_GEZICHT[n] for n in b["rijks"] if n in BIJ_GEZICHT]
        uit.append(("rijksbeschermd gezicht",
                    f"{namen}: wijzigingen aan het uiterlijk zijn "
                    f"vergunningplichtig, wat gevelisolatie, kozijnen en "
                    f"zonnepanelen aan de voorzijde raakt"
                    + (f". In het bestemmingsplan hoort hier vermoedelijk de "
                       f"dubbelbestemming {', '.join(dub)} bij (afgeleid uit "
                       f"de overlap per buurt, niet uit de planregels)"
                       if dub else ""), BRON))
    else:
        uit.append(("rijksbeschermd gezicht", "geen op dit punt", BRON))
    uit += _registerregels(b, _laad().get("register_datum"))
    for n, naam in archeologisch_rijksmonument(pand_id):
        uit.append(("archeologisch rijksmonument",
                    f"het pand ligt op archeologisch rijksmonument {n}"
                    + (f" ({naam})" if naam else "")
                    + ": graven en bouwen in de bodem vraagt een vergunning; "
                      "het gebouw zelf is daardoor geen rijksmonument",
                    "RCE via PDOK, punt in de pandomtrek van de BAG"))
    if b["stadsbeeld"] == "object":
        uit.append(("gemeentelijk voorbeschermd stadsbeeld",
                    f"dit is een voorbeschermd stadsbeeldobject in het "
                    f"Wederopbouwcentrum, sinds {STADSBEELD_SINDS}: sloop van "
                    f"delen aan de openbare ruimte en het wijzigen van gevels "
                    f"en dakvlakken naar openbaar gebied zijn "
                    f"vergunningplichtig; normaal onderhoud zonder wijziging "
                    f"van detaillering, materiaal en kleur niet",
                    STADSBEELD_BRON))
    elif b["stadsbeeld"] == "gebied":
        uit.append(("gemeentelijk voorbeschermd stadsbeeld",
                    f"ligt in het voorbeschermd stadsbeeld Wederopbouwcentrum, "
                    f"sinds {STADSBEELD_SINDS}, maar het gebouw is zelf geen "
                    f"stadsbeeldobject: wijzigingen aan gevels en dakvlakken "
                    f"naar openbaar gebied kunnen vergunningplichtig zijn, "
                    f"nakijken in het omgevingsplan", STADSBEELD_BRON))
    elif b["stadsbeeld"] is None:
        uit.append(("gemeentelijk voorbeschermd stadsbeeld", "niet nagekeken",
                    STADSBEELD_BRON))
    return uit


def proef():
    afw = []
    vierkant = {"type": "Polygon", "coordinates": [
        [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
        [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]]}
    if not in_vlak(2, 2, vierkant):
        afw.append("een punt binnen het vlak valt erbuiten")
    if in_vlak(5, 5, vierkant):
        afw.append("een punt in het gat telt als binnen")
    if in_vlak(12, 5, vierkant):
        afw.append("een punt buiten het vlak telt als binnen")
    multi = {"type": "MultiPolygon", "coordinates": [
        [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
        [[[20, 20], [21, 20], [21, 21], [20, 21], [20, 20]]]]}
    if not in_vlak(20.5, 20.5, multi):
        afw.append("het tweede deel van een multipolygoon wordt niet gezien")
    if _in_bbox({"type": "Polygon", "coordinates": [
            [[4.0, 52.0], [4.1, 52.0], [4.1, 52.1], [4.0, 52.0]]]}):
        afw.append("een vlak bij Den Haag valt binnen de bbox van Nijmegen")
    if not _in_bbox({"type": "Polygon", "coordinates": [
            [[5.85, 51.84], [5.86, 51.84], [5.86, 51.85], [5.85, 51.84]]]}):
        afw.append("een vlak in de Benedenstad valt buiten de bbox")
    x, y = wgs84_naar_rd(52.15517440, 5.38720621)
    if abs(x - 155000) > 0.01 or abs(y - 463000) > 0.01:
        afw.append(f"het nulpunt van RD komt uit op {x:.2f}, {y:.2f}")
    # Een bekend punt verder weg: de omrekening mag niet alleen in het
    # nulpunt kloppen. Plein 1944 in Nijmegen ligt in het werkingsgebied van
    # het voorbeschermd stadsbeeld (gemeten 18 oktober), dus de omrekening
    # moet daar binnen het vlak uitkomen.
    try:
        import stadsbeeld
        gebied = stadsbeeld.vlakken(stadsbeeld.WERKINGSGEBIED)
    except Exception:
        gebied = None
    if gebied:
        import bestemming
        plein = [pt for pt in bestemming.punten_per_pand().values()
                 if (pt.get("adres") or "").startswith("Plein 1944")]
        binnen = sum(1 for pt in plein if any(
            in_vlak(*wgs84_naar_rd(pt["lat"], pt["lon"]), v) for v in gebied))
        if plein and not binnen:
            afw.append("geen enkel pand aan Plein 1944 valt in het "
                       "voorbeschermd stadsbeeld; de omrekening naar RD klopt "
                       "niet")
        # En via bescherming(), zodat ook de aansluiting wordt beproefd.
        _cache.clear()
        b = None
        for pid, pt in bestemming.punten_per_pand().items():
            if (pt.get("adres") or "").startswith("Plein 1944"):
                b = bescherming(pid)
                break
        if b is not None and b["stadsbeeld"] not in ("object", "gebied"):
            afw.append(f"bescherming() ziet Plein 1944 niet in het "
                       f"stadsbeeld: {b}")
    # De drie toestanden van het rijksgezicht krijgen elk een eigen tekst.
    _oud = dict(_cache)
    try:
        _cache.clear()
        _cache.update({"geladen": True, "punten": {"P": {"lat": 5, "lon": 5}},
                       "gezichten": None, "gebied": None, "objecten": None})
        t_niet = dossierregels("P")[0][1]
        _cache["gezichten"] = []
        t_geen = dossierregels("P")[0][1]
        _cache["gezichten"] = [{"naam": "Nijmegen", "geometry": {
            "type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10],
                                                [0, 10], [0, 0]]]}}]
        t_wel = dossierregels("P")[0][1]
        if len({t_niet, t_geen, t_wel}) != 3 or t_niet != "niet nagekeken":
            afw.append("niet nagekeken, geen en wel krijgen geen eigen tekst")
        if "Cultuurhistorie 1" not in t_wel or "afgeleid" not in t_wel:
            afw.append("de afgeleide dubbelbestemming staat er niet, of niet "
                       "als afgeleid")
        if dossierregels("ONBEKEND")[0][1].startswith("geen"):
            afw.append("een pand buiten de ring leest als geen gezicht")
    finally:
        _cache.clear()
        _cache.update(_oud)
    # HET ERFGOEDREGISTER: drie toestanden, en een echt geval.
    t_niet = _registerregels({"register": None}, None)[0][1]
    t_geen = _registerregels({"register": []}, "2026-10-15")[0][1]
    t_beeld = _registerregels({"register": [], "gem_stadsbeeld": True},
                              "2026-10-15")[0][1]
    t_mon = _registerregels({"register": [{
        "BESCHERMINGS_OMS": "Gemeentelijk monument", "STATUS_OMS": "Beschermd",
        "TITEL": "Begijnenstraat 20", "STATUS_DATUM": "1988-02-10"}]},
        "2026-10-15")[0][1]
    if len({t_niet, t_geen, t_beeld, t_mon}) != 4 or t_niet != "niet nagekeken":
        afw.append("het register maakt geen onderscheid tussen niet "
                   "nagekeken, niets, alleen een stadsbeeld en een monument")
    if "art. 14" not in t_mon:
        afw.append("bij een gemeentelijk monument staat de regel er niet bij")
    t_sb = _registerregels({"register": [{
        "BESCHERMINGS_OMS": "Stadsbeeldobject", "STATUS_OMS": "Beschermd",
        "TITEL": "van Welderenstraat 100"}]}, "2026-10-15")[0][1]
    if "art. 19" not in t_sb or "buitenkant" in t_sb:
        afw.append("bij een stadsbeeldobject staat niet de regel van art. 19, "
                   "of nog alleen de buitenkant")
    _cache.clear()
    c = _laad()
    if c.get("register"):
        import bestemming
        raak = [pid for pid, pt in bestemming.punten_per_pand().items()
                if (pt.get("adres") or "") == "Begijnenstraat 9"]
        if not raak:
            afw.append("Begijnenstraat 9 staat niet meer in de voorraad; de "
                       "proef op het register meet dan niets")
        elif not any(p.get("BESCHERMINGS_OMS") ==
                            "Gemeentelijk monument"
                            for p in bescherming(raak[0])["register"] or []):
            afw.append("Begijnenstraat 9 (11-9), gemeentelijk monument, "
                       "wordt niet gevonden in het register")
    _cache.clear()
    # Een archeologisch rijksmonument maakt het gebouw geen rijksmonument
    # (Flavus 43, RCE 397576, 18 oktober).
    _cache.update({"rce_per_pand": {"F": [("397576", None, True)],
                                    "G": [("31114", None, False)],
                                    "W": [("522985", None, False)]},
                   "register_nummers": {"522985"}})
    _oud_b = globals()["bescherming"]
    try:
        globals()["bescherming"] = lambda pid: {"register": []}
        if monument_aanvullen("F") is not None:
            afw.append("een archeologisch rijksmonument geeft het gebouw de "
                       "vlag van een rijksmonument")
        if archeologisch_rijksmonument("F") != [("397576", None)]:
            afw.append("het archeologisch rijksmonument wordt niet apart "
                       "genoemd")
        if monument_aanvullen("G") is None:
            afw.append("een gebouwd RCE-rijksmonument wordt niet meer gezien")
        # De pandomtrek: een buurpand dat een rand raakt telt niet (St.
        # Anthoniusplaats 17, 0,006). Een pand dat in meer vlakken ligt,
        # telt met de som: Ganzenheuvel 5 ligt in vier vlakken (0,218, 0,22,
        # 0,237 en 0,319); hier de drie laagste, die elk onder de drempel
        # blijven en samen erboven.
        _cache["register_per_pand"] = {
            "RAND": [("1", 0.006)],
            "VIER": [("1", 0.218), ("2", 0.22), ("3", 0.237)]}
        _cache["register"] = [({"ID": i, "BESCHERMINGS_OMS":
                                "Rijksmonument", "RIJKSOBJECTCODE": "31124",
                                "TITEL": "x"}, None, (0, 0, 0, 0))
                              for i in (1, 2, 3, 4)]
        _cache["geladen"] = True
        globals()["bescherming"] = lambda pid: {"register": [
            {"BESCHERMINGS_OMS": "Rijksmonument"}]}
        if monument_aanvullen("RAND") is not None:
            afw.append("een buurpand dat de rand van een monumentvlak raakt, "
                       "wordt rijksmonument")
        if monument_aanvullen("VIER") is None:
            afw.append("een pand dat over meer monumentvlakken samen in het "
                       "register ligt, wordt geen rijksmonument")
        globals()["bescherming"] = lambda pid: {"register": []}
        # Het transformatorhuisje Waldeck Pyrmontsingel 1A (522985) staat in
        # het register op een eigen vlak; het RCE-punt viel in nummer 7 en 13.
        if monument_aanvullen("W") is not None:
            afw.append("een RCE-punt maakt een pand rijksmonument terwijl het "
                       "register dat nummer op een ander pand legt")
    finally:
        globals()["bescherming"] = _oud_b
        _cache.clear()
    # De sleutel van het register: ID is uniek per object, OBJECTID niet
    # (3085 dubbel). Getoetst op de objecten in het bestand zelf; _laad
    # splitst een object in zijn delen, en die delen hun ID.
    try:
        with open(REGISTER, encoding="utf-8") as f:
            ids = [(x.get("properties") or {}).get("ID")
                   for x in json.load(f).get("features") or []]
        if len(ids) != len(set(ids)):
            afw.append("ID is niet meer uniek in het erfgoedregister; de "
                       "meting per pandomtrek koppelt dan verkeerd")
    except (OSError, ValueError):
        pass
    # De titel van het register leest reeksen met letters en toevoegingen
    # (Houtstraat 10-12A2), aflopende reeksen en de straat van het deel ervoor.
    for titel, adres, ja in (
            ("Houtstraat 10-12A2, Houthof 51-53", "Houtstraat 12 A 1", True),
            ("Houtstraat 10-12A2, Houthof 51-53", "Houtstraat 12 A 3", False),
            ("Houtstraat 10-12A2, Houthof 51-53", "Houthof 52", True),
            ("In de Betouwstraat 15-15A", "In de Betouwstraat 15 B", False),
            ("In de Betouwstraat 10-8", "In de Betouwstraat 9", True),
            ("Burchtstraat 57, Stockumstraat 10", "Stockumstraat 10", True),
            ("St. Annastraat 53", "St. Annastraat 53 A 1", True),
            ("Molenstraat 94", "Karrengas 44 B", False)):
        if titel_noemt(titel, adres) != ja:
            afw.append(f"de titel '{titel}' leest {adres} verkeerd")
    # Punt en titel samen: eens geeft een uitkomst, oneens twijfel.
    _cache["vbo_gem"] = {"JJ": [(True, True)], "NN": [(False, False)],
                         "JN": [(True, False)], "NJ": [(False, True)]}
    z = {k: vbo_in_gemeentelijk_monument(k) for k in ("JJ", "NN", "JN", "NJ",
                                                       "XX")}
    if z != {"JJ": "binnen", "NN": "buiten", "JN": "twijfel",
             "NJ": "twijfel", "XX": None}:
        afw.append(f"punt en titel worden verkeerd samengenomen: {z}")
    _cache.clear()
    # DE SOORT VOOR DE HUUROPSLAG (art. 8a). Een gezicht telt alleen bij een
    # bouwjaar voor 1965, en een onbekend bouwjaar geeft geen opslag; een
    # gemeentelijk monument gaat voor een gezicht; "in procedure" telt niet.
    _oud_b, _oud_g = globals()["bescherming"], globals()["gemeentelijk_monument"]
    try:
        globals()["bescherming"] = lambda pid: {"rijks": ["Nijmegen"],
                                                "register": []}
        globals()["gemeentelijk_monument"] = lambda pid: []
        z = [monument_soort("X", bj, rijks=False) for bj in (1930, 1965, None)]
        if z != ["gezicht", None, None]:
            afw.append(f"het gezicht telt niet alleen voor 1965: {z}")
        globals()["gemeentelijk_monument"] = lambda pid: [{"x": 1}]
        if monument_soort("X", 1930, rijks=False) != "gemeentelijk":
            afw.append("een gemeentelijk monument in een gezicht krijgt de "
                       "opslag van het gezicht")
        if monument_soort("X", 1930, rijks=True) != "rijks":
            afw.append("een rijksmonument krijgt niet de opslag van een "
                       "rijksmonument")
    finally:
        globals()["bescherming"] = _oud_b
        globals()["gemeentelijk_monument"] = _oud_g
    _cache.clear()
    _cache.update({"register_per_pand:Gemeentelijk monument": None,
                   "geladen": True, "register": [], "punten": {}})
    _oud_b = globals()["bescherming"]
    try:
        globals()["bescherming"] = lambda pid: {"register": [
            {"BESCHERMINGS_OMS": "In procedure"},
            {"BESCHERMINGS_OMS": "Stadsbeeldobject"}]}
        if gemeentelijk_monument("P"):
            afw.append("een monument in procedure of een stadsbeeldobject "
                       "telt als gemeentelijk monument")
        # Een pand dat niet in de meting staat, is niet gemeten: dan het
        # pandpunt (Molenstraat 55). Een buurpand met 0,01 telt niet.
        globals()["bescherming"] = lambda pid: {"register": [
            {"BESCHERMINGS_OMS": "Gemeentelijk monument", "ID": 7}]}
        _cache["register_per_pand:Gemeentelijk monument"] = {
            "RANDJE": [("7", 0.01)], "ANDER": [("7", 1.0)]}
        if not gemeentelijk_monument("ONBEKEND"):
            afw.append("een pand dat de meting niet kent, telt als gemeten "
                       "en niet in het vlak")
        if gemeentelijk_monument("RANDJE"):
            afw.append("een buurpand dat de rand van een gemeentelijk "
                       "monument raakt, telt als monument")
    finally:
        globals()["bescherming"] = _oud_b
        _cache.clear()
    for a in afw:
        print("AFWIJKING: " + a, file=sys.stderr)
    print(f"Proef gezicht: {len(afw)} afwijkingen", file=sys.stderr)
    return 1 if afw else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proef", action="store_true")
    ap.add_argument("--ophalen", action="store_true")
    a = ap.parse_args()
    if a.proef:
        return proef()
    if a.ophalen:
        verslag(ophalen())
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
