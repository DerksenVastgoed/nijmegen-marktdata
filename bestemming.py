#!/usr/bin/env python3
"""
De bestemmingen uit het bestemmingsplan per pand in de ring, vooral de
dubbelbestemmingen.

WAAROM DIT BESTAAT. Groesbeekseweg 118A/B, 16 oktober 2026: een verdieping
boven een apotheek werd een woning, en het duurde 213 dagen. Het
bestemmingsplan stond het appartement toe, maar op die plek ligt ook de
dubbelbestemming 'Cultuurhistorie - 2' met een bouwverbod (artikel 19.2), en
de gemeente moest daar binnenplans van afwijken, na een akkoord van de
Adviescommissie Omgevingskwaliteit. Bij Bronsgeeststraat 11 en Heydenrijckstraat
40 was die stap er niet, en gold het omgevingsplan als vergunningsvrij. Voor
een aankoop bepaalt zo'n dubbelbestemming de doorlooptijd meer dan de
verbouwing zelf, en onze dossiers kenden alleen het beschermd stadsgezicht per
buurt.

DE BRON. De dataset "Ruimtelijke plannen (Wro)" van ruimtelijkeplannen.nl, via
PDOK als WMS, met een eigen laag 'dubbelbestemming' en een laag
'enkelbestemming'. Licentie CC-0. Niet jeleefomgeving.nl, dat geautomatiseerd
ophalen weigert. Twee voorbehouden van de bron zelf: de gegevens zijn niet
volledig en worden twee keer per jaar bijgewerkt, en plannen in de nieuwe
standaard (STOP/TPOD, het omgevingsplan zelf) staan er niet in. Voor wat
juridisch geldt verwijst de bron naar "Regels op de kaart" in het
Omgevingsloket. Wat dit script vindt is dus een aanwijzing om na te kijken, en
"niets gevonden" is niet hetzelfde als "geen dubbelbestemming".

HOE. Per pand één punt (het verblijfsobject uit de voorraad), en daarop een
GetFeatureInfo per laag. Het antwoord wordt bewaard in bestemmingen.json,
zodat een pand alleen opnieuw wordt gevraagd als er een laag bij is gekomen of
als het antwoord ouder is dan HERHAAL_DAGEN; de bron verandert twee keer per
jaar.

DE AANDUIDINGEN (28 november 2026). Smetiusstraat 15: café met kamerverhuur
wordt een hotel van 14 kamers, vergund op 25 november 2026 (Z2026-00002909).
Volgens de ruimtelijke onderbouwing kon dat zonder buitenplanse afwijking
omdat het pand binnen 'Gemengd - 3' de functieaanduiding 'horeca' heeft, en
logiesverstrekkende horeca ook op de verdiepingen mag. De enkelbestemming
alleen zegt dat dus niet: de aanduiding beslist. Daarom vraagt dit script nu
ook functieaanduiding, bouwaanduiding, gebiedsaanduiding en de naam van het
bestemmingsplan op. En het pand zelf stond niet in bestemmingen.json, omdat
de ronde alleen panden met een woning nam: 661 panden met alleen een
niet-woning (horeca, winkel, kantoor) ontbraken, en dat zijn juist de panden
waar een transformatie speelt. Die gaan nu mee.

  python3 bestemming.py --verken      # een handvol bekende panden, met het
                                      # ruwe antwoord in het verslag
  python3 bestemming.py --minuten 60  # de ring ophalen, hervatbaar
  python3 bestemming.py --zoek horeca # panden met die functieaanduiding
  python3 bestemming.py --proef
"""
import argparse
import datetime as dt
import json
import sys
import time
import urllib.parse
import urllib.request

WMS = "https://service.pdok.nl/kadaster/ruimtelijke-plannen/wms/v1_0"
AANDUIDINGEN = ("functieaanduiding", "bouwaanduiding", "gebiedsaanduiding")
# maatvoering (28 november): de maximale goot- en bouwhoogte en het
# bebouwingspercentage staan niet in de planregels maar op de verbeelding,
# volgens artikel 10.2.2 van Nijmegen Centrum - Binnenstad. Voor optoppen of
# een dakopbouw is dat het getal dat telt.
LAGEN = ("dubbelbestemming", "enkelbestemming") + AANDUIDINGEN + (
    "bestemmingsplangebied", "maatvoering", "plangebied")
UIT_PAD = "bestemmingen.json"
VERSLAG = "bestemming_verslag.md"
PAUZE = 0.2
# De bron wordt twee keer per jaar bijgewerkt; een antwoord ouder dan dit
# wordt opnieuw gevraagd, zodat een gewijzigd plan vanzelf binnenkomt.
HERHAAL_DAGEN = 183

# Panden waarvan we uit een besluit weten wat er ligt, om de bron aan te
# toetsen. Groesbeekseweg 118A: 'Cultuurhistorie - 2' volgens besluit
# Z2026-00001328. De andere twee zijn ter vergelijking; van die twee zegt het
# besluit alleen dat het omgevingsplan vergunningsvrij was.
BEKEND = {
    "Groesbeekseweg 118A": "Cultuurhistorie",
    "Bronsgeeststraat 11": None,
    "Heydenrijckstraat 40": None,
    # Z2026-00002909: 'Gemengd - 3' met functieaanduiding 'horeca' en
    # 'Waarde - Cultuurhistorie 2', volgens besluit en ruimtelijke
    # onderbouwing. Toets voor de nieuwe lagen.
    "Smetiusstraat 15": "Gemengd - 3, functieaanduiding horeca, "
                        "Cultuurhistorie 2",
}


