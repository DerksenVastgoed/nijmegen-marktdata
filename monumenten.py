#!/usr/bin/env python3
"""
Gemeentelijke monumenten in Nijmegen, uit twee open bronnen naast elkaar.

WAAROM TWEE. 18 oktober 2026: het omgevingsplan heeft geen informatieobject
voor gemeentelijke monumenten, nijmegen.nl sluit op de monumentenlijst geen
bestand of kaart in, de GeoServer gaf 401 en de catalogus van data.overheid.nl
gaf nul datasets. Het register dat de Erfgoedverordening voorschrijft
(CVDR731607, art. 2) is dus niet als bestand te vinden. Twee bronnen die er
elk een deel van dekken:

1. AANWIJZINGSBESLUITEN in het Gemeenteblad, via de open SRU-zoekdienst van
   de officiele bekendmakingen. Officieel en met datum, maar elektronisch
   pas vanaf ongeveer 2014; oudere aanwijzingen ontbreken.
2. WIKIDATA, de door vrijwilligers bijgehouden lijst, open onder CC0, vaak
   met coordinaten. Niet officieel, dus nooit zonder die vermelding.

Waar ze het eens zijn, is het sterk; waar alleen Wikidata een monument kent,
is het waarschijnlijk een oude aanwijzing. Dit is een verkenning: eerst zien
wat er komt, voordat het dossier erop leunt.

  python3 monumenten.py --verken
  python3 monumenten.py --proef
"""
import argparse
import json
import re
import sys
import urllib.parse

import stadsbeeld  # mag() en haal(): robots.txt eerst, een implementatie

SRU = "https://repository.overheid.nl/sru"
# Een paar varianten, want de indexnamen van deze dienst zijn hier niet
# nagekeken. Het verslag zegt per variant hoeveel er terugkwam.
SRU_VRAGEN = [
    'dt.creator="Nijmegen" and cql.textAndIndexes="gemeentelijk monument"',
    'dt.creator="Nijmegen" and dt.title any "monument"',
    'cql.textAndIndexes="Nijmegen" and cql.textAndIndexes="aanwijzing '
    'gemeentelijk monument"',
]
WIKIDATA = "https://query.wikidata.org/sparql"
# Het label in de vraag zelf in plaats van een vast Q-nummer, zodat een
# verkeerd onthouden nummer niet stil nul oplevert.
SPARQL = """
SELECT ?item ?itemLabel ?adres ?coord ?aanduidingLabel WHERE {
  ?aanduiding rdfs:label "gemeentelijk monument"@nl .
  ?item wdt:P1435 ?aanduiding ;
        wdt:P131 ?plaats .
  ?plaats rdfs:label "Nijmegen"@nl .
  OPTIONAL { ?item wdt:P6375 ?adres . }
  OPTIONAL { ?item wdt:P625 ?coord . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "nl". }
}
"""
UIT_GMB = "monumenten_gemeenteblad.json"
UIT_WD = "monumenten_wikidata.json"
VERSLAG = "monumenten_bronnen_verslag.md"


def records_uit_sru(xml):
    """[(titel, url, datum)] uit een SRU-antwoord, of None als het geen
    SRU-antwoord is."""
    if not xml or "searchRetrieveResponse" not in xml:
        return None
    uit = []
    for rec in re.findall(r"<(?:\w+:)?record>(.*?)</(?:\w+:)?record>", xml,
                          re.S):
        titel = re.search(r"<dcterms:title>([^<]*)</dcterms:title>", rec)
        url = re.search(r"<(?:\w+:)?preferredUrl>([^<]*)<", rec)
        datum = re.search(r"<dcterms:available>([^<]*)<", rec)
        uit.append(((titel.group(1) if titel else "").strip(),
                    (url.group(1) if url else "").strip(),
                    (datum.group(1) if datum else "").strip()))
    return uit


def aantal_uit_sru(xml):
    m = re.search(r"<(?:\w+:)?numberOfRecords>(\d+)<", xml or "")
    return int(m.group(1)) if m else None


def rijen_uit_sparql(antwoord):
    """[{item, naam, adres, lon, lat}] uit een SPARQL-JSON-antwoord, of None."""
    try:
        d = json.loads(antwoord)
    except ValueError:
        return None
    uit = []
    for b in (d.get("results") or {}).get("bindings") or []:
        rij = {"item": (b.get("item") or {}).get("value"),
               "naam": (b.get("itemLabel") or {}).get("value"),
               "adres": (b.get("adres") or {}).get("value")}
        m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)",
                     (b.get("coord") or {}).get("value") or "")
        if m:
            rij["lon"], rij["lat"] = float(m.group(1)), float(m.group(2))
        uit.append(rij)
    return uit


