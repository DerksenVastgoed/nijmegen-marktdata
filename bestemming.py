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
GetFeatureInfo op beide lagen. Het antwoord wordt bewaard in bestemmingen.json,
zodat een pand maar één keer wordt gevraagd; de bron verandert twee keer per
jaar.

  python3 bestemming.py --verken      # een handvol bekende panden, met het
                                      # ruwe antwoord in het verslag
  python3 bestemming.py --minuten 60  # de ring ophalen, hervatbaar
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
LAGEN = ("dubbelbestemming", "enkelbestemming")
UIT_PAD = "bestemmingen.json"
VERSLAG = "bestemming_verslag.md"
PAUZE = 0.2

# Panden waarvan we uit een besluit weten wat er ligt, om de bron aan te
# toetsen. Groesbeekseweg 118A: 'Cultuurhistorie - 2' volgens besluit
# Z2026-00001328. De andere twee zijn ter vergelijking; van die twee zegt het
# besluit alleen dat het omgevingsplan vergunningsvrij was.
BEKEND = {
    "Groesbeekseweg 118A": "Cultuurhistorie",
    "Bronsgeeststraat 11": None,
    "Heydenrijckstraat 40": None,
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


def namen_uit(antwoord):
    """
    De bestemmingsnamen uit een GetFeatureInfo-antwoord.

    De veldnaam ken ik niet zeker zonder een echt antwoord; daarom zoeken op
    velden die 'naam' of 'bestemming' heten, en het ruwe antwoord gaat in het
    verslag van --verken. Pas daarna hoort hier één vaste veldnaam te staan.
    """
    try:
        d = json.loads(antwoord)
    except Exception:
        return None
    namen = []
    for f in d.get("features") or []:
        props = (f or {}).get("properties") or {}
        for k, v in props.items():
            kl = k.lower()
            if isinstance(v, str) and v.strip() and (
                    kl == "naam" or kl.endswith("naam")
                    or "bestemming" in kl and "hoofdgroep" not in kl):
                if v.strip() not in namen:
                    namen.append(v.strip())
    return namen


def punten_per_pand(pad="voorraad.json"):
    """Per pand in de ring één punt (lat, lon) en een adres."""
    with open(pad, encoding="utf-8") as f:
        v = json.load(f)
    uit = {}
    for rec in (v.get("adressen") or {}).values():
        if rec.get("herkomst") != "focusbuurt":
            continue
        p, punt = rec.get("pand"), rec.get("punt")
        if p and punt and len(punt) == 2 and p not in uit:
            uit[p] = {"lat": punt[1], "lon": punt[0], "adres": rec.get("adres")}
    return uit


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
                r.append(f"  ruw: `{ruw[:600]}`")
            except Exception as e:
                r.append(f"- {laag}: FOUT {type(e).__name__}: {str(e)[:200]}")
            time.sleep(PAUZE)
        r.append("")
    with open(VERSLAG, "w", encoding="utf-8") as f:
        f.write("\n".join(r) + "\n")
    print("\n".join(r))
    return 0


def ophalen(minuten):
    opgeslagen = lees()
    panden = opgeslagen.setdefault("panden", {})
    punten = punten_per_pand()
    wachtrij = [p for p in punten if p not in panden]
    begin, gedaan, fout = time.monotonic(), 0, 0
    for p in wachtrij:
        if minuten and time.monotonic() - begin > minuten * 60:
            break
        pt = punten[p]
        rec = {"adres": pt["adres"], "gezien": dt.date.today().isoformat()}
        try:
            for laag in LAGEN:
                namen = namen_uit(_verzoek(laag, pt["lat"], pt["lon"]))
                # None is "niet te lezen", [] is "gekeken en niets gevonden".
                rec[laag] = namen
                time.sleep(PAUZE)
        except Exception as e:
            fout += 1
            if fout > 20:
                print("Te veel fouten; de bron lijkt onbereikbaar",
                      file=sys.stderr)
                break
            continue
        panden[p] = rec
        gedaan += 1
    opgeslagen["bron"] = ("Ruimtelijke plannen (Wro), ruimtelijkeplannen.nl via "
                          "PDOK, CC-0; niet volledig, twee keer per jaar "
                          "bijgewerkt, zonder plannen in de nieuwe standaard")
    opgeslagen["bijgewerkt"] = dt.date.today().isoformat()
    with open(UIT_PAD, "w", encoding="utf-8") as f:
        json.dump(opgeslagen, f, ensure_ascii=False, indent=1)
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
    return uit


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
    for a in afw:
        print("AFWIJKING: " + a, file=sys.stderr)
    print(f"Proef bestemming: {len(afw)} afwijkingen", file=sys.stderr)
    return 1 if afw else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proef", action="store_true")
    ap.add_argument("--verken", action="store_true")
    ap.add_argument("--minuten", type=float, default=0)
    a = ap.parse_args()
    if a.proef:
        return proef()
    if a.verken:
        return verken(BEKEND)
    return ophalen(a.minuten)


if __name__ == "__main__":
    sys.exit(main())