def _verzoek(laag, lat, lon, opmaak="application/json"):
    """GetFeatureInfo op één punt, WMS 1.3.0 in WGS84 (as-volgorde lat, lon)."""
    d = 0.00005
    params = {
        "service": "WMS", "version": "1.3.0", "request": "GetFeatureInfo",
        "layers": laag, "query_layers": laag, "styles": "",
        "crs": "EPSG:4326",
        "bbox": f"{lat - d},{lon - d},{lat + d},{lon + d}",
        "width": "101", "height": "101", "i": "50", "j": "50",
        "info_format": opmaak, "feature_count": "10",
    }
    url = WMS + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "User-Agent": "NijmegenVastgoedMonitor/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def verwijzingen_uit(antwoord):
    """
    Per feature de naam, het plan, het artikelnummer en de link naar de
    planregels. None als het antwoord niet te lezen is, [] als er niets ligt.

    DE VELDEN ZIJN GEMETEN, 28 november 2026, met verken op vier panden en
    alle zes lagen (bestemming_verslag.md). Het veld is altijd 'naam'. De
    oude lezer nam ook elk veld met 'bestemming' in de sleutel of dat op
    'naam' eindigde, en las zo bij Smetiusstraat 15 'bestemmingsvlak'
    ("Enkelbestemming=NL.IMRO.0268.ID5198-00") als functieaanduiding, en bij
    Groesbeekseweg 118A 'locatienaam' (een zin over de plangrens) als
    plannaam.

    'verwijzingnaartekst' is de link naar het artikel in de planregels, en
    'plangebied' het plan waar de regel uit komt. Die twee maken de tabel met
    planregels mogelijk: dezelfde naam ('Gemengd - 3') kan in een ander plan
    iets anders betekenen. Bij aanduidingen is de link soms leeg; dan staat
    het artikel bij de bestemming waar de aanduiding in ligt.
    """
    try:
        d = json.loads(antwoord)
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    uit, gezien = [], set()
    for f in d.get("features") or []:
        props = (f or {}).get("properties") or {}
        naam = props.get("naam")
        if not isinstance(naam, str) or not naam.strip():
            continue
        v = {"naam": naam.strip(),
             "plan": (props.get("plangebied") or "").strip(),
             "artikel": (props.get("artikelnummer") or "").strip(),
             "tekst": (props.get("verwijzingnaartekst") or "").strip(),
             # Of de regel al geldt: een ontwerp of een voorbereidingsbesluit
             # staat in dezelfde lagen als het vastgestelde plan.
             "typeplan": (props.get("typeplan") or "").strip(),
             "planstatus": (props.get("planstatus") or "").strip()}
        # DE WAARDEN BIJ EEN MAATVOERING, gemeten 28 november met verken op
        # vier panden: het veld 'maatvoering' bevat ze als
        # "maximum bouwhoogte (m)"="13", "maximum goothoogte (m)"="10".
        # Een eerste versie zocht velden met 'waarde' of 'omvang' in de
        # sleutel en vond niets.
        maten = maten_uit(props.get("maatvoering"))
        if maten:
            v["maten"] = maten
        sleutel = (v["naam"], v["plan"], json.dumps(maten, sort_keys=True))
        if sleutel not in gezien:
            gezien.add(sleutel)
            uit.append(v)
    return uit


def maten_uit(tekst):
    """
    '"maximum bouwhoogte (m)"="13", "maximum goothoogte (m)"="10"' wordt
    {"maximum bouwhoogte (m)": "13", "maximum goothoogte (m)": "10"}.
    Leeg bij geen of onleesbare tekst.
    """
    import re
    if not isinstance(tekst, str):
        return {}
    return {k.strip(): w.strip()
            for k, w in re.findall(r'"([^"]+)"\s*=\s*"([^"]*)"', tekst)
            if k.strip() and w.strip()}


def namen_uit(antwoord):
    """De namen uit een GetFeatureInfo-antwoord, zie verwijzingen_uit."""
    v = verwijzingen_uit(antwoord)
    if v is None:
        return None
    namen = []
    for x in v:
        if x["naam"] not in namen:
            namen.append(x["naam"])
    return namen


def velden_uit(antwoord):
    """
    De properties van elk feature, zonder geometrie, voor het verslag.

    WAAROM. Tot 28 november ging het ruwe antwoord afgekapt op 600 tekens in
    het verslag; bij de aanduidingslagen viel die grens midden in de
    coördinaten, en de veldnamen waren niet te zien.
    """
    try:
        d = json.loads(antwoord)
    except Exception:
        return antwoord[:300]
    return json.dumps([(f or {}).get("properties") or {}
                       for f in d.get("features") or []],
                      ensure_ascii=False)


def punten_per_pand(pad="voorraad.json", met_niet_woningen=False):
    """
    Per pand in de ring één punt (lat, lon) en een adres.

    met_niet_woningen neemt ook de panden met alleen een niet-woning mee
    (horeca, winkel, kantoor). Standaard uit, omdat gezicht.py deze functie
    ook gebruikt en zijn telling op de woonpanden heeft gemeten; de ronde
    hier zet hem aan. Een pand met een woning houdt het punt van de woning.
    """
    with open(pad, encoding="utf-8") as f:
        v = json.load(f)
    uit = {}
    delen = ("adressen", "niet_woningen") if met_niet_woningen else (
        "adressen",)
    for deel in delen:
        for rec in (v.get(deel) or {}).values():
            if rec.get("herkomst") != "focusbuurt":
                continue
            p, punt = rec.get("pand"), rec.get("punt")
            if p and punt and len(punt) == 2 and p not in uit:
                uit[p] = {"lat": punt[1], "lon": punt[0],
                          "adres": rec.get("adres")}
    return uit


def te_vragen(rec, vandaag=None):
    """
    Welke lagen voor een pand nog gevraagd moeten worden.

    Geen record of een antwoord ouder dan HERHAAL_DAGEN: alle lagen. Anders
    alleen de lagen die er nog niet in staan (None telt als gevraagd maar
    onleesbaar, en wordt bij de volgende verversing opnieuw gevraagd).
    """
    if not rec:
        return list(LAGEN)
    vandaag = vandaag or dt.date.today()
    try:
        gezien = dt.date.fromisoformat(rec.get("gezien") or "")
    except ValueError:
        return list(LAGEN)
    if (vandaag - gezien).days > HERHAAL_DAGEN:
        return list(LAGEN)
    # Een record zonder verwijzingen is van voor 28 november: de namen zijn
    # gelezen met de oude lezer (zie verwijzingen_uit) en plan en link
    # ontbreken. Helemaal opnieuw, één keer.
    if "verwijzingen" not in rec:
        return list(LAGEN)
    lagen = [laag for laag in LAGEN if laag not in rec]
    # Een maatvoering die met de eerste lezer is gevraagd, heeft namen maar
    # geen maten; die laag nog een keer.
    mv = (rec.get("verwijzingen") or {}).get("maatvoering") or []
    if "maatvoering" not in lagen and any(not x.get("maten") for x in mv):
        lagen.append("maatvoering")
    return lagen