def verken():
    r = ["# Gemeentelijke monumenten: twee open bronnen", ""]
    r.append("## Gemeenteblad (SRU)")
    beste = []
    for vraag in SRU_VRAGEN:
        url = SRU + "?" + urllib.parse.urlencode({
            "operation": "searchRetrieve", "version": "2.0",
            "query": vraag, "maximumRecords": "200"})
        _e, _s, inhoud = stadsbeeld.haal(url, r)
        tekst = inhoud.decode("utf-8", "replace") if inhoud else ""
        recs = records_uit_sru(tekst)
        r.append(f"- `{vraag}`: totaal {aantal_uit_sru(tekst)}, gelezen "
                 f"{'onleesbaar' if recs is None else len(recs)}")
        for t, u, d in (recs or [])[:8]:
            r.append(f"  - {d} {t[:140]} ({u})")
        if recs and len(recs) > len(beste):
            beste = recs
    with open(UIT_GMB, "w", encoding="utf-8") as f:
        json.dump([{"titel": t, "url": u, "datum": d} for t, u, d in beste],
                  f, ensure_ascii=False, indent=1)
    r.append("")
    r.append("## Wikidata")
    url = WIKIDATA + "?" + urllib.parse.urlencode({
        "query": SPARQL, "format": "json"})
    _e, _s, inhoud = stadsbeeld.haal(url, r)
    rijen = rijen_uit_sparql(inhoud.decode("utf-8", "replace")) \
        if inhoud else None
    if rijen is None:
        r.append("- geen leesbaar antwoord")
    else:
        met_coord = sum(1 for x in rijen if "lat" in x)
        met_adres = sum(1 for x in rijen if x.get("adres"))
        r.append(f"- {len(rijen)} rijen, {met_coord} met coordinaten, "
                 f"{met_adres} met adres")
        for x in rijen[:10]:
            r.append(f"  - {x.get('naam')} | {x.get('adres')} | "
                     f"{x.get('lat')}, {x.get('lon')}")
        with open(UIT_WD, "w", encoding="utf-8") as f:
            json.dump({"bron": "Wikidata, CC0, niet officieel",
                       "rijen": rijen}, f, ensure_ascii=False, indent=1)
    with open(VERSLAG, "w", encoding="utf-8") as f:
        f.write("\n".join(r) + "\n")
    print("\n".join(r))
    return 0


# DE BRON VAN DE GEMEENTE ZELF. Gevonden op 18 oktober via de KaartViewer
# (kaartviewer.py): de kaart Historie, map Monumenten, heeft de lagen
# "Beschermde objecten" (extern_Monumenten:HIS_MON_MONUMENT) en "Beschermde
# gebieden" (extern_Monumenten:HIS_MON_BESCHERMDE_GEB). Andere werkruimtes
# van dezelfde server geven WFS met outputFormat, dus hier ook proberen.
WFS = "https://services.nijmegen.nl/geoservices/extern_Monumenten/ows"
WFS_LAGEN = ("extern_Monumenten:HIS_MON_MONUMENT",
             "extern_Monumenten:HIS_MON_BESCHERMDE_GEB")


