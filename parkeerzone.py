#!/usr/bin/env python3
"""
De parkeerzone onder elk pand, en wat er NIET uit de lagen te halen is.

WAAROM. De parkeernorm bestaat niet als enkel getal. In de binnenstad is hij
0,70 per woning waarvan 0,50 voor bewoners, in de schil 1e ring 1,25 voor
bepaalde koopcategorieen, en bij Hatertseweg 338 rekende de gemeente met 0,8
per wooneenheid. En in gereguleerd gebied kan de eis helemaal wegvallen: daar
krijgen nieuwe huisnummers geen parkeervergunning, dus stijgt de parkeerdruk
niet, dus geldt bij splitsen geen parkeereis. Behalve bij een toename van
bruto vloeroppervlak. Zie het blok "Parkeren bij splitsen" in bronnen.py.

Zonder de zone van een pand is elke parkeerberekening in de brief dus een gok,
en een gok die plausibel leest.

TWEE LAGEN, EN MAAR EEN ERVAN GEEFT ANTWOORD.

  MOB_PARKEERNORMERING   welke norm geldt hier. Dit werkt: 27 vlakken, veld
                         GEBIED met zes waarden, en 20.292 van de 20.321
                         adressen vallen in precies een vlak.

  MOB_BETAALD_PARKEREN   hier wilde ik weten of de parkeereis wegvalt, en dat
                         ZEGT DEZE LAAG NIET.

WAAROM NIET, EN HOE IK DAT ZAG. De eerste echte ronde gaf dat 4098 van de
6121 adressen in de Binnenstad buiten elk betaaldvlak liggen. Dat kan niet:
in de Nijmeegse binnenstad geldt overal betaald parkeren. De laag zelf legt
het uit: van de 33 vlakken zijn sommige gebieden (Centrum met 160 punten, 1e
ring met 177, de lettergebieden D tot Z) en andere LOSSE PARKEERGARAGES (P8
Vierdaagseplein met 5 punten, Lage Markt met 5, Doddendaal met 7, Radboud
UMC). Een punt in zo'n vlak betekent dus "hier ligt een parkeerplek", niet
"dit adres ligt in gereguleerd gebied". In een voetgangersgebied zonder
parkeervakken valt een woning er buiten terwijl er wel degelijk betaald
parkeren geldt.

DAAROM HEET HET VELD NIET MEER betaald_parkeren MAAR betaald_parkeervlak, en
draagt het de naam van het vlak in plaats van waar of onwaar. Een waar/onwaar
veld met die naam leest als "hier valt de parkeereis weg", en dat is precies
de bewering die de laag niet waarmaakt. Het was een getal dat klopt zolang
niemand het nameet.

WAT DE JUISTE BRON WAARSCHIJNLIJK IS: de gebieden waar parkeervergunningen
worden uitgegeven, de belanghebbendengebieden. Die staan hier als
lettergebieden in ZONE_NAAM maar door elkaar met de garages, dus ze zijn er
wel uit te halen zodra is vastgesteld welke namen gebieden zijn. Dat is niet
uit deze laag alleen te bepalen en wacht op een bron die het zegt.

WAT DEZE MODULE NIET DOET: aannemen hoe die lagen eruitzien. Ik kan
services.nijmegen.nl vanuit de werkomgeving niet bereiken, dus ken ik de
veldnamen niet. Een module die een veldnaam raadt, levert een zone op die
klopt zolang niemand hem nameet, en dat is deze week drie keer gebeurd.
Daarom:

  --verken   haalt de laag op en zegt wat erin zit: aantal vlakken, de
             velden met hun verschillende waarden, het geometrietype en de
             omhullende doos. Die uitkomst gaat naar een digestbestand, want
             het joblogboek van GitHub is van buiten de runner niet te lezen.
  --koppel   kent de zone toe aan elk pand met een punt. Kan het zonefeld
             niet worden vastgesteld, dan gebeurt er niets en zegt de module
             waarom.

DE ASVOLGORDE WORDT GEMETEN EN NIET AANGENOMEN. In WFS 1.0.0 levert GeoServer
EPSG:4326 als lengte-breedte, in 1.1.0 omgekeerd. Dat is een bekende val, dus
deze module kijkt waar de vlakken liggen: valt het midden buiten Nijmegen maar
past het na omwisselen wel, dan wisselt zij om en meldt dat.
"""

import argparse
import json
import os
import re
import sys
import urllib.parse

try:
    import requests
except Exception:                                    # pragma: no cover
    requests = None