def rest_stand(wachtrij, gedaan, fout):
    """Wat de vervolgronde nodig heeft: hoeveel er nog over is."""
    return {"rest": max(wachtrij - gedaan, 0), "opgehaald": gedaan,
            "fouten": fout}


def zoek(tekst, bestemming=None, pad=UIT_PAD):
    """
    Panden met een functieaanduiding die `tekst` bevat (hoofdletters maken
    niet uit), eventueel alleen binnen een enkelbestemming die `bestemming`
    bevat. Geeft [(pand, adres, enkelbestemmingen, functieaanduidingen,
    dubbelbestemmingen)], gesorteerd op adres.
    """
    t, b = tekst.lower(), (bestemming or "").lower()
    uit = []
    for p, rec in (lees(pad).get("panden") or {}).items():
        fa = rec.get("functieaanduiding") or []
        eb = rec.get("enkelbestemming") or []
        if not any(t in n.lower() for n in fa):
            continue
        if b and not any(b in n.lower() for n in eb):
            continue
        uit.append((p, rec.get("adres") or "", eb, fa,
                    rec.get("dubbelbestemming") or []))
    return sorted(uit, key=lambda r: r[1])


def lees(pad=UIT_PAD):
    try:
        with open(pad, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"bron": "", "panden": {}}


def verken(punten_adres):
    """Bekende panden vragen en het ruwe antwoord vastleggen."""
    import pandsleutel as _psl
    with open("voorraad.json", encoding="utf-8") as f:
        v = json.load(f)
    per = {}
    for deel in ("adressen", "niet_woningen"):
        for rec in (v.get(deel) or {}).values():
            if rec.get("punt"):
                per.setdefault(_psl.sleutel(rec.get("adres") or ""), rec)
    r = ["# Verkenning bestemmingen via PDOK", "",
         f"Op {dt.date.today().isoformat()}, WMS {WMS}.", ""]
    for adres, verwacht in punten_adres.items():
        rec = per.get(_psl.sleutel(adres))
        if not rec:
            r.append(f"## {adres}\n\nNiet in de voorraad, dus geen punt.\n")
            continue
        lat, lon = rec["punt"][1], rec["punt"][0]
        r.append(f"## {adres} ({lat:.6f}, {lon:.6f})")
        r.append(f"Verwacht: {verwacht or 'onbekend'}")
        for laag in LAGEN:
            try:
                ruw = _verzoek(laag, lat, lon)
                r.append(f"- {laag}: namen {namen_uit(ruw)!r}")
                r.append(f"  velden: `{velden_uit(ruw)[:1500]}`")
            except Exception as e:
                r.append(f"- {laag}: FOUT {type(e).__name__}: {str(e)[:200]}")
            time.sleep(PAUZE)
        r.append("")
    with open(VERSLAG, "w", encoding="utf-8") as f:
        f.write("\n".join(r) + "\n")
    print("\n".join(r))
    return 0


def ophalen(minuten, rest_pad=None):
    opgeslagen = lees()
    panden = opgeslagen.setdefault("panden", {})
    punten = punten_per_pand(met_niet_woningen=True)
    wachtrij = [(p, te_vragen(panden.get(p))) for p in punten]
    wachtrij = [(p, lagen) for p, lagen in wachtrij if lagen]
    begin, gedaan, fout = time.monotonic(), 0, 0
    for p, lagen in wachtrij:
        if minuten and time.monotonic() - begin > minuten * 60:
            break
        pt = punten[p]
        # Alle lagen: een nieuw record, zodat oude antwoorden niet blijven
        # hangen. Een paar lagen: aanvullen op wat er al staat.
        if len(lagen) == len(LAGEN):
            rec = {"adres": pt["adres"]}
        else:
            rec = dict(panden[p])
        try:
            verw = dict(rec.get("verwijzingen") or {})
            for laag in lagen:
                v = verwijzingen_uit(_verzoek(laag, pt["lat"], pt["lon"]))
                # None is "niet te lezen", [] is "gekeken en niets gevonden".
                rec[laag] = None if v is None else list(
                    dict.fromkeys(x["naam"] for x in v))
                verw[laag] = v
                time.sleep(PAUZE)
            rec["verwijzingen"] = verw
        except Exception as e:
            fout += 1
            if fout > 20:
                print("Te veel fouten; de bron lijkt onbereikbaar",
                      file=sys.stderr)
                break
            continue
        if len(lagen) == len(LAGEN):
            rec["gezien"] = dt.date.today().isoformat()
        panden[p] = rec
        gedaan += 1
    telling = {}
    for rec in panden.values():
        for n in rec.get("functieaanduiding") or []:
            telling[n] = telling.get(n, 0) + 1
    opgeslagen["telling_functieaanduiding"] = dict(
        sorted(telling.items(), key=lambda kv: -kv[1]))
    opgeslagen["bron"] = ("Ruimtelijke plannen (Wro), ruimtelijkeplannen.nl via "
                          "PDOK, CC-0; niet volledig, twee keer per jaar "
                          "bijgewerkt, zonder plannen in de nieuwe standaard")
    opgeslagen["bijgewerkt"] = dt.date.today().isoformat()
    with open(UIT_PAD, "w", encoding="utf-8") as f:
        json.dump(opgeslagen, f, ensure_ascii=False, indent=1)
    if rest_pad:
        # Voor de vervolgronde in bestemming.yml: door zolang er rest is en
        # deze ronde iets opleverde (zelfde regel als inhaal-3dbag.yml).
        with open(rest_pad, "w", encoding="utf-8") as f:
            json.dump(rest_stand(len(wachtrij), gedaan, fout), f)
    met = sum(1 for x in panden.values() if x.get("dubbelbestemming"))
    print(f"Bestemmingen: {gedaan} panden gevraagd, {fout} fouten, "
          f"{len(wachtrij) - gedaan} te gaan; {met} van {len(panden)} met een "
          f"dubbelbestemming", file=sys.stderr)
    return 0