def verken_wfs():
    import collections
    r = ["# Monumenten uit de GeoServer van de gemeente", ""]
    for laag in WFS_LAGEN:
        url = WFS + "?" + urllib.parse.urlencode({
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": laag, "outputFormat": "application/json",
            "srsName": "EPSG:28992"})
        _e, soort, inhoud = stadsbeeld.haal(url, r)
        r.append(f"## {laag}")
        if inhoud is None:
            r.append("- niet opgehaald")
            continue
        try:
            d = json.loads(inhoud.decode("utf-8"))
        except ValueError:
            r.append(f"- geen JSON ({soort}): `{inhoud[:300]!r}`")
            continue
        fs = d.get("features") or []
        r.append(f"- {len(fs)} objecten")
        if fs:
            velden = sorted((fs[0].get("properties") or {}).keys())
            r.append(f"- velden: {velden}")
            for veld in velden:
                waarden = collections.Counter(
                    str((f.get("properties") or {}).get(veld)) for f in fs)
                if len(waarden) <= 12:
                    r.append(f"  - {veld}: {dict(waarden.most_common(12))}")
            for f in fs[:5]:
                r.append(f"  - voorbeeld: "
                         f"{json.dumps(f.get('properties'), ensure_ascii=False)[:400]}")
        naam = laag.split(":")[1].lower()
        with open(f"monumenten_{naam}.geojson", "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        r.append("")
    with open("monumenten_wfs_verslag.md", "w", encoding="utf-8") as f:
        f.write("\n".join(r) + "\n")
    print("\n".join(r))
    return 0


# RCE-RIJKSMONUMENTEN ALS PUNTEN, VIA PDOK. 18 oktober 2026: het bestand van
# rijksmonumenten.py (RCE linked data, 45 minuten per run) bevat 76 unieke
# rijksmonumentnummers op 174 adressen, terwijl het erfgoedregister van de
# gemeente 206 objecten "Rijksmonument" kent. Dezelfde RCE publiceert de
# rijksmonumenten ook als punten in de PDOK-collectie die gezicht.py al
# gebruikt (rce_inspire_points, naamruimte nlps-rijksmonumenten). Dit haalt
# ze op voor de hele gemeente en vergelijkt de nummers met het register.
RCE_PUNTEN = ("https://api.pdok.nl/rce/beschermde-gebieden-cultuurhistorie/"
              "ogc/v1/collections/rce_inspire_points/items")
# De gemeente Nijmegen ruim, in WGS84 (lon, lat); de omhullende van de
# gemeentelijke lagen in RD is 170.170-200.457 bij 419.060-435.629.
GEMEENTE_BBOX = (5.72, 51.78, 5.97, 51.91)
UIT_RCE = "rijksmonumenten_rce_punten.json"


def nummer_uit_citatie(c):
    """Het rijksmonumentnummer uit ci_citation, zoals 'monumenten/341971'."""
    m = re.search(r"monumenten/(\d+)", c or "")
    return m.group(1) if m else None


def _gemeentegrens(r):
    url = ("https://services.nijmegen.nl/geoservices/extern_GEO_Gebiedsindelingen"
           "/ows?" + urllib.parse.urlencode({
               "service": "WFS", "version": "2.0.0", "request": "GetFeature",
               "typeNames": "extern_GEO_Gebiedsindelingen:GEO_IND_GEMEENTEGRENS",
               "outputFormat": "application/json", "srsName": "EPSG:28992"}))
    _e, _s, inhoud = stadsbeeld.haal(url, r)
    if inhoud is None:
        return None
    try:
        d = json.loads(inhoud.decode("utf-8"))
    except ValueError:
        return None
    uit = []
    for f in d.get("features") or []:
        g = f.get("geometry") or {}
        if g.get("type") == "Polygon":
            uit.append(g)
        elif g.get("type") == "MultiPolygon":
            uit += [{"type": "Polygon", "coordinates": c}
                    for c in g.get("coordinates") or []]
    return uit or None


def verken_rce():
    import time
    r = ["# Rijksmonumenten van de RCE als punten (PDOK)", ""]
    url = RCE_PUNTEN + "?" + urllib.parse.urlencode({
        "f": "json", "limit": "500",
        "bbox": ",".join(str(v) for v in GEMEENTE_BBOX)})
    punten, paginas = [], 0
    while url and paginas < 30:
        _e, _s, inhoud = stadsbeeld.haal(url, r)
        if inhoud is None:
            break
        d = json.loads(inhoud.decode("utf-8"))
        paginas += 1
        for f in d.get("features") or []:
            p = f.get("properties") or {}
            if p.get("namespace") != "nlps-rijksmonumenten":
                continue
            c = (f.get("geometry") or {}).get("coordinates") or [None, None]
            punten.append({"nummer": nummer_uit_citatie(p.get("ci_citation")),
                           "naam": p.get("text"), "lon": c[0], "lat": c[1],
                           "klasse": p.get("siteprotectionclassification"),
                           "aanduiding": p.get("designation")})
        url = next((l.get("href") for l in d.get("links") or []
                    if l.get("rel") == "next"), None)
        time.sleep(0.2)
    # BINNEN DE GEMEENTEGRENS. De eerste ronde gaf precies 500 punten op een
    # bbox die ook Ubbergen, Groesbeek en Beuningen raakt. De grens komt van
    # dezelfde GeoServer als het register (extern_GEO_Gebiedsindelingen).
    grens = _gemeentegrens(r)
    if grens:
        import gezicht
        binnen = []
        for x in punten:
            if x["lat"] is None:
                continue
            gx, gy = gezicht.wgs84_naar_rd(x["lat"], x["lon"])
            if any(gezicht.in_vlak(gx, gy, v) for v in grens):
                binnen.append(x)
        r.append(f"- binnen de gemeentegrens: {len(binnen)} van "
                 f"{len(punten)}")
        punten = binnen
    else:
        r.append("- gemeentegrens niet te lezen; punten niet gefilterd")
    nummers = {x["nummer"] for x in punten if x["nummer"]}
    r.append(f"- {len(punten)} punten, {len(nummers)} unieke nummers, "
             f"{paginas} pagina's, {'volledig' if url is None else 'NIET VOLLEDIG'}")
    try:
        with open("monumenten_his_mon_monument.geojson", encoding="utf-8") as f:
            reg = json.load(f).get("features") or []
        # Het register schrijft soms "31114 " of "31177 en 31178".
        regnr = {n for x in reg
                 for n in re.findall(r"\d{4,6}",
                                     str(x["properties"].get("RIJKSOBJECTCODE")
                                         or ""))}
        r.append(f"- register: {len(regnr)} objecten met een "
                 f"rijksmonumentnummer; in beide {len(nummers & regnr)}, "
                 f"alleen RCE {len(nummers - regnr)}, alleen register "
                 f"{len(regnr - nummers)}")
        r.append(f"  - alleen RCE, voorbeelden: {sorted(nummers - regnr)[:15]}")
        r.append(f"  - alleen register, voorbeelden: "
                 f"{sorted(regnr - nummers)[:15]}")
    except (OSError, ValueError):
        r.append("- register niet te lezen")
    try:
        with open("rijksmonumenten_nijmegen.json", encoding="utf-8") as f:
            oud = json.load(f)
        oudnr = {nummer_uit_citatie(x.get("nummer")) or
                 re.sub(r"\D", "", x.get("nummer") or "")
                 for v in oud.values() for x in v}
        oudnr.discard("")
        r.append(f"- rijksmonumenten_nijmegen.json: {len(oudnr)} nummers, "
                 f"waarvan {len(oudnr & nummers)} ook als RCE-punt")
    except (OSError, ValueError):
        pass
    with open(UIT_RCE, "w", encoding="utf-8") as f:
        json.dump({"bron": "RCE via PDOK, rce_inspire_points, CC BY 4.0",
                   "punten": punten}, f, ensure_ascii=False)
    with open("rijksmonumenten_rce_verslag.md", "w", encoding="utf-8") as f:
        f.write("\n".join(r) + "\n")
    print("\n".join(r))
    return 0


# RCE-PUNT NAAR PAND. 18 oktober 2026: van de 261 rijksmonumenten (RCE-punten)
# staan er 66 niet in het erfgoedregister, en voor die 66 wisten we niet in
# welk pand ze liggen: een RCE-punt is een punt, en wij kennen per pand ook
# alleen een punt. De BAG kent per pand de omtrek. Per RCE-punt vraagt dit de
# panden waarvan de omtrek een vierkant van een meter rond het punt raakt, bij
# de BAG-WFS van PDOK. Voor alle 261, niet alleen de 66, zodat de koppeling
# te toetsen is tegen het register: waar beide een pand noemen, horen ze
# hetzelfde pand te noemen.
BAG_WFS = "https://service.pdok.nl/lv/bag/wfs/v2_0"
UIT_RCE_PANDEN = "rijksmonumenten_rce_panden.json"


def panden_bij_punt(x, y, r, d=0.5):
    """De pand-identificaties waarvan de omtrek het vierkant rond (x, y) in
    RD raakt, of None als de BAG geen antwoord gaf."""
    url = BAG_WFS + "?" + urllib.parse.urlencode({
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeName": "bag:pand", "outputFormat": "application/json",
        "bbox": f"{x - d},{y - d},{x + d},{y + d},urn:ogc:def:crs:EPSG::28992"})
    _e, _s, inhoud = stadsbeeld.haal(url, r)
    if inhoud is None:
        return None
    try:
        d = json.loads(inhoud.decode("utf-8"))
    except ValueError:
        return None
    return [str((f.get("properties") or {}).get("identificatie"))
            for f in d.get("features") or []
            if (f.get("properties") or {}).get("identificatie")]


def koppel_rce_panden():
    import time
    import gezicht
    r = ["# RCE-rijksmonumenten gekoppeld aan BAG-panden", ""]
    try:
        with open(UIT_RCE, encoding="utf-8") as f:
            punten = json.load(f).get("punten") or []
    except (OSError, ValueError):
        r.append("- geen RCE-punten; eerst --rce")
        punten = []
    uit, fout, leeg = {}, 0, 0
    for x in punten:
        if x.get("lat") is None or not x.get("nummer"):
            continue
        gx, gy = gezicht.wgs84_naar_rd(x["lat"], x["lon"])
        p = panden_bij_punt(gx, gy, r if fout < 3 else [])
        time.sleep(0.2)
        if p is None:
            fout += 1
            continue
        if not p:
            leeg += 1
        uit[x["nummer"]] = {"naam": x.get("naam"), "panden": p,
                            "klasse": x.get("klasse"),
                            "aanduiding": x.get("aanduiding")}
    r.append(f"- {len(uit)} nummers gevraagd, {fout} zonder antwoord, "
             f"{leeg} met een punt buiten elk pand")
    # De toets: het register noemt per object een rijksmonumentnummer en ligt
    # als vlak; via de pandpunten van de voorraad weten we welk pand in welk
    # registervlak valt.
    reg = gezicht._laad().get("register") or []
    punt_pand = {pid: pt for pid, pt in gezicht._laad()["punten"].items()}
    nr_pand_reg = {}
    for pid, pt in punt_pand.items():
        gx, gy = gezicht.wgs84_naar_rd(pt["lat"], pt["lon"])
        for props in gezicht._raak(reg, gx, gy):
            for n in re.findall(r"\d{4,6}",
                                str(props.get("RIJKSOBJECTCODE") or "")):
                nr_pand_reg.setdefault(n, set()).add(pid)
    eens = oneens = te_toetsen = 0
    voorbeelden = []
    for n, v in uit.items():
        if n in nr_pand_reg and v["panden"]:
            te_toetsen += 1
            if set(v["panden"]) & nr_pand_reg[n]:
                eens += 1
            else:
                oneens += 1
                voorbeelden.append((n, v["naam"], v["panden"],
                                    sorted(nr_pand_reg[n])))
    r.append(f"- toets tegen het register (pand in de ring, nummer in "
             f"beide): {te_toetsen}, waarvan {eens} hetzelfde pand en "
             f"{oneens} een ander")
    r += [f"  - {v}" for v in voorbeelden[:10]]
    ring = set(punt_pand)
    in_ring = {n: [p for p in v["panden"] if p in ring] for n, v in uit.items()}
    r.append(f"- nummers met een pand in de ring: "
             f"{sum(1 for v in in_ring.values() if v)}, waarvan niet in het "
             f"register: {sum(1 for n, v in in_ring.items() if v and n not in nr_pand_reg)}")
    with open(UIT_RCE_PANDEN, "w", encoding="utf-8") as f:
        json.dump({"bron": "RCE-punten via PDOK, gekoppeld aan BAG-pandomtrek "
                           "(PDOK BAG WFS), vierkant van 1 m rond het punt",
                   "nummers": uit}, f, ensure_ascii=False, indent=1)
    with open("rijksmonumenten_rce_panden_verslag.md", "w",
              encoding="utf-8") as f:
        f.write("\n".join(r) + "\n")
    print("\n".join(r))
    return 0


# DE PANDOMTREK TEGEN HET REGISTERVLAK. 19 oktober 2026. Tot nu toe toetst
# het dossier een pand met een punt: valt het pandpunt in het vlak van het
# register, dan hoort het erbij. Bij St. Anthoniusplaats 15-16 (31169) valt
# alleen het punt van 15 erin, terwijl het register beide nummers noemt. Hier
# wordt per rijksmonumentvlak elk BAG-pand opgehaald dat de omhullende raakt,
# en gemeten welk deel van het pand in het vlak ligt.
#
# HOE GEMETEN. Geen geometriebibliotheek: een raster van punten op STAP meter
# binnen de pandomtrek, en per punt gezicht.in_vlak (dezelfde toets als
# overal). aandeel_pand = punten in beide / punten in het pand. Bij 0,5 m is
# dat op een pand van 50 m2 een raster van 200 punten. Een drempel staat hier
# bewust nog niet: die volgt uit de verdeling in het verslag.
# Rijks- en gemeentelijke monumenten: beide geven een huuropslag (Besluit
# huurprijzen woonruimte art. 8a: 35% en 15%), dus beide per pandomtrek.
SOORTEN_OMTREK = ("Rijksmonument", "Gemeentelijk monument")
UIT_REG_PANDEN = "monumenten_register_panden.json"
STAP = 0.5


def panden_in_vak(minx, miny, maxx, maxy, r):
    """[(pand-id, geometrie)] van elk BAG-pand dat het vak raakt, of None."""
    url = BAG_WFS + "?" + urllib.parse.urlencode({
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeName": "bag:pand", "outputFormat": "application/json",
        "srsName": "urn:ogc:def:crs:EPSG::28992", "count": "1000",
        "bbox": f"{minx},{miny},{maxx},{maxy},urn:ogc:def:crs:EPSG::28992"})
    _e, _s, inhoud = stadsbeeld.haal(url, r)
    if inhoud is None:
        return None
    try:
        d = json.loads(inhoud.decode("utf-8"))
    except ValueError:
        return None
    return [(str(f["properties"]["identificatie"]), f.get("geometry"))
            for f in d.get("features") or []
            if (f.get("properties") or {}).get("identificatie")]


VBO_VELDEN = {}


def vbo_in_pand(pid, pand_geom, r):
    """[{vbo, adres, x, y}] van de verblijfsobjecten in dit pand, uit de BAG
    WFS in RD, of None als de BAG geen antwoord gaf. Gezocht in de omhullende
    van het pand en gefilterd op het pand-id."""
    a, b, c, d = _omhullende(pand_geom)
    url = BAG_WFS + "?" + urllib.parse.urlencode({
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeName": "bag:verblijfsobject", "outputFormat": "application/json",
        "srsName": "urn:ogc:def:crs:EPSG::28992", "count": "1000",
        "bbox": f"{a},{b},{c},{d},urn:ogc:def:crs:EPSG::28992"})
    _e, _s, inhoud = stadsbeeld.haal(url, r)
    if inhoud is None:
        return None
    try:
        feats = json.loads(inhoud.decode("utf-8")).get("features") or []
    except ValueError:
        return None
    uit = []
    for f in feats:
        pr = f.get("properties") or {}
        if not VBO_VELDEN and pr:
            VBO_VELDEN.update({k: type(v).__name__ for k, v in pr.items()})
        if pid not in str(pr.get("pandidentificatie") or ""):
            continue
        g = f.get("geometry") or {}
        if g.get("type") != "Point":
            continue
        x, y = g["coordinates"][:2]
        adres = " ".join(str(pr.get(k) or "") for k in
                         ("openbare_ruimte", "huisnummer", "huisletter",
                          "toevoeging")).strip()
        uit.append({"vbo": str(pr.get("identificatie")),
                    "adres": " ".join(adres.split()), "x": x, "y": y})
    return uit


def _omhullende(geom):
    pts = [pt for poly in (geom["coordinates"] if geom["type"] ==
                           "MultiPolygon" else [geom["coordinates"]])
           for ring in poly for pt in ring]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def aandeel(pand, vlak, stap=STAP):
    """(rasterpunten in het pand, waarvan in het vlak) op stap meter."""
    import gezicht
    a, b, c, d = _omhullende(pand)
    in_pand = in_beide = 0
    y = b + stap / 2
    while y < d:
        x = a + stap / 2
        while x < c:
            if gezicht.in_vlak(x, y, pand):
                in_pand += 1
                if gezicht.in_vlak(x, y, vlak):
                    in_beide += 1
            x += stap
        y += stap
    return in_pand, in_beide


def koppel_register_panden():
    import time
    r = ["# Monumenten uit het register: pandomtrek tegen vlak", "",
         f"Raster van {STAP} m binnen elke BAG-pandomtrek; aandeel = deel van "
         "de rasterpunten van het pand dat in het registervlak valt.", ""]
    try:
        with open("monumenten_his_mon_monument.geojson",
                  encoding="utf-8") as f:
            feats = json.load(f).get("features") or []
    except (OSError, ValueError):
        r.append("- geen register; eerst --wfs")
        feats = []
    rijks = [f for f in feats if (f.get("properties") or {})
             .get("BESCHERMINGS_OMS") in SOORTEN_OMTREK and f.get("geometry")]
    uit, fout, vbo_fout = {}, 0, 0
    from gezicht import in_vlak as gezicht_in_vlak
    for f in rijks:
        p, geom = f["properties"], f["geometry"]
        panden = panden_in_vak(*_omhullende(geom), r if fout < 3 else [])
        time.sleep(0.2)
        if panden is None:
            fout += 1
            continue
        rij = []
        for pid, pg in panden:
            if not pg or pg.get("type") not in ("Polygon", "MultiPolygon"):
                continue
            n_p, n_b = aandeel(pg, geom)
            # OOK NUL BEWAREN. Tot 19 oktober bleef een pand zonder overlap
            # weg, en dan was "niet in de meting" niet te onderscheiden van
            # "gemeten, nul". gezicht.py las afwezig als niet gemeten, en dat
            # klopte dus niet. Nu staat elk pand dat de BAG bij het vlak
            # teruggeeft erin, ook met 0; afwezig betekent: de BAG gaf dit
            # pand-id hier niet terug.
            rij.append({"pand": pid, "punten": n_p, "in_vlak": n_b,
                        "aandeel_pand": round(n_b / n_p, 3) if n_p else 0.0})
            # DEELS IN HET VLAK: PER WONING. Ligt een pand maar voor een deel
            # in het vlak, dan beslist waar de woning ligt. De BAG geeft per
            # verblijfsobject een punt in RD; dat punt tegen hetzelfde vlak,
            # zonder omrekening uit WGS84.
            a_p = rij[-1]["aandeel_pand"]
            if 0.01 <= a_p < 0.99:
                vbo = vbo_in_pand(pid, pg, r if vbo_fout < 3 else [])
                time.sleep(0.2)
                if vbo is None:
                    vbo_fout += 1
                else:
                    rij[-1]["vbo"] = [
                        dict(v, in_vlak=gezicht_in_vlak(v["x"], v["y"], geom))
                        for v in vbo]
        # SLEUTEL IS ID, NIET OBJECTID. 19 oktober 2026: OBJECTID is in het
        # register niet uniek (2.781 objecten, 2.757 OBJECTID's; bij de rijks-
        # en gemeentelijke monumenten 5 dubbel). Onder OBJECTID 3085 staan
        # "van Berchenstraat 31-35, Parkweg 1" en "Parkweg 1, van
        # Berchenstraat 35"; de tweede overschreef de eerste, en daarmee
        # verdween het vlak van nummer 31 en 33 uit de meting. ID is uniek.
        uit[str(p.get("ID"))] = {
            "soort": p.get("BESCHERMINGS_OMS"),
            "titel": p.get("TITEL"), "naam": p.get("OBJECTNAAM"),
            "nummers": re.findall(r"\d{4,6}", str(p.get("RIJKSOBJECTCODE")
                                                   or "")),
            "panden": rij}
    r.append(f"- {len(rijks)} vlakken ("
             + ", ".join(f"{sum(1 for f in rijks if f['properties'].get('BESCHERMINGS_OMS') == s)} {s.lower()}"
                         for s in SOORTEN_OMTREK)
             + f"), {fout} zonder antwoord van de BAG")
    alle = [x["aandeel_pand"] for v in uit.values() for x in v["panden"]]
    r.append(f"- {len(alle)} paren vlak-pand met overlap")
    met_vbo = [x for v in uit.values() for x in v["panden"] if "vbo" in x]
    n_vbo = sum(len(x["vbo"]) for x in met_vbo)
    r.append(f"- {len(met_vbo)} paren deels in het vlak (0,01 tot 0,99) met "
             f"de verblijfsobjecten erbij: {n_vbo} verblijfsobjecten, waarvan "
             f"{sum(1 for x in met_vbo for v in x['vbo'] if v['in_vlak'])} in "
             f"het vlak; {vbo_fout} keer geen antwoord van de BAG")
    r.append(f"- velden van bag:verblijfsobject: {VBO_VELDEN}")
    r.append("")
    r.append("## Verdeling van aandeel_pand (deel van het pand in het vlak)")
    grenzen = [0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99, 1.0001]
    onder = 0
    for g in grenzen:
        n = sum(1 for a in alle if onder <= a < g)
        r.append(f"- {onder:.2f} tot {min(g, 1):.2f}{' (incl.)' if g > 1 else ''}"
                 f": {n}")
        onder = g
    r.append("")
    # De drempel gaat per pand over de som van alle vlakken van een soort;
    # dit is de verdeling waaruit hij volgt.
    for soort in SOORTEN_OMTREK:
        som = {}
        for v in uit.values():
            if v["soort"] == soort:
                for x in v["panden"]:
                    som[x["pand"]] = som.get(x["pand"], 0) + x["aandeel_pand"]
        r.append(f"## Som per pand, {soort.lower()} ({len(som)} panden)")
        stappen = [i / 20 for i in range(21)] + [99]
        for a, b in zip(stappen, stappen[1:]):
            n = sum(1 for x in som.values() if a <= x < b)
            if n:
                r.append(f"- {a:.2f} tot {b if b < 99 else 'meer'}: {n}")
        r.append("")
    r.append("## St. Anthoniusplaats 15-16 (31169)")
    for k, v in uit.items():
        if "31169" in v["nummers"]:
            r.append(f"- {v['titel']}: {v['panden']}")
    r.append("")
    r.append("## Paren tussen 0,05 en 0,9 (de twijfelzone)")
    for k, v in uit.items():
        for x in v["panden"]:
            if 0.05 <= x["aandeel_pand"] < 0.9:
                r.append(f"- {v['titel']} ({','.join(v['nummers'])}): pand "
                         f"{x['pand']}, {x['aandeel_pand']}")
    # PAND-ID'S DIE DE BAG NIET TERUGGEEFT. Voor elk pand van de voorraad
    # waarvan het pandpunt in een gemeten vlak ligt, maar dat bij dat vlak
    # niet terugkwam: welk pand de BAG op dat punt wel kent.
    import gezicht
    punten = gezicht._laad().get("punten") or {}
    gemeten = {o: {x["pand"] for x in v["panden"]} for o, v in uit.items()}
    vlak_van = {str(f["properties"].get("ID")):
                (f["geometry"], _omhullende(f["geometry"])) for f in rijks}
    r.append("")
    r.append("## Voorraadpanden met het pandpunt in een vlak, die de BAG bij "
             "dat vlak niet teruggaf")
    vreemd = 0
    for pid, pt in punten.items():
        x, y = gezicht.wgs84_naar_rd(pt["lat"], pt["lon"])
        for o, (geom, (a, b, c, d)) in vlak_van.items():
            if a <= x <= c and b <= y <= d and o in gemeten and \
                    pid not in gemeten[o] and gezicht.in_vlak(x, y, geom):
                vreemd += 1
                bag = panden_bij_punt(x, y, [], d=0.1)
                time.sleep(0.2)
                r.append(f"- {pt['adres']}: voorraad {pid}, vlak "
                         f"{uit[o]['titel']}; BAG op het punt: {bag}")
    r.append(f"- {vreemd} gevallen")
    with open(UIT_REG_PANDEN, "w", encoding="utf-8") as f:
        json.dump({"sleutel": "ID",
                   "bron": "erfgoedregister gemeente (rijks- en gemeentelijke "
                           "monumentvlakken) "
                           "tegen BAG-pandomtrek (PDOK BAG WFS), raster "
                           f"{STAP} m", "objecten": uit},
                  f, ensure_ascii=False, indent=1)
    with open("monumenten_register_panden_verslag.md", "w",
              encoding="utf-8") as f:
        f.write("\n".join(r) + "\n")
    print("\n".join(r))
    return 0


def proef():
    afw = []
    sru = ("<sru:searchRetrieveResponse><sru:numberOfRecords>2"
           "</sru:numberOfRecords><sru:record><dcterms:title>Aanwijzing "
           "gemeentelijk monument Hertogstraat 13</dcterms:title>"
           "<gzd:preferredUrl>https://x/gmb-1.html</gzd:preferredUrl>"
           "<dcterms:available>2023-01-02</dcterms:available></sru:record>"
           "</sru:searchRetrieveResponse>")
    if records_uit_sru(sru) != [("Aanwijzing gemeentelijk monument "
                                 "Hertogstraat 13", "https://x/gmb-1.html",
                                 "2023-01-02")]:
        afw.append(f"SRU-records worden niet gelezen: {records_uit_sru(sru)}")
    if aantal_uit_sru(sru) != 2:
        afw.append("het totaal uit SRU wordt niet gelezen")
    if records_uit_sru("<html>fout</html>") is not None:
        afw.append("een onleesbaar SRU-antwoord telt als nul besluiten")
    sp = json.dumps({"results": {"bindings": [{
        "item": {"value": "http://www.wikidata.org/entity/Q1"},
        "itemLabel": {"value": "Hertogstraat 13"},
        "coord": {"value": "Point(5.86 51.84)"}}]}})
    rij = (rijen_uit_sparql(sp) or [{}])[0]
    if (rij.get("lon"), rij.get("lat")) != (5.86, 51.84):
        afw.append(f"de coordinaten uit Wikidata worden niet gelezen: {rij}")
    if rijen_uit_sparql("<html>") is not None:
        afw.append("een onleesbaar Wikidata-antwoord telt als nul monumenten")
    if nummer_uit_citatie("https://monumentenregister.cultureelerfgoed.nl/"
                          "monumenten/341971") != "341971" or \
            nummer_uit_citatie("kennis.cultureelerfgoed.nl/Gezicht/1439"):
        afw.append("het rijksmonumentnummer uit de citatie wordt verkeerd "
                   "gelezen")
    # De verblijfsobjecten van een pand: alleen die met dit pand-id, met
    # het punt in RD zoals de BAG het geeft.
    _oud_haal = stadsbeeld.haal
    try:
        nep = {"features": [
            {"properties": {"identificatie": "V1", "pandidentificatie":
                            "P1", "openbare_ruimte": "Molenstraat",
                            "huisnummer": 55},
             "geometry": {"type": "Point", "coordinates": [1.0, 2.0]}},
            {"properties": {"identificatie": "V2", "pandidentificatie": "P2"},
             "geometry": {"type": "Point", "coordinates": [3.0, 4.0]}}]}
        stadsbeeld.haal = lambda url, r: (None, 200,
                                          json.dumps(nep).encode("utf-8"))
        v = vbo_in_pand("P1", {"type": "Polygon", "coordinates": [[[0, 0],
                                                                    [5, 5]]]},
                        [])
        if v != [{"vbo": "V1", "adres": "Molenstraat 55", "x": 1.0,
                  "y": 2.0}]:
            afw.append(f"de verblijfsobjecten van een pand worden verkeerd "
                       f"gelezen: {v}")
        stadsbeeld.haal = lambda url, r: (None, None, None)
        if vbo_in_pand("P1", {"type": "Polygon", "coordinates": [[[0, 0],
                                                                  [5, 5]]]},
                       []) is not None:
            afw.append("geen antwoord van de BAG leest als een pand zonder "
                       "verblijfsobjecten")
    finally:
        stadsbeeld.haal = _oud_haal
    # Het aandeel: een pand van 10 bij 10 m waarvan het vlak de linkerhelft
    # dekt, geeft de helft; een vlak ernaast geeft niets.
    _pand = {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10],
                                                 [0, 10], [0, 0]]]}
    _half = {"type": "MultiPolygon", "coordinates": [[[[-5, -5], [5, -5],
                                                       [5, 15], [-5, 15],
                                                       [-5, -5]]]]}
    _naast = {"type": "Polygon", "coordinates": [[[20, 0], [30, 0], [30, 10],
                                                  [20, 10], [20, 0]]]}
    n_p, n_b = aandeel(_pand, _half)
    if n_p != 400 or n_b != 200 or aandeel(_pand, _naast)[1] != 0:
        afw.append(f"het aandeel van een pand in een vlak wordt verkeerd "
                   f"gemeten: {n_p}, {n_b}")
    for a in afw:
        print("AFWIJKING: " + a, file=sys.stderr)
    print(f"Proef monumenten: {len(afw)} afwijkingen", file=sys.stderr)
    return 1 if afw else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verken", action="store_true")
    ap.add_argument("--proef", action="store_true")
    ap.add_argument("--wfs", action="store_true")
    ap.add_argument("--rce", action="store_true")
    ap.add_argument("--rce-panden", action="store_true")
    ap.add_argument("--register-panden", action="store_true")
    a = ap.parse_args()
    if a.register_panden:
        return koppel_register_panden()
    if a.rce_panden:
        return koppel_rce_panden()
    if a.rce:
        return verken_rce()
    if a.wfs:
        return verken_wfs()
    if a.proef:
        return proef()
    if a.verken:
        return verken()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