BASIS = "https://services.nijmegen.nl/geoservices/extern_Mobiliteit/ows"
LAGEN = {
    "normering": "extern_Mobiliteit:MOB_PARKEERNORMERING",
    # MET EEN LIGGEND STREEPJE. Ik schreef hier MOB_BETAALDPARKEREN, en de
    # dienst antwoordde met een ServiceExceptionReport in XML. De
    # verkenning meldde dat in het verslag in plaats van stil niets te
    # doen, en zo was de naam in een ronde gevonden. Precies waarvoor die
    # verkenningsstand bestaat.
    "betaald": "extern_Mobiliteit:MOB_BETAALD_PARKEREN",
}
# DE VERGUNNINGENZONES UIT HET BESLUIT, EN NIET UIT DE KAART.
#
# Op 14 oktober schreef ik dat het gereguleerde gebied uit de gepubliceerde
# lagen niet te bepalen is. Mark vroeg of dat dan nergens in de beleidsstukken
# staat. Het staat er wel, en in het kanaal dat wij al dagelijks lezen: het
# Besluit tot aanwijzing en uitwerking betaald parkeren, dat jaarlijks als
# gemeenteblad wordt gepubliceerd. Artikel 1 definieert het gereguleerd
# vergunningengebied als de gebieden van artikel 2, en artikel 2 wijst die
# negentien zones met naam aan. Daar hangt de vrijstelling bij splitsen aan:
# in dat gebied krijgen nieuwe huisnummers geen parkeervergunning.
#
# HET BESLUIT EN DE KAART ZIJN NIET GELIJK, en dat is nagemeten op de laag van
# 14 oktober:
#   uit artikel 2, niet in de kaart: B, I, T, U
#   in de kaart, niet in artikel 2:  D, V
# De overige veertien namen in de kaart zijn parkeerterreinen uit artikel 15
# lid d, zoals P8 Vierdaagseplein en De Oude Haven, en die zijn geen
# vergunningenzone. Een punt in zo'n terrein zegt niets over het adres.
#
# Daarom drie uitkomsten en geen twee: ja (de naam staat in artikel 2), nee
# (het is een parkeerterrein) en onbekend (D en V staan in de kaart maar niet
# in dit besluit; welk besluit ze aanwijst weet ik niet).
VERGUNNINGENZONES = [
    "Centrum", "B", "1e ring", "2e ring west", "2e ring oost",
    "I", "J", "K", "L", "P", "Q", "R", "S", "T", "U", "W", "X", "Y", "Z",
]
# In de kaart, niet in artikel 2 van het besluit van 2025.
ONBEKENDE_ZONES = ["D", "V"]

VOORRAAD = "voorraad.json"
ZONES = "parkeerzones.json"

# Nijmegen, ruim genomen. De WFS zelf geeft als omhullende doos in RD
# 180337,422322 tot 191124,434316, en dat is ongeveer 5,74 tot 5,90 oost en
# 51,76 tot 51,87 noord. Deze doos is daar ruimer dan nodig, want hij dient
# alleen om een omgewisselde asvolgorde te betrappen.
DOOS = (5.5, 51.6, 6.2, 52.0)


def url_van(laag, formaat="application/json"):
    vraag = {
        "service": "WFS", "version": "1.0.0", "request": "GetFeature",
        "typeName": laag, "outputFormat": formaat,
        # EPSG:4326 omdat onze punten uit PDOK in CRS84 staan. Omrekenen naar
        # RD zou een tweede bron van fouten zijn, en precies bij een zonegrens
        # telt elke meter.
        "srsName": "EPSG:4326",
    }
    return BASIS + "?" + urllib.parse.urlencode(vraag)


def haal(laag, pauze=30):
    """De laag ophalen. Geeft (data, fout) terug."""
    if requests is None:
        return None, "requests ontbreekt"
    try:
        r = requests.get(url_van(laag), timeout=pauze)
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:120]}"
    if r.status_code != 200:
        return None, f"http {r.status_code}: {r.text[:160]}"
    try:
        return r.json(), ""
    except Exception as e:
        # EEN BESTAANDE DIENST MET EEN ONBEKENDE LAAG ANTWOORDT MET XML, niet
        # met een foutcode: http 200 en een ServiceExceptionReport in de body.
        # Zonder deze regel staat er "geen json" met een stuk XML erachter, en
        # dan is de oorzaak nog zoekwerk. Zo stond het op 14 oktober in het
        # verslag en kostte het een minuut om te zien dat de laagnaam fout was.
        if "ServiceExceptionReport" in (r.text or ""):
            # (?!Report) EN [^<]: zonder het eerste pakt dit de buitenste
            # tag <ServiceExceptionReport ...> en begint de melding met de
            # binnenste tag erin; zonder het tweede loopt hij door de
            # volgende tag heen. De proef hier betrapte beide.
            reden = re.search(r"<ServiceException(?!Report)[^>]*>\s*"
                              r"([^<]{0,200})", r.text, re.S)
            return None, ("de dienst kent deze laag niet onder deze naam: "
                          + " ".join((reden.group(1) if reden else "").split())
                          [:160])
        return None, f"geen json: {str(e)[:120]} ({r.text[:120]})"