BRONNAAM = "ruimtelijkeplannen.nl via PDOK"
VOORBEHOUD = ("de bron is niet volledig, niet juridisch bindend en mist het "
              "omgevingsplan in de nieuwe standaard; nakijken in Regels op de "
              "kaart in het Omgevingsloket")

_cache = {}


# WAAR DE DRIE CULTUURHISTORIE-NAMEN BIJ HOREN. AFGELEID, niet uit de
# planregels (die waren niet automatisch op te halen), maar per pand gemeten
# tegen de gezichten op 17 en 18 oktober 2026:
# - "Cultuurhistorie 1": 813 van de 815 panden liggen in het rijksgezicht
#   Nijmegen (1980), de oude binnenstad.
# - "Cultuurhistorie 2": 1.811 van de 1.811 liggen in het rijksgezicht
#   19de-eeuwse Stadsuitleg (2013).
# - "Cultuurhistorie" zonder nummer: 134 van de 134 liggen in een
#   gemeentelijk beschermd stadsbeeld en in geen rijksgezicht; 130 daarvan op
#   een object van Stadsbeeld Waterkwartier. Dat was de open vraag over Biezen.
# Omgekeerd hebben 616 panden in een gemeentelijk stadsbeeld buiten de
# rijksgezichten geen enkele cultuurhistorische dubbelbestemming: die
# stadsbeelden staan niet in het bestemmingsplan, alleen in het
# erfgoedregister (gezicht.py).
HERKOMST = {
    "Waarde - Cultuurhistorie 1": "hoort bij het rijksgezicht Nijmegen, "
                                  "afgeleid uit de ligging",
    "Waarde - Cultuurhistorie 2": "hoort bij het rijksgezicht 19de-eeuwse "
                                  "Stadsuitleg, afgeleid uit de ligging",
    "Waarde - Cultuurhistorie": "hoort bij het gemeentelijk Stadsbeeld "
                                "Waterkwartier, afgeleid uit de ligging",
}


def dossierregels(pand_id, pad=UIT_PAD):
    """
    Wat het dossier van een pand over de dubbelbestemming zegt, als
    [(onderwerp, tekst, bron)].

    DRIE TOESTANDEN, DRIE TEKSTEN. Niet gevraagd is niet hetzelfde als
    gevraagd en niets gevonden, en niets gevonden is niet hetzelfde als geen
    dubbelbestemming, want de bron is niet volledig.

    ARCHEOLOGIE ALLEEN BIJ UITBREIDEN. Gemeten op 17 oktober over 10.239
    panden in de ring: archeologie 2 bij 3.775 en archeologie 3 bij 3.627.
    Als hoofdpunt zou het in bijna elk dossier staan en daarmee niets
    onderscheiden. Het raakt alleen wie graaft of uitbouwt, dus daar staat
    het.
    """
    if pad not in _cache:
        _cache[pad] = lees(pad).get("panden") or {}
    rec = _cache[pad].get(str(pand_id or ""))
    if not rec:
        return [("dubbelbestemming", "niet nagekeken voor dit pand", BRONNAAM)]
    dubbel = rec.get("dubbelbestemming")
    if dubbel is None:
        return [("dubbelbestemming", "het antwoord van de bron was niet te "
                 "lezen", BRONNAAM)]
    uit = []
    cult = [n for n in dubbel if "cultuurhistorie" in n.lower()]
    arch = [n for n in dubbel if "archeologie" in n.lower()]
    if cult:
        herkomst = [HERKOMST[c] for c in cult if c in HERKOMST]
        uit.append(("cultuurhistorische dubbelbestemming",
                    f"{', '.join(cult)}"
                    + (f" ({'; '.join(herkomst)})" if herkomst else "")
                    + ". Bouwen kan dan een afwijking van "
                    f"het plan vergen, met advies van de Adviescommissie "
                    f"Omgevingskwaliteit; bij Groesbeekseweg 118A was dat "
                    f"nodig en duurde de procedure 213 dagen. Dit is een "
                    f"aanwijzing: {VOORBEHOUD}", BRONNAAM))
    elif rec.get("enkelbestemming"):
        # HET PLAN IS GELEZEN, DUS DIT IS MEER DAN "NIETS GEVONDEN". Gemeten
        # op 17 oktober: alle 10.296 panden in de ring hebben een
        # enkelbestemming in deze bron, ook de 1.070 in St. Anna, waar geen
        # enkel pand een cultuurhistorische dubbelbestemming heeft (wel
        # overal Archeologie 4). Dat is dus geen gat in de bron maar het plan
        # zelf. Wat de bron wel mist, is het omgevingsplan in de nieuwe
        # standaard; dat voorbehoud blijft.
        uit.append(("cultuurhistorische dubbelbestemming",
                    f"geen, volgens het bestemmingsplan op dit punt "
                    f"(enkelbestemming {', '.join(rec['enkelbestemming'])}). "
                    f"Wijzigingen in het omgevingsplan in de nieuwe standaard "
                    f"staan niet in deze bron; {VOORBEHOUD}", BRONNAAM))
    else:
        uit.append(("cultuurhistorische dubbelbestemming",
                    f"niet gevonden, en op dit punt ook geen enkelbestemming, "
                    f"dus het plan zelf is niet gelezen. Dat is geen "
                    f"uitsluitsel: {VOORBEHOUD}", BRONNAAM))
    if arch:
        uit.append(("bij uitbreiden of graven",
                    f"{', '.join(arch)}; dan kan archeologisch onderzoek "
                    f"nodig zijn", BRONNAAM))
    uit.extend(aanduidingregels(rec))
    return uit


