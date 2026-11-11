#!/usr/bin/env python3
"""
Register van bekende kamerverhuurpanden.

Twee bronnen samen, omdat elk afzonderlijk gaten heeft:

- De vergunningenlijst van de gemeente (kamervergunningen.json). Bevat alleen
  wat een vergunning nodig had. Boven de WOZ-grens van €396.000 is geen
  omzettingsvergunning nodig, dus die kamerpanden staan er niet in.
- Meldingen brandveilig gebruik en besluiten over kamerverhuur uit het
  bekendmakingen-archief. Een melding is verplicht vanaf vijf verhuurde kamers,
  ongeacht de WOZ. Nijmegen publiceert ze sinds ongeveer 2025 in het
  gemeenteblad; oudere meldingen staan er niet in.

Wat ook samen ontbreekt: kamerpanden met drie of vier kamers boven de
WOZ-grens, en meldingen van voor de publicatie. Het register is dus een
ondergrens van het werkelijke aantal.

Een aanvraag telt niet mee; alleen een verleende vergunning, een besluit of
een melding.

Gebruik:
  python kamerverhuur_register.py
Schrijft kamerverhuur_objecten.json en kamerverhuur_per_buurt.json.
"""

import collections
import json
import os
import re
import sys


import pandsleutel as _psl
REGISTER_PAD = "kamerverhuur_objecten.json"
PER_BUURT_PAD = "kamerverhuur_per_buurt.json"
VERGUNNINGEN_PAD = "kamervergunningen.json"
ARCHIEF_PAD = "bekendmakingen_archief.json"

try:
    from diagnose import leg_vast, wis
except Exception:  # noqa
    def leg_vast(*_a):
        pass

    def wis(*_a):
        pass