def soort_zone(naam):
    """
    Is dit een vergunningenzone uit artikel 2, of een parkeerterrein?

    Geeft "vergunningenzone", "onbekend" of "parkeerterrein". Het verschil
    bepaalt of de vrijstelling bij splitsen in beeld komt, dus het mag geen
    waar/onwaar zijn met onbekend erin verstopt.
    """
    kaal = (naam or "").strip()
    if kaal in VERGUNNINGENZONES:
        return "vergunningenzone"
    if kaal in ONBEKENDE_ZONES:
        return "onbekend"
    return "parkeerterrein"


def _ringen(geometrie):
    """De buitenringen van een vlak of van een verzameling vlakken."""
    soort = (geometrie or {}).get("type") or ""
    co = (geometrie or {}).get("coordinates") or []
    if soort == "Polygon":
        return [co[0]] if co else []
    if soort == "MultiPolygon":
        return [deel[0] for deel in co if deel]
    return []


def _midden(ringen):
    punten = [p for ring in ringen for p in ring
              if isinstance(p, (list, tuple)) and len(p) >= 2]
    if not punten:
        return None
    return (sum(p[0] for p in punten) / len(punten),
            sum(p[1] for p in punten) / len(punten))


def _in_doos(x, y, doos=DOOS):
    return doos[0] <= x <= doos[2] and doos[1] <= y <= doos[3]


def vlakken_uit(data):
    """
    De vlakken uit een GeoJSON, met de asvolgorde gemeten.

    Geeft (vlakken, verwisseld, overgeslagen) terug. Een vlak is
    (eigenschappen, ringen).
    """
    kenmerken = (data or {}).get("features") or []
    ruw = []
    for k in kenmerken:
        ringen = _ringen(k.get("geometry"))
        if ringen:
            ruw.append((k.get("properties") or {}, ringen))
    if not ruw:
        return [], False, len(kenmerken)
    # DE ASVOLGORDE METEN. Past het midden van de eerste vlakken in de doos om
    # Nijmegen, dan staat lengtegraad voorop. Past het alleen omgewisseld, dan
    # heeft de dienst breedtegraad voorop gezet en wisselen wij om.
    goed = omgekeerd = 0
    for _, ringen in ruw[:40]:
        m = _midden(ringen)
        if not m:
            continue
        if _in_doos(m[0], m[1]):
            goed += 1
        elif _in_doos(m[1], m[0]):
            omgekeerd += 1
    verwisseld = omgekeerd > goed
    if verwisseld:
        ruw = [(e, [[[p[1], p[0]] for p in ring] for ring in ringen])
               for e, ringen in ruw]
    return ruw, verwisseld, len(kenmerken) - len(ruw)


def in_vlak(punt, ring):
    """
    Ligt het punt in deze ring? Straalmethode, met de rand meegerekend.

    De rand komt hier zelden voor en de keuze is willekeurig, maar hij moet
    wel vastliggen: anders hangt de zone van een pand aan afrondingsruis.
    """
    x, y = punt[0], punt[1]
    binnen = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > y) != (y2 > y):
            if y2 != y1:
                snij = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
                if x < snij:
                    binnen = not binnen
    return binnen


def vlak_van(punt, vlakken):
    """De eigenschappen van het eerste vlak waarin dit punt valt, of None."""
    for eigenschappen, ringen in vlakken:
        for ring in ringen:
            if in_vlak(punt, ring):
                return eigenschappen
    return None


def waarden_per_veld(vlakken, maximaal=12):
    """Per veld de verschillende waarden, voor de verkenning."""
    uit = {}
    for eigenschappen, _ in vlakken:
        for veld, waarde in (eigenschappen or {}).items():
            uit.setdefault(veld, set()).add(
                str(waarde)[:60] if waarde is not None else "")
    return {veld: sorted(w)[:maximaal] for veld, w in sorted(uit.items())}