def aanduidingregels(rec):
    """
    De regels over plan en aanduidingen, alleen voor lagen die gevraagd zijn.

    EEN LAAG DIE NOG NIET IS GEVRAAGD GEEFT GEEN REGEL. De panden van voor 28
    november hebben deze lagen nog niet; de ronde vult ze aan. Een regel als
    "niet nagekeken" zou dan in duizenden dossiers staan tot de ronde klaar
    is, en dat onderscheidt niets. Gevraagd en leeg krijgt wel een eigen
    tekst, en onleesbaar ook, zodat die drie nooit hetzelfde woord delen.
    """
    uit = []
    plan = rec.get("bestemmingsplangebied")
    if plan:
        uit.append(("bestemmingsplan", ", ".join(plan), BRONNAAM))
    if "functieaanduiding" in rec:
        fa = rec["functieaanduiding"]
        if fa is None:
            tekst = "het antwoord van de bron was niet te lezen"
        elif fa and _bepalingen_tekst(rec):
            tekst = f"{_bepalingen_tekst(rec)}. {VOORBEHOUD}"
        elif fa:
            tekst = (f"{', '.join(fa)}. Een functieaanduiding staat hier een "
                     f"functie toe naast wat de bestemming zegt; bij "
                     f"Smetiusstraat 15 maakte 'horeca' binnen Gemengd - 3 een "
                     f"hotel mogelijk zonder buitenplanse afwijking "
                     f"(Z2026-00002909). Wat de aanduiding precies toestaat "
                     f"staat in de planregels. Dit is een aanwijzing: "
                     f"{VOORBEHOUD}")
        else:
            tekst = (f"geen op dit punt; wat er mag volgt uit de bestemming "
                     f"en de planregels. {VOORBEHOUD}")
        uit.append(("functieaanduiding", tekst, BRONNAAM))
    for laag in ("bouwaanduiding", "gebiedsaanduiding"):
        namen = rec.get(laag)
        if namen:
            uit.append((laag, ", ".join(namen), BRONNAAM))
    maat = maatvoering_tekst(rec)
    if maat:
        uit.append(("maatvoering", maat, BRONNAAM))
    links = artikel_links(rec)
    if links:
        uit.append(("planregels", "; ".join(f"{n}: {u}" for n, u in links),
                    BRONNAAM))
    komend = in_voorbereiding(rec)
    if komend:
        uit.append(("in voorbereiding", "; ".join(komend) + ". Dit geldt nog "
                    "niet, maar kan wat hier mag veranderen: nakijken in "
                    "Regels op de kaart voor een aankoop.", BRONNAAM))
    return uit


_PLANREGELS = {}


def _artikelen(pad="planregels.json"):
    """De artikelteksten van planregels.py, een keer gelezen; {} zonder."""
    if pad not in _PLANREGELS:
        try:
            with open(pad, encoding="utf-8") as f:
                _PLANREGELS[pad] = json.load(f).get("artikelen") or {}
        except (FileNotFoundError, json.JSONDecodeError):
            _PLANREGELS[pad] = {}
    return _PLANREGELS[pad]


def _bepalingen_tekst(rec, artikelen=None):
    """
    De bepaling uit het artikel per functieaanduiding, als een regel; leeg
    als geen enkel artikel is opgehaald (dan blijft de algemene uitleg).

    WAAROM (28 november). De algemene uitleg noemde Smetiusstraat 15 als
    voorbeeld, maar in een ander plan betekent 'horeca' iets anders, en
    sommige aanduidingen staan letterlijk een hotel toe ('specifieke vorm van
    horeca - 2' in Binnenstad, 'specifieke vorm van gemengd - 3' in Oost).
    De lezer hoort de bepaling zelf te zien. Een aanduiding die niet in het
    artikel van de bestemming staat, krijgt "niet gevonden in het artikel":
    dat is niet "geen".
    """
    import planregels
    artikelen = _artikelen() if artikelen is None else artikelen
    delen = []
    for naam, titel, bep in planregels.bepaling_aanduiding(rec, artikelen):
        if titel is None:
            return ""
        if bep:
            delen.append(f"{naam} ({titel}, lid {bep['lid']}): "
                         f"{bep['tekst'].rstrip(' ;')}")
        else:
            delen.append(f"{naam}: niet gevonden in {titel}; de bepaling kan "
                         f"in een algemeen hoofdstuk van het plan staan")
    return "; ".join(delen)


def artikel_links(rec):
    """
    [(naam, link)] naar het artikel in de planregels, voor enkel- en
    dubbelbestemming en gebiedsaanduiding, een keer per link.

    WAAROM (28 november). Het dossier noemde 'Gemengd - 3', maar wat die
    bestemming toestaat staat in het artikel, en de link daarheen zat al in
    elk antwoord (verwijzingnaartekst). Bij een plangebied staan meerdere
    links met een komma (regels en toelichting); die blijven weg, het
    dossier noemt het plan al.
    """
    uit, gezien = [], set()
    verw = rec.get("verwijzingen") or {}
    for laag in ("enkelbestemming", "dubbelbestemming", "gebiedsaanduiding"):
        for v in verw.get(laag) or []:
            u = (v.get("tekst") or "").strip()
            if not u or "," in u or u in gezien:
                continue
            gezien.add(u)
            uit.append((v.get("naam") or laag, u))
    return uit


VASTGESTELD = {"vastgesteld", "onherroepelijk", "geheel onherroepelijk",
               "geheel onherroepelijk in werking"}


def in_voorbereiding(rec):
    """
    Plannen op dit punt die nog niet gelden: een voorbereidingsbesluit, of
    een plan met een andere planstatus dan vastgesteld (bijvoorbeeld een
    ontwerp). Als 'naam (typeplan, planstatus)', een keer per plan.

    WAAROM (28 november). Een ontwerpplan of voorbereidingsbesluit verandert
    wat er straks mag, zoals de inperking van winkel naar wonen op de begane
    grond in de binnenstad. De lagen geven ze naast het geldende plan, en
    tot nu toe zag het dossier het verschil niet.
    """
    uit, gezien = [], set()
    for laag, verw in (rec.get("verwijzingen") or {}).items():
        for v in verw or []:
            tp = (v.get("typeplan") or "").lower()
            st = (v.get("planstatus") or "").lower()
            if not tp and not st:
                continue
            if tp != "voorbereidingsbesluit" and (not st or st in VASTGESTELD):
                continue
            sleutel = v.get("plan") or v.get("naam")
            if sleutel in gezien:
                continue
            gezien.add(sleutel)
            uit.append(f"{v.get('naam')} ({tp or 'onbekend type'}, "
                       f"{st or 'status onbekend'})")
    return uit