def _json(pad):
    try:
        with open(pad, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def sleutel(straat, nr):
    """De sleutel van kamerverhuur_objecten.json: per woning.

    Een van de veertien sleutelfuncties in elf bestanden die allemaal hetzelfde
    bedoelden en op drie punten uiteenliepen: of een titel werd afgekort,
    of een accent wegviel of bleef staan, en of "doctor" meedeed. Op de
    adressen die we volgen gaven twee van die veertien 41 keer een andere
    sleutel. De functie blijft staan omdat de aanroepers hem gebruiken, maar
    hij rekent niet meer zelf."""
    return _psl.sleutel(straat, nr)


def _straat_nr(adres):
    m = re.match(r"^(.+?)\s+(\d+)", (adres or "").strip())
    return (m.group(1).strip(), m.group(2)) if m else (None, None)


def _adres_uit_titel(titel):
    """Het adres uit een bekendmakingstitel, via het archiefscript als dat kan."""
    try:
        from bekendmakingen_archief import adres_uit_titel
        uit = adres_uit_titel(titel)
        if uit:
            return uit
    except Exception:
        pass
    m = re.search(r"aan\s+(?:de\s+)?(.+?)\s+(\d+)[A-Za-z]?\s*,", titel)
    return (m.group(1).strip(), m.group(2)) if m else None


def bekende_straten(vergunningen):
    """Straatnamen die we zeker kennen: uit de vergunningen en de straatcache."""
    namen = set()
    for items in (vergunningen or {}).values():
        for v in items:
            straat, _nr = _straat_nr(v.get("adres"))
            if straat:
                namen.add(straat.lower())
    # Alleen straten waarvoor echt een buurt is gevonden. Een mislukte opzoeking
    # staat ook in de cache, met een lege buurt, en is geen bewijs.
    namen.update(k.lower() for k, v in _json("straat_buurt_cache.json").items() if v)
    return namen


def schoon_straat(straat, bekend):
    """
    "aan de Pijnboomstraat 19" levert "de Pijnboomstraat" op. Blind "de"
    weghalen kan niet, want "de Ruyterstraat" heet echt zo. Daarom alleen als
    de straat zonder "de" bekend is en met "de" niet.
    """
    laag = straat.lower()
    if laag.startswith("de ") and laag not in bekend and laag[3:] in bekend:
        return straat[3:]
    return straat


def telt_als_kamerverhuur(item):
    """Een melding, een besluit of een vergunning; geen aanvraag, geen samenvoeging."""
    soorten = " ".join(x.lower() for x in (item.get("soorten") or []))
    titel = (item.get("titel") or "").lower()
    if "samenvoeg" in soorten or "samenvoeg" in titel:
        return None
    if "brandveilig" in soorten or "brandveilig" in titel:
        return "melding brandveilig gebruik"
    if titel.startswith("aanvraag"):
        return None
    if any(k in soorten for k in ("kamerverhuur", "omzetting")):
        return "besluit kamerverhuur"
    return None


def bouw_register(vergunningen, archief):
    """Per adres: de straat, het nummer en de bronnen die op kamerverhuur wijzen."""
    register = {}
    bekend = bekende_straten(vergunningen)

    for _k, items in (vergunningen or {}).items():
        for v in items:
            soort = (v.get("soort") or "").lower()
            if "samenvoeg" in soort:
                continue
            straat, nr = _straat_nr(v.get("adres"))
            if not straat:
                continue
            sl = sleutel(straat, nr)
            r = register.setdefault(sl, {"adres": f"{straat} {nr}", "straat": straat,
                                         "bronnen": []})
            r["bronnen"].append({"bron": "vergunning", "soort": v.get("soort") or "",
                                 "jaar": (v.get("datum") or "")[:4]})

    for _k, items in (archief or {}).items():
        for t in items:
            soort = telt_als_kamerverhuur(t)
            if not soort:
                continue
            adres = _adres_uit_titel(t.get("titel") or "")
            if not adres:
                continue
            straat, nr = adres
            straat = schoon_straat(straat, bekend)
            sl = sleutel(straat, nr)
            r = register.setdefault(sl, {"adres": f"{straat} {nr}", "straat": straat,
                                         "bronnen": []})
            r["bronnen"].append({"bron": "melding" if "melding" in soort else "besluit",
                                 "soort": soort,
                                 "jaar": (t.get("datum") or "")[:4]})
    return register


def koppel_buurten(register):
    """Elke straat aan een buurt, via de cache en zo nodig PDOK."""
    try:
        from vergunningen_buurten import lees_cache, buurt_van_straat, STRAATCACHE
    except Exception:
        return register, 0
    # Sinds 11 november in nijmegen-marktdata: beide bronnen van dit register
    # (de vergunningenlijst en de meldingen in het bekendmakingenarchief) zijn
    # openbaar, en de straten die het opzoekt dus ook.
    cache = lees_cache()
    nieuw = 0
    for r in register.values():
        if not cache.get(r["straat"]):
            nieuw += 1
        r["buurt"] = buurt_van_straat(r["straat"], cache) or ""
    try:
        with open(STRAATCACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
    except Exception:
        pass
    return register, nieuw


def per_buurt(register):
    """Telling per buurt, uitgesplitst naar welke bron het pand kent."""
    uit = collections.defaultdict(lambda: {"totaal": 0, "alleen_vergunning": 0,
                                           "alleen_melding_of_besluit": 0, "beide": 0})
    for r in register.values():
        b = r.get("buurt")
        if not b:
            continue
        soorten = {x["bron"] for x in r["bronnen"]}
        heeft_v = "vergunning" in soorten
        heeft_m = bool(soorten & {"melding", "besluit"})
        u = uit[b]
        u["totaal"] += 1
        if heeft_v and heeft_m:
            u["beide"] += 1
        elif heeft_v:
            u["alleen_vergunning"] += 1
        else:
            u["alleen_melding_of_besluit"] += 1
    return dict(uit)


def meldingen_per_jaar(register):
    """Hoeveel meldingen per jaar: laat zien hoe ver het archief terugreikt."""
    teller = collections.Counter()
    for r in register.values():
        for b in r["bronnen"]:
            if b["bron"] == "melding" and b["jaar"]:
                teller[b["jaar"]] += 1
    return dict(sorted(teller.items()))


def main():
    wis("kamerverhuur")
    vergunningen = _json(VERGUNNINGEN_PAD)
    archief = _json(ARCHIEF_PAD)
    register = bouw_register(vergunningen, archief)
    register, nieuw = koppel_buurten(register)

    telling = per_buurt(register)
    jaren = meldingen_per_jaar(register)
    samenvatting = {"per_buurt": telling, "meldingen_per_jaar": jaren,
                    "zonder_buurt": sum(1 for r in register.values()
                                        if not r.get("buurt"))}

    with open(REGISTER_PAD, "w", encoding="utf-8") as f:
        json.dump(register, f, ensure_ascii=False, indent=1, sort_keys=True)
    with open(PER_BUURT_PAD, "w", encoding="utf-8") as f:
        json.dump(samenvatting, f, ensure_ascii=False, indent=1, sort_keys=True)

    print(f"Register: {len(register)} adressen met een aanwijzing voor kamerverhuur",
          file=sys.stderr)
    print(f"  meldingen per jaar: {jaren or 'geen'}", file=sys.stderr)
    print(f"  {nieuw} straten nieuw opgezocht, "
          f"{samenvatting['zonder_buurt']} adressen zonder buurt", file=sys.stderr)
    if not register:
        leg_vast("kamerverhuur", "Het register is leeg: geen vergunningen en geen "
                                 "meldingen gevonden. Staan kamervergunningen.json "
                                 "en bekendmakingen_archief.json in de repo?")
    elif not jaren:
        leg_vast("kamerverhuur", "Geen enkele melding brandveilig gebruik in het "
                                 "archief. Het register rust dan alleen op de "
                                 "vergunningenlijst en mist kamerpanden boven de "
                                 "WOZ-grens.")


if __name__ == "__main__":
    main()