def zonefeld(vlakken, maximaal=25):
    """
    Welk veld de zonenaam bevat, afgeleid uit de inhoud en niet uit de naam.

    EEN NAAM RADEN IS HET PROBLEEM, NIET DE OPLOSSING. Ik ken de velden van
    deze laag niet, dus kies ik op eigenschappen van de inhoud:
      - de waarden zijn tekst, niet een getal
      - er zijn er meer dan een, anders zegt het veld niets
      - er zijn er niet te veel, want dan is het een nummer per vlak
      - geen waarde is leeg

    Blijven er meer velden over, dan kiest deze functie NIET. Zij geeft de
    kandidaten terug en de koppelstap doet niets, want een verkeerd veld
    levert een parkeernorm op die klopt zolang niemand hem nameet.
    """
    aantal = len(vlakken)
    if not aantal:
        return "", []
    kandidaten = []
    for veld, waarden in waarden_per_veld(vlakken, maximaal=10 ** 6).items():
        if any(w == "" for w in waarden):
            continue
        if len(waarden) < 2 or len(waarden) > min(maximaal, aantal):
            continue
        if all(w.replace(".", "").replace(",", "").replace("-", "").isdigit()
               for w in waarden):
            continue
        kandidaten.append(veld)
    if len(kandidaten) == 1:
        return kandidaten[0], kandidaten
    return "", kandidaten


def verken(laag, naam):
    """Zeggen wat er in een laag zit, zonder iets te veronderstellen."""
    data, fout = haal(laag)
    if fout:
        return {"laag": naam, "fout": fout}
    vlakken, verwisseld, overgeslagen = vlakken_uit(data)
    veld, kandidaten = zonefeld(vlakken)
    soorten = sorted({(k.get("geometry") or {}).get("type") or "geen"
                      for k in (data.get("features") or [])})
    doos = None
    alle = [p for _, ringen in vlakken for ring in ringen for p in ring]
    if alle:
        doos = [round(min(p[0] for p in alle), 5),
                round(min(p[1] for p in alle), 5),
                round(max(p[0] for p in alle), 5),
                round(max(p[1] for p in alle), 5)]
    return {"laag": naam, "fout": "", "vlakken": len(vlakken),
            "overgeslagen": overgeslagen, "verwisseld": verwisseld,
            "geometrietypen": soorten, "doos": doos,
            "crs": (data.get("crs") or {}).get("properties", {}).get("name")
                   or data.get("crs") or "niet vermeld",
            "zonefeld": veld, "kandidaten": kandidaten,
            "velden": waarden_per_veld(vlakken)}


def verslag(standen):
    """De verkenning als markdown, want een digest kunnen wij lezen."""
    r = ["## Parkeerzones: wat er in de lagen zit", ""]
    for s in standen:
        r.append(f"### {s['laag']}")
        if s.get("fout"):
            r.append(f"- NIET OPGEHAALD: {s['fout']}")
            r.append("")
            continue
        r.append(f"- {s['vlakken']} vlakken, "
                 f"{s['overgeslagen']} zonder bruikbare geometrie")
        r.append(f"- geometrietypen: {', '.join(s['geometrietypen'])}")
        r.append(f"- crs zoals vermeld: {s['crs']}")
        r.append(f"- omhullende doos: {s['doos']}")
        r.append(f"- asvolgorde omgewisseld: "
                 f"{'ja' if s['verwisseld'] else 'nee'}")
        if s["zonefeld"]:
            r.append(f"- zonefeld: **{s['zonefeld']}**")
        else:
            r.append(f"- zonefeld NIET vast te stellen; kandidaten: "
                     f"{s['kandidaten'] or 'geen'}")
        r.append("- velden en hun waarden:")
        for veld, waarden in s["velden"].items():
            r.append(f"  - `{veld}`: {', '.join(waarden) or '(leeg)'}")
        r.append("")
    return "\n".join(r)