def maatvoering_tekst(rec):
    """
    De maatvoering als een regel: naam met waarde waar die bekend is.
    Leeg als de laag niet gevraagd is of er niets ligt; het dossier zegt dan
    niets, want een ontbrekende maat is in deze bron geen 'geen maximum'.
    """
    verw = ((rec.get("verwijzingen") or {}).get("maatvoering")) or []
    delen = []
    for v in verw:
        m = v.get("maten") or {}
        if m:
            delen.extend(f"{k} {w}" for k, w in m.items())
        else:
            delen.append(v["naam"])
    if not delen:
        delen = list(rec.get("maatvoering") or [])
    return "; ".join(dict.fromkeys(delen))


def proef():
    afw = []
    voorbeeld = json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {
            "naam": "Waarde - Cultuurhistorie 2", "bestemmingshoofdgroep":
            "waarde", "planidentificatie": "NL.IMRO.0268.x"}}]})
    if namen_uit(voorbeeld) != ["Waarde - Cultuurhistorie 2"]:
        afw.append(f"de naam wordt niet gelezen: {namen_uit(voorbeeld)}")
    if namen_uit('{"type":"FeatureCollection","features":[]}') != []:
        afw.append("een leeg antwoord is niet 'gekeken en niets gevonden'")
    if namen_uit("<html>fout</html>") is not None:
        afw.append("een onleesbaar antwoord telt als niets gevonden")
    # HET ECHTE ANTWOORD van Smetiusstraat 15, functieaanduiding, 28
    # november (ingekort): 'bestemmingsvlak' mag geen naam worden.
    echt = json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {
            "aanduiding": "", "naam": "horeca",
            "bestemmingsvlak": "Enkelbestemming=NL.IMRO.0268.ID5198-00",
            "plangebied": "NL.IMRO.0268.BP5000-VG01",
            "verwijzingnaartekst": ""}},
        {"type": "Feature", "properties": {
            "naam": "Gemengd - 3", "plangebied": "NL.IMRO.0268.BP5000-VG01",
            "verwijzingnaartekst": "https://ruimtelijkeplannen.nl/documents/"
            "NL.IMRO.0268.BP5000-VG01/r_NL.IMRO.0268.BP5000-VG01_2.10.html"}},
        {"type": "Feature", "properties": {
            "naam": "Nijmegen Bottendaal Galgenveld",
            "locatienaam": "Het plangebied Nijmegen Bottendaal-Galgenveld "
                           "wordt begrensd door"}}]})
    if namen_uit(echt) != ["horeca", "Gemengd - 3",
                           "Nijmegen Bottendaal Galgenveld"]:
        afw.append(f"de lezer neemt andere velden dan 'naam': "
                   f"{namen_uit(echt)}")
    v_echt = verwijzingen_uit(echt) or [{}, {}]
    if v_echt[1].get("plan") != "NL.IMRO.0268.BP5000-VG01" \
            or not v_echt[1].get("tekst", "").endswith("_2.10.html"):
        afw.append(f"plan en link naar de planregels worden niet gelezen: "
                   f"{v_echt[1]}")
    # De drie toestanden van het dossier, op een eigen bestand.
    import tempfile, os
    fd, pad = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(pad, "w", encoding="utf-8") as f:
        json.dump({"panden": {
            "P1": {"dubbelbestemming": ["Waarde - Cultuurhistorie 2",
                                        "Waarde - Archeologie 4"]},
            "P2": {"dubbelbestemming": []},
            "P4": {"dubbelbestemming": ["Waarde - Archeologie 4"],
                   "enkelbestemming": ["Wonen"]},
            "P3": {"dubbelbestemming": None}}}, f)
    try:
        r1 = dossierregels("P1", pad)
        if [o for o, _t, _b in r1] != ["cultuurhistorische dubbelbestemming",
                                       "bij uitbreiden of graven"]:
            afw.append(f"cultuurhistorie met archeologie: {r1}")
        if "afgeleid" not in r1[0][1]:
            afw.append("de herkomst van de dubbelbestemming staat er niet bij, "
                       "of niet als afgeleid")
        if "Regels op de kaart" not in r1[0][1]:
            afw.append("het voorbehoud van de bron staat er niet bij")
        r2 = dossierregels("P2", pad)
        if len(r2) != 1 or not r2[0][1].startswith("niet gevonden"):
            afw.append(f"gekeken en niets gevonden: {r2}")
        r5 = dossierregels("P4", pad)
        if not r5[0][1].startswith("geen, volgens het bestemmingsplan") \
                or r5[0][1] == r2[0][1]:
            afw.append(f"plan gelezen zonder cultuurhistorie leest als niets "
                       f"gevonden: {r5}")
        r3 = dossierregels("P3", pad)
        r4 = dossierregels("P9", pad)
        if r3[0][1] == r4[0][1] or r2[0][1] == r4[0][1]:
            afw.append("niet gevraagd, onleesbaar en niets gevonden krijgen "
                       "dezelfde tekst")
        if "nagekeken" not in r4[0][1]:
            afw.append(f"niet gevraagd zegt niet dat het niet is nagekeken: {r4}")
    finally:
        os.unlink(pad)
        _cache.pop(pad, None)

    # AANDUIDINGEN: gevraagd met horeca, gevraagd en leeg, onleesbaar, en
    # nog niet gevraagd geven elk iets anders.
    fa_wel = aanduidingregels({"functieaanduiding": ["horeca"],
                               "bestemmingsplangebied": ["Binnenstad"]})
    fa_leeg = aanduidingregels({"functieaanduiding": []})
    fa_ruis = aanduidingregels({"functieaanduiding": None})
    fa_niet = aanduidingregels({"enkelbestemming": ["Wonen"]})
    if [o for o, _t, _b in fa_wel] != ["bestemmingsplan", "functieaanduiding"] \
            or not fa_wel[1][1].startswith("horeca"):
        afw.append(f"functieaanduiding horeca staat niet in het dossier: "
                   f"{fa_wel}")
    if not fa_leeg or not fa_leeg[0][1].startswith("geen") \
            or not fa_ruis or fa_ruis[0][1] == fa_leeg[0][1]:
        afw.append("functieaanduiding: leeg en onleesbaar krijgen dezelfde "
                   "tekst, of geen tekst")
    if fa_niet:
        afw.append(f"een niet gevraagde aanduidingslaag geeft toch een regel: "
                   f"{fa_niet}")
    fd, dpad = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(dpad, "w", encoding="utf-8") as f:
        json.dump({"panden": {"S": {
            "dubbelbestemming": [], "enkelbestemming": ["Gemengd - 3"],
            "functieaanduiding": ["horeca"]}}}, f)
    try:
        if "functieaanduiding" not in [o for o, _t, _b
                                       in dossierregels("S", dpad)]:
            afw.append("functieaanduiding horeca staat niet in het dossier "
                       "van het pand")
    finally:
        os.unlink(dpad)
        _cache.pop(dpad, None)

    # WELKE LAGEN NOG GEVRAAGD WORDEN.
    vandaag = dt.date(2026, 11, 28)
    oud = {"gezien": "2026-10-17", "dubbelbestemming": [],
           "enkelbestemming": ["Wonen"]}
    if te_vragen(oud, vandaag) != list(LAGEN):
        afw.append(f"een record zonder verwijzingen wordt niet helemaal "
                   f"opnieuw gevraagd: {te_vragen(oud, vandaag)}")
    half = dict(oud, verwijzingen={})
    if te_vragen(half, vandaag) != [l for l in LAGEN if l not in half]:
        afw.append(f"een record met verwijzingen krijgt niet alleen de "
                   f"ontbrekende lagen: {te_vragen(half, vandaag)}")
    vol = dict(half, **{l: [] for l in LAGEN})
    if te_vragen(vol, vandaag):
        afw.append("een volledig record wordt opnieuw gevraagd")
    if te_vragen(dict(vol, gezien="2026-01-01"), vandaag) != list(LAGEN):
        afw.append("een record ouder dan HERHAAL_DAGEN wordt niet ververst")
    if te_vragen(None, vandaag) != list(LAGEN):
        afw.append("een nieuw pand krijgt niet alle lagen")

    # NIET-WONINGEN GAAN MEE, en een pand met een woning houdt dat punt.
    fd, vpad = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(vpad, "w", encoding="utf-8") as f:
        json.dump({"adressen": {
            "a": {"herkomst": "focusbuurt", "pand": "W", "punt": [5.1, 51.1],
                  "adres": "Woonstraat 1"}},
            "niet_woningen": {
            "b": {"herkomst": "focusbuurt", "pand": "H", "punt": [5.2, 51.2],
                  "adres": "Cafestraat 1"},
            "c": {"herkomst": "focusbuurt", "pand": "W", "punt": [5.3, 51.3],
                  "adres": "Woonstraat 1a"},
            "d": {"herkomst": "bekendmaking", "pand": "X", "punt": [5.4, 51.4],
                  "adres": "Buiten 1"}}}, f)
    try:
        alleen_w = punten_per_pand(vpad)
        beide = punten_per_pand(vpad, met_niet_woningen=True)
        if set(alleen_w) != {"W"}:
            afw.append(f"zonder vlag horen alleen woonpanden erin: {alleen_w}")
        if set(beide) != {"W", "H"}:
            afw.append(f"met vlag horen woon- en horecapand erin, niet het "
                       f"pand buiten de ring: {sorted(beide)}")
        if beide.get("W", {}).get("adres") != "Woonstraat 1":
            afw.append("een pand met een woning krijgt het punt van de "
                       "niet-woning")
    finally:
        os.unlink(vpad)

    # ZOEKEN op functieaanduiding en bestemming.
    fd, zpad = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(zpad, "w", encoding="utf-8") as f:
        json.dump({"panden": {
            "1": {"adres": "B 1", "enkelbestemming": ["Gemengd - 3"],
                  "functieaanduiding": ["horeca"]},
            "2": {"adres": "A 1", "enkelbestemming": ["Wonen"],
                  "functieaanduiding": ["Horeca"]},
            "3": {"adres": "C 1", "enkelbestemming": ["Gemengd - 3"],
                  "functieaanduiding": []}}}, f)
    try:
        if [r[0] for r in zoek("horeca", pad=zpad)] != ["2", "1"]:
            afw.append(f"zoeken op horeca: {zoek('horeca', pad=zpad)}")
        if [r[0] for r in zoek("horeca", "gemengd", zpad)] != ["1"]:
            afw.append("zoeken binnen een bestemming filtert niet")
    finally:
        os.unlink(zpad)

    # MAATVOERING: het echte antwoord van Smetiusstraat 15 (28 november).
    mv = json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {
            "aanduiding": "Bouwvlak=NL.IMRO.0268.ID44634-00",
            "maatvoering": '"maximum bouwhoogte (m)"="13", '
                           '"maximum goothoogte (m)"="10"',
            "naam": "maximale goot- en bouwhoogte (m)",
            "plangebied": "NL.IMRO.0268.BP5000-VG01",
            "verwijzingnaartekst": ""}}]})
    v_mv = verwijzingen_uit(mv) or [{}]
    if v_mv[0].get("maten") != {"maximum bouwhoogte (m)": "13",
                                "maximum goothoogte (m)": "10"}:
        afw.append(f"de maten van een maatvoering worden niet gelezen: {v_mv}")
    if maatvoering_tekst({"verwijzingen": {"maatvoering": v_mv}}) != \
            "maximum bouwhoogte (m) 13; maximum goothoogte (m) 10":
        afw.append(f"maatvoering in het dossier: "
                   f"{maatvoering_tekst({'verwijzingen': {'maatvoering': v_mv}})}")
    if maatvoering_tekst({"enkelbestemming": ["Wonen"]}):
        afw.append("een niet gevraagde maatvoering geeft toch een regel")
    if maten_uit(None) or maten_uit("onzin"):
        afw.append("een lege of onleesbare maatvoering geeft toch maten")
    zonder_maten = {"gezien": "2026-11-28", "verwijzingen": {"maatvoering": [
        {"naam": "maximale goot- en bouwhoogte (m)"}]}}
    zonder_maten.update({l: [] for l in LAGEN})
    if te_vragen(zonder_maten, dt.date(2026, 11, 28)) != ["maatvoering"]:
        afw.append("een maatvoering zonder maten wordt niet opnieuw gevraagd")

    # BEPALINGEN IN HET DOSSIER: de echte tekst, niet gevonden, niet gehaald.
    _arts = {"https://ruimtelijkeplannen.nl/documents/A/a.html": {
        "titel": "Artikel 10 Gemengd - 3",
        "tekst": "l. ter plaatse van de aanduiding 'specifieke vorm van "
                 "horeca-2' tevens voor een hotel;"}}
    _rec = {"functieaanduiding": ["specifieke vorm van horeca - .2",
                                  "onderwijs"],
            "verwijzingen": {"enkelbestemming": [
                {"naam": "Gemengd - 3",
                 "tekst": "https://ruimtelijkeplannen.nl/documents/A/a.html"}]}}
    _bt = _bepalingen_tekst(_rec, _arts)
    if "tevens voor een hotel" not in _bt or \
            "onderwijs: niet gevonden in Artikel 10" not in _bt:
        afw.append(f"bepalingen in het dossier: {_bt!r}")
    if _bepalingen_tekst(_rec, {}):
        afw.append("zonder opgehaald artikel komt er toch een bepalingstekst")
    # En via het dossier zelf: de bepaling moet in de regel staan.
    fd, _dp = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(_dp, "w", encoding="utf-8") as f:
        json.dump({"panden": {"G": dict(_rec, dubbelbestemming=[],
                                        enkelbestemming=["Gemengd - 3"])}}, f)
    _oud = _PLANREGELS.get("planregels.json")
    _PLANREGELS["planregels.json"] = _arts
    try:
        _fa = [t for o, t, _b in dossierregels("G", _dp)
               if o == "functieaanduiding"]
        if not _fa or "tevens voor een hotel" not in _fa[0]:
            afw.append(f"de bepaling staat niet in het dossier: {_fa}")
    finally:
        if _oud is None:
            _PLANREGELS.pop("planregels.json", None)
        else:
            _PLANREGELS["planregels.json"] = _oud
        os.unlink(_dp)
        _cache.pop(_dp, None)

    # ARTIKEL-LINKS: bestemmingen met link, plangebied met kommalijst niet.
    al = artikel_links({"verwijzingen": {
        "enkelbestemming": [{"naam": "Gemengd - 3", "tekst": "https://r/a_2.10.html"}],
        "dubbelbestemming": [{"naam": "Waarde - Cultuurhistorie 2",
                              "tekst": "https://r/a_3.27.html"},
                             {"naam": "dubbel", "tekst": "https://r/a_3.27.html"}],
        "gebiedsaanduiding": [{"naam": "twee links",
                               "tekst": "https://r/r.html,https://r/t.html"}],
        "functieaanduiding": [{"naam": "horeca", "tekst": "https://r/f.html"}]}})
    if al != [("Gemengd - 3", "https://r/a_2.10.html"),
              ("Waarde - Cultuurhistorie 2", "https://r/a_3.27.html")]:
        afw.append(f"artikel-links: {al}")
    if artikel_links({"enkelbestemming": ["Wonen"]}):
        afw.append("een record zonder verwijzingen geeft toch links")

    # IN VOORBEREIDING: ontwerp en voorbereidingsbesluit wel, vastgesteld niet.
    vb = {"verwijzingen": {
        "plangebied": [
            {"naam": "Binnenstad", "plan": "A", "typeplan": "bestemmingsplan",
             "planstatus": "vastgesteld"},
            {"naam": "Winkels begane grond", "plan": "B",
             "typeplan": "voorbereidingsbesluit", "planstatus": "vastgesteld"},
            {"naam": "Herziening", "plan": "C", "typeplan": "bestemmingsplan",
             "planstatus": "ontwerp"}],
        "enkelbestemming": [
            {"naam": "Gemengd - 3", "plan": "C", "typeplan": "bestemmingsplan",
             "planstatus": "ontwerp"}]}}
    kv = in_voorbereiding(vb)
    if kv != ["Winkels begane grond (voorbereidingsbesluit, vastgesteld)",
              "Herziening (bestemmingsplan, ontwerp)"]:
        afw.append(f"plannen in voorbereiding: {kv}")
    if in_voorbereiding({"verwijzingen": {"plangebied": [
            {"naam": "Binnenstad", "plan": "A", "typeplan": "bestemmingsplan",
             "planstatus": "vastgesteld"}]}}):
        afw.append("een vastgesteld plan telt als in voorbereiding")
    if in_voorbereiding({"verwijzingen": {"plangebied": [
            {"naam": "Oud", "plan": "D"}]}}):
        afw.append("een record zonder status telt als in voorbereiding")

    # DE KETEN STOPT als er niets meer te doen is of niets meer lukt.
    if rest_stand(10, 10, 0)["rest"] != 0 or rest_stand(10, 3, 1)["rest"] != 7:
        afw.append(f"de rest van de wachtrij klopt niet: "
                   f"{rest_stand(10, 10, 0)}, {rest_stand(10, 3, 1)}")
    if rest_stand(10, 0, 21)["opgehaald"] != 0:
        afw.append("een ronde zonder resultaat telt als opgehaald")

    for a in afw:
        print("AFWIJKING: " + a, file=sys.stderr)
    print(f"Proef bestemming: {len(afw)} afwijkingen", file=sys.stderr)
    return 1 if afw else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proef", action="store_true")
    ap.add_argument("--verken", action="store_true")
    ap.add_argument("--minuten", type=float, default=0)
    ap.add_argument("--zoek", metavar="AANDUIDING")
    ap.add_argument("--rest", metavar="PAD",
                    help="schrijf de rest van de wachtrij als json")
    ap.add_argument("--bestemming", metavar="TEKST")
    a = ap.parse_args()
    if a.proef:
        return proef()
    if a.verken:
        return verken(BEKEND)
    if a.zoek:
        rijen = zoek(a.zoek, a.bestemming)
        for _p, adres, eb, fa, db in rijen:
            print(f"{adres}\t{', '.join(eb)}\t{', '.join(fa)}\t"
                  f"{', '.join(db)}")
        print(f"{len(rijen)} panden met functieaanduiding '{a.zoek}'"
              + (f" binnen '{a.bestemming}'" if a.bestemming else ""),
              file=sys.stderr)
        return 0
    return ophalen(a.minuten, a.rest)


if __name__ == "__main__":
    sys.exit(main())