def koppel(voorraad_pad=VOORRAAD, zones_pad=ZONES):
    """
    De zone bij elk pand met een punt zetten, plus het betaaldparkeervlak.

    Wat hier NIET gebeurt: een pand zonder punt een zone geven. Zie
    punt_uit() in voorraad_bag.py voor waarom een geraden punt erger is dan
    geen punt.
    """
    try:
        with open(voorraad_pad, encoding="utf-8") as f:
            voorraad = json.load(f)
    except Exception as e:
        return {"fout": f"{voorraad_pad} niet te lezen: {str(e)[:80]}"}
    try:
        with open(zones_pad, encoding="utf-8") as f:
            opgeslagen = json.load(f)
    except Exception as e:
        return {"fout": f"{zones_pad} niet te lezen: {str(e)[:80]}"}

    normvlakken, _, _ = vlakken_uit(opgeslagen.get("normering"))
    betaaldvlakken, _, _ = vlakken_uit(opgeslagen.get("betaald"))
    veld, kandidaten = zonefeld(normvlakken)
    if not veld:
        return {"fout": "het zonefeld is niet vast te stellen",
                "kandidaten": kandidaten}

    tel = {"met_punt": 0, "zonder_punt": 0, "in_een_zone": 0,
           "buiten_elke_zone": 0, "in_een_betaaldvlak": 0}
    per_zone = {}
    for groep in ("adressen", "niet_woningen", "pijplijn"):
        for rec in (voorraad.get(groep) or {}).values():
            punt = rec.get("punt")
            if not punt:
                tel["zonder_punt"] += 1
                continue
            tel["met_punt"] += 1
            eigenschappen = vlak_van(punt, normvlakken)
            if eigenschappen is None:
                tel["buiten_elke_zone"] += 1
                # Weghalen en niet laten staan: een oude zone bij een pand dat
                # nu buiten elke zone valt, is een stille onwaarheid.
                rec.pop("parkeerzone", None)
            else:
                zone = str(eigenschappen.get(veld) or "")
                rec["parkeerzone"] = zone
                tel["in_een_zone"] += 1
                per_zone[zone] = per_zone.get(zone, 0) + 1
            # HET VELD HEET NAAR WAT HET MEET EN NIET NAAR WAT WIJ WILLEN
            # WETEN. Dit heette betaald_parkeren, en dat beweerde te veel.
            # Zie de uitleg bij koppel() hieronder: de laag mengt gebieden met
            # losse parkeergarages, en 4098 van de 6121 adressen in de
            # Binnenstad vallen er buiten. Wat dit veld zegt is: op dit punt
            # ligt een vlak uit de laag betaald parkeren, en welk.
            if betaaldvlakken:
                vlak = vlak_van(punt, betaaldvlakken)
                if vlak is None:
                    rec.pop("betaald_parkeervlak", None)
                    rec.pop("betaald_parkeren", None)
                else:
                    naam = str(vlak.get("ZONE_NAAM")
                               or vlak.get("TARIEF_ZONE") or "ja")
                    rec["betaald_parkeervlak"] = naam
                    rec.pop("betaald_parkeren", None)
                    tel["in_een_betaaldvlak"] += 1
                    # DE AARD VAN HET VLAK ERBIJ. Zie soort_zone(): alleen een
                    # vergunningenzone uit artikel 2 van het besluit zegt iets
                    # over het adres; een parkeerterrein is een plek.
                    soort = soort_zone(naam)
                    rec["vlak_soort"] = soort
                    tel[soort] = tel.get(soort, 0) + 1
            else:
                rec.pop("betaald_parkeervlak", None)
                rec.pop("betaald_parkeren", None)

    with open(voorraad_pad, "w", encoding="utf-8") as f:
        json.dump(voorraad, f, ensure_ascii=False)
    return {"fout": "", "zonefeld": veld, "per_zone": per_zone, **tel}


def proef():
    fouten = []

    # DE STRAALMETHODE OP EEN VIERKANT. Binnen, buiten, en net erbuiten.
    vierkant = [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0]]
    for punt, hoort in (([1.0, 1.0], True), ([3.0, 1.0], False),
                        ([-1.0, 1.0], False), ([1.0, 3.0], False),
                        ([1.9999, 1.9999], True)):
        if in_vlak(punt, vierkant) != hoort:
            fouten.append(f"punt {punt} in een vierkant van 2 bij 2 geeft "
                          f"{in_vlak(punt, vierkant)} in plaats van {hoort}")

    # EEN VLAK MET EEN GAT ERIN wordt hier als buitenring behandeld, dus een
    # punt in het gat heet binnen. Dat staat hier opgeschreven omdat het een
    # keuze is: parkeerzones hebben geen gaten, en zou dat veranderen, dan
    # moet deze proef omvallen in plaats van de brief.
    met_gat = {"type": "Polygon", "coordinates": [
        vierkant,
        [[0.5, 0.5], [1.5, 0.5], [1.5, 1.5], [0.5, 1.5], [0.5, 0.5]]]}
    ringen = _ringen(met_gat)
    if len(ringen) != 1:
        fouten.append(f"een vlak met een gat levert {len(ringen)} ringen in "
                      f"plaats van alleen de buitenring")

    # EEN VERZAMELING VLAKKEN. Twee losse gebieden, een zone.
    multi = {"type": "MultiPolygon", "coordinates": [
        [vierkant],
        [[[10.0, 10.0], [12.0, 10.0], [12.0, 12.0], [10.0, 12.0],
          [10.0, 10.0]]]]}
    if len(_ringen(multi)) != 2:
        fouten.append("een MultiPolygon levert niet twee ringen")

    # DE ASVOLGORDE GEMETEN. Nijmegen in de juiste volgorde blijft staan;
    # omgewisseld wordt omgedraaid. Zonder deze meting zou een zone worden
    # gezocht in de Indische Oceaan en viel elk pand buiten elke zone: een
    # brief zonder parkeerregel in plaats van een foute.
    def _vlak(ring, naam):
        return {"type": "Feature", "properties": {"ZONE": naam},
                "geometry": {"type": "Polygon", "coordinates": [ring]}}

    binnenstad = [[5.86, 51.84], [5.88, 51.84], [5.88, 51.85],
                  [5.86, 51.85], [5.86, 51.84]]
    schil = [[5.88, 51.84], [5.90, 51.84], [5.90, 51.85], [5.88, 51.85],
             [5.88, 51.84]]
    goed = {"features": [_vlak(binnenstad, "Binnenstad"),
                         _vlak(schil, "Schil 1e ring")]}
    vlakken, verwisseld, over = vlakken_uit(goed)
    if verwisseld or over or len(vlakken) != 2:
        fouten.append(f"een laag in de juiste asvolgorde wordt aangepast: "
                      f"verwisseld={verwisseld}, overgeslagen={over}, "
                      f"{len(vlakken)} vlakken")
    omgedraaid = {"features": [
        {"type": "Feature", "properties": {"ZONE": "Binnenstad"},
         "geometry": {"type": "Polygon",
                      "coordinates": [[[p[1], p[0]] for p in binnenstad]]}}]}
    vlakken_om, verwisseld_om, _ = vlakken_uit(omgedraaid)
    if not verwisseld_om:
        fouten.append("een omgewisselde asvolgorde wordt niet opgemerkt; dan "
                      "valt elk pand buiten elke zone en verdwijnt de "
                      "parkeerregel stil uit de brief")
    elif not in_vlak([5.87, 51.845], vlakken_om[0][1][0]):
        fouten.append("na het omwisselen valt een punt in de binnenstad niet "
                       "meer in de binnenstad")

    # HET ZONEFELD UIT DE INHOUD. Het echte geval is onbekend, dus wordt hier
    # getoetst wat de regel moet doen: een tekstveld met een paar waarden is
    # de zone, een nummer per vlak niet, en bij twijfel kiest hij niet.
    def _met(eigenschappen):
        return [(e, [vierkant]) for e in eigenschappen]

    duidelijk = _met([{"ZONE": "Binnenstad", "ID": "1", "OPP": "1200"},
                      {"ZONE": "Schil", "ID": "2", "OPP": "3400"},
                      {"ZONE": "Binnenstad", "ID": "3", "OPP": "900"}])
    veld, kandidaten = zonefeld(duidelijk)
    if veld != "ZONE":
        fouten.append(f"het zonefeld wordt niet gevonden: {veld!r}, "
                      f"kandidaten {kandidaten}")
    # Twee tekstvelden die beide kunnen: dan niet kiezen.
    dubbel = _met([{"ZONE": "Binnenstad", "GEBIED": "Centrum"},
                   {"ZONE": "Schil", "GEBIED": "Oost"}])
    veld2, kandidaten2 = zonefeld(dubbel)
    if veld2 or sorted(kandidaten2) != ["GEBIED", "ZONE"]:
        fouten.append(f"bij twee mogelijke velden wordt toch gekozen: "
                      f"{veld2!r} uit {kandidaten2}")
    # Een veld met een eigen waarde per vlak is een nummer en geen zone.
    uniek = _met([{"NAAM": f"vlak {i}"} for i in range(40)])
    veld3, _ = zonefeld(uniek)
    if veld3:
        fouten.append(f"een veld met een eigen waarde per vlak wordt als "
                      f"zone gekozen: {veld3!r}")

    # DE KOPPELING OP EEN ECHTE VOORRAADVORM, met een pand in de binnenstad,
    # een in de schil, een buiten elke zone en een zonder punt.
    import tempfile
    with tempfile.TemporaryDirectory() as m:
        vp = os.path.join(m, "voorraad.json")
        zp = os.path.join(m, "zones.json")
        # DE ECHTE VELDNAMEN VAN DE LAAG, uit de verkenning van 14 oktober:
        # ZONE_NAAM en TARIEF_ZONE. Eerst stond hier ZONE, een naam die ik zelf
        # had bedacht, en dan toetst de proef mijn eigen verzinsel.
        betaald = {"features": [
            {"type": "Feature",
             "properties": {"ZONE_NAAM": "Gereguleerd",
                            "TARIEF_ZONE": "Centrum"},
             "geometry": {"type": "Polygon", "coordinates": [binnenstad]}}]}
        with open(zp, "w", encoding="utf-8") as f:
            json.dump({"normering": goed, "betaald": betaald}, f)
        with open(vp, "w", encoding="utf-8") as f:
            json.dump({"adressen": {
                "a": {"adres": "In de binnenstad 1", "punt": [5.87, 51.845]},
                "b": {"adres": "In de schil 2", "punt": [5.89, 51.845]},
                "c": {"adres": "Ver weg 3", "punt": [5.70, 51.80]},
                "d": {"adres": "Zonder punt 4"},
                # Een pand dat eerder een zone kreeg en er nu buiten valt.
                "e": {"adres": "Was een zone 5", "punt": [5.70, 51.80],
                      "parkeerzone": "Binnenstad"},
                # Een record uit een eerdere ronde, met het oude veld erin.
                "f": {"adres": "Oud veld 6", "punt": [5.87, 51.845],
                      "betaald_parkeren": True},
            }}, f)
        uit = koppel(vp, zp)
        with open(vp, encoding="utf-8") as f:
            na = json.load(f)["adressen"]
        if uit.get("fout"):
            fouten.append(f"de koppeling mislukte: {uit['fout']}")
        if na["a"].get("parkeerzone") != "Binnenstad":
            fouten.append(f"het pand in de binnenstad krijgt zone "
                          f"{na['a'].get('parkeerzone')!r}")
        if na["b"].get("parkeerzone") != "Schil 1e ring":
            fouten.append(f"het pand in de schil krijgt zone "
                          f"{na['b'].get('parkeerzone')!r}")
        if "parkeerzone" in na["c"]:
            fouten.append(f"een pand buiten elke zone krijgt er toch een: "
                          f"{na['c'].get('parkeerzone')!r}")
        if "parkeerzone" in na["d"] or "betaald_parkeren" in na["d"]:
            fouten.append("een pand zonder punt krijgt een zone")
        if "parkeerzone" in na["e"]:
            fouten.append(f"een oude zone blijft staan bij een pand dat nu "
                          f"buiten elke zone valt: "
                          f"{na['e'].get('parkeerzone')!r}")
        # HET VELD NOEMT HET VLAK EN NIET EEN JA OF NEE. Een waar/onwaar veld
        # met de naam betaald_parkeren leest als "hier valt de parkeereis
        # weg", en dat is iets anders dan wat de laag meet.
        # EEN VERGUNNINGENZONE UIT ARTIKEL 2, EEN ONBEKENDE EN EEN TERREIN.
        # Dit is het verschil waar de vrijstelling aan hangt, dus het hoort
        # per vlak uit elkaar gehouden te worden.
        for naam, hoort in (("Centrum", "vergunningenzone"),
                            ("Z", "vergunningenzone"),
                            ("1e ring", "vergunningenzone"),
                            ("D", "onbekend"), ("V", "onbekend"),
                            ("P8 Vierdaagseplein", "parkeerterrein"),
                            ("De Oude Haven", "parkeerterrein"),
                            ("", "parkeerterrein")):
            if soort_zone(naam) != hoort:
                fouten.append(f"{naam or '(leeg)'} heet {soort_zone(naam)!r} "
                              f"in plaats van {hoort!r}")
        if na["a"].get("betaald_parkeervlak") != "Gereguleerd":
            fouten.append(f"het vlak uit de laag betaald parkeren wordt niet "
                          f"bij naam bewaard: "
                          f"{na['a'].get('betaald_parkeervlak')!r}")
        if na["a"].get("vlak_soort") != "parkeerterrein":
            fouten.append(f"een vlak met een naam die niet in artikel 2 staat "
                          f"heet toch vergunningenzone: "
                          f"{na['a'].get('vlak_soort')!r}")
        if "betaald_parkeervlak" in na["b"]:
            fouten.append(f"een pand buiten elk betaaldvlak krijgt er toch "
                          f"een: {na['b'].get('betaald_parkeervlak')!r}")
        # OP RECORD f, want dat is het enige dat het oude veld HAD. Eerst
        # keek deze regel naar a en b, die het nooit hadden, dus was het
        # weghalen daar een lege handeling en bleef de breuk stil.
        for _sl in ("a", "b", "e", "f"):
            if "betaald_parkeren" in na[_sl]:
                fouten.append(f"het oude veld betaald_parkeren blijft staan "
                              f"bij {_sl}; dan leest een record uit een "
                              f"eerdere ronde als een uitspraak over de "
                              f"parkeereis")
        if na["f"].get("betaald_parkeervlak") != "Gereguleerd":
            fouten.append(f"het record met het oude veld krijgt geen nieuw "
                          f"veld: {na['f'].get('betaald_parkeervlak')!r}")
        if (uit.get("in_een_zone"), uit.get("buiten_elke_zone"),
                uit.get("zonder_punt"),
                uit.get("in_een_betaaldvlak")) != (3, 2, 1, 2):
            fouten.append(
                f"de tellingen kloppen niet: {uit.get('in_een_zone')} in een "
                f"zone, {uit.get('buiten_elke_zone')} buiten, "
                f"{uit.get('zonder_punt')} zonder punt, "
                f"{uit.get('in_een_betaaldvlak')} in een betaaldvlak; "
                f"verwacht 3, 2, 1, 2")

        # EN ZONDER VAST ZONEFELD GEBEURT ER NIETS. Liever geen zone dan een
        # zone uit het verkeerde veld.
        with open(zp, "w", encoding="utf-8") as f:
            json.dump({"normering": {"features": [
                {"type": "Feature",
                 "properties": {"ZONE": "Binnenstad", "GEBIED": "Centrum"},
                 "geometry": {"type": "Polygon",
                              "coordinates": [binnenstad]}},
                {"type": "Feature",
                 "properties": {"ZONE": "Schil", "GEBIED": "Oost"},
                 "geometry": {"type": "Polygon", "coordinates": [schil]}},
            ]}, "betaald": betaald}, f)
        uit2 = koppel(vp, zp)
        if not uit2.get("fout"):
            fouten.append("zonder vast zonefeld wordt er toch gekoppeld")

    # HET VERSLAG MOET DE REDEN NOEMEN als een laag niet is opgehaald, want
    # "niet opgehaald" en "geen vlakken gevonden" zijn twee dingen.
    tekst = verslag([{"laag": "normering", "fout": "http 500"}])
    if "NIET OPGEHAALD" not in tekst or "http 500" not in tekst:
        fouten.append(f"het verslag verzwijgt waarom een laag mislukte: "
                      f"{tekst[:120]!r}")

    # EEN ONBEKENDE LAAGNAAM HEET EEN ONBEKENDE LAAGNAAM. Dit is het echte
    # antwoord van 14 oktober op MOB_BETAALDPARKEREN: http 200 met XML in de
    # body in plaats van een foutcode. De tekst is ingekort maar niet
    # aangepast.
    class _Antwoord:
        status_code = 200
        text = ('<?xml version="1.0" ?>\n<ServiceExceptionReport\n'
                '   version="1.2.0"\n   xmlns="http://www.opengis.net/ogc">\n'
                '  <ServiceException>Could not locate '
                '{http://extern_Mobiliteit}MOB_BETAALDPARKEREN in catalog.'
                '</ServiceException>\n</ServiceExceptionReport>')

        def json(self):
            raise ValueError("Expecting value: line 1 column 1 (char 0)")

    _oud, globals()["requests"] = requests, type(
        "_Nep", (), {"get": staticmethod(lambda *a, **k: _Antwoord())})()
    try:
        _data, _fout = haal("extern_Mobiliteit:BESTAAT_NIET")
    finally:
        globals()["requests"] = _oud
    if _data is not None or "kent deze laag niet" not in _fout:
        fouten.append(f"een onbekende laagnaam wordt niet als zodanig "
                      f"gemeld: {_fout!r}")
    if "ServiceExceptionReport" in _fout or "<?xml" in _fout:
        fouten.append(f"de melding is ruwe XML in plaats van een reden: "
                      f"{_fout[:80]!r}")

    for f in fouten:
        print(f"FOUT {f}", file=sys.stderr)
    print(f"Proef: {len(fouten)} fouten", file=sys.stderr)
    return 1 if fouten else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proef", action="store_true")
    ap.add_argument("--verken", action="store_true",
                    help="de lagen ophalen en zeggen wat erin zit")
    ap.add_argument("--koppel", action="store_true",
                    help="de zone bij elk pand met een punt zetten")
    ap.add_argument("--uit", default="",
                    help="pad voor het verslag van de verkenning")
    args = ap.parse_args()
    if args.proef:
        return proef()

    if args.verken:
        standen = [verken(laag, naam) for naam, laag in sorted(LAGEN.items())]
        tekst = verslag(standen)
        print(tekst)
        if args.uit:
            with open(args.uit, "w", encoding="utf-8") as f:
                f.write(tekst + "\n")
        # De lagen zelf bewaren, zodat --koppel geen tweede keer hoeft te
        # vragen en de koppeling ook zonder netwerk na te meten is.
        bewaar = {}
        for naam, laag in sorted(LAGEN.items()):
            data, fout = haal(laag)
            if not fout:
                bewaar[naam] = data
        if bewaar:
            with open(ZONES, "w", encoding="utf-8") as f:
                json.dump(bewaar, f, ensure_ascii=False)
            print(f"{len(bewaar)} lagen bewaard in {ZONES}", file=sys.stderr)
        # Een laag die niet is opgehaald is een mislukking, en die hoort niet
        # groen te staan.
        return 1 if any(s.get("fout") for s in standen) else 0

    if args.koppel:
        uit = koppel()
        print(json.dumps(uit, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1 if uit.get("fout") else 0

    print("Kies --verken, --koppel of --proef.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    # sys.exit en niet main(): anders is de exitcode altijd 0 en is de poort
    # in de workflow een formaliteit.
    sys.exit(main())
