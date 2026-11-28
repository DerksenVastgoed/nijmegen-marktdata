#!/usr/bin/env python3
"""
De Omgevingsvisie gemeente Nijmegen per stadsdeel, en welke ringbuurt bij
welk stadsdeel hoort, uit de tekst van de visie zelf.

WAAROM (28 november 2026). De visie (gemeenteblad 2025 nr. 401292,
CVDR744138) bindt niet op pandniveau, maar zegt per stadsdeel wat de gemeente
wil: bij Nijmegen-Oost "de balans tussen groei van het aantal inwoners en
leefbaarheid, vooral in de wijken rond het centrum", bij Oud-West minder
ruimte voor inbreiding. Haar werkingsgebieden (GIO's) bleken de stadsdelen
te zijn (dc-2025-14234 "Stadsdeel Nijmegen-Centrum", dc-2025-14235 "Stadsdeel
Nijmegen-Zuid"), en die waren vanaf GitHub niet op te halen: op 28 november
gaf identifier.officielebekendmakingen.nl 403 op elke JOIN-identificatie
(zie stadsbeeld.verken_regeling). Maar de tekst van paragraaf 6.4 tot en met
6.12 noemt per stadsdeel zijn wijken en buurten, en die tekst is wel te
halen. Een kaart is dus niet nodig: het stadsdeel van een buurt volgt uit
waar de visie de buurt noemt.

AFGELEID, NIET HARD. Een buurt hoort bij een stadsdeel als precies één
stadsdeelparagraaf de naam noemt. Noemt geen of meer dan één paragraaf de
naam, dan blijft de buurt zonder stadsdeel, en staat in het verslag waarom.

  python3 omgevingsvisie.py            # ophalen en vastleggen
  python3 omgevingsvisie.py --proef
"""
import argparse
import datetime as dt
import json
import re
import sys
import urllib.request

import planregels
import ring

REGELING = "https://lokaleregelgeving.overheid.nl/CVDR744138"
UIT_PAD = "omgevingsvisie.json"
VERSLAG = "omgevingsvisie_verslag.md"
# De koppen van hoofdstuk 6, zoals de inhoudsopgave ze noemt (28 november):
# 6.4 Nijmegen-Centrum tot en met 6.12 Nijmegen-Oost.
_KOP = re.compile(r"^6\.(\d{1,2})\s+(Nijmegen-[A-Za-z-]+|Dukenburg|Lindenholt)"
                  r"\s*$")
# Andere namen waarmee de visie een ringbuurt kan noemen. Alleen wat in de
# tekst van 28 november staat: "Waterkwartier (ook De Biezen genoemd)".
SYNONIEMEN = {"Biezen": ("Biezen", "Waterkwartier"),
              "St. Anna": ("St. Anna", "Sint Anna", "St.-Anna"),
              "Stadscentrum": ("Stadscentrum", "binnenstad", "Binnenstad")}
# Zinnen met deze woorden komen letterlijk in het dossier: wat de gemeente
# wil met bouwen, functies en ruimte.
KERNWOORDEN = ("verdicht", "inbreiding", "intensiver", "transformatie",
               "hoogbouw", "woningbouw", "functiemenging", "horeca",
               "kantoren", "studenten", "kamer", "leefbaarheid")


def stadsdelen(tekst):
    """
    {stadsdeel: {"paragraaf": "6.12", "tekst": ...}} uit de tekst van de
    visie. Een kop komt twee keer voor (inhoudsopgave en tekst); de langste
    paragraaf telt.
    """
    regels = (tekst or "").splitlines()
    koppen = [(i, m.group(1), m.group(2)) for i, r in enumerate(regels)
              for m in [_KOP.match(r.strip())] if m]
    uit = {}
    for n, (i, nr, naam) in enumerate(koppen):
        eind = len(regels)
        for j in range(i + 1, len(regels)):
            r = regels[j].strip()
            if _KOP.match(r) or re.match(r"^(7|8|9)(\.\d+)*\s+\S", r) or \
                    re.match(r"^Hoofdstuk \d", r):
                eind = j
                break
        deel = "\n".join(regels[i + 1:eind]).strip()
        if len(deel) > len((uit.get(naam) or {}).get("tekst", "")):
            uit[naam] = {"paragraaf": f"6.{nr}", "tekst": deel}
    return uit


def buurt_naar_stadsdeel(delen, buurten=ring.BUURTEN):
    """
    ({buurt: stadsdeel}, {buurt: reden zonder stadsdeel}). Een buurt hoort
    bij het enige stadsdeel waarvan de paragraaf haar (of een synoniem)
    noemt.
    """
    koppel, zonder = {}, {}
    for b in buurten:
        namen = SYNONIEMEN.get(b, (b,))
        treffers = [sd for sd, d in delen.items()
                    if any(re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])",
                                     d["tekst"]) for n in namen)]
        if len(treffers) == 1:
            koppel[b] = treffers[0]
        elif not treffers:
            zonder[b] = "door geen stadsdeelparagraaf genoemd"
        else:
            zonder[b] = "genoemd in " + ", ".join(sorted(treffers))
    return koppel, zonder


def kernzinnen(tekst, maximum=8):
    """Zinnen met een kernwoord, letterlijk, in volgorde."""
    zinnen = re.split(r"(?<=[.!?])\s+", " ".join((tekst or "").split()))
    uit = [z for z in zinnen
           if any(k in z.lower() for k in KERNWOORDEN) and 20 < len(z) < 400]
    return uit[:maximum]


def _haal(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "NijmegenVastgoedMonitor/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def ophalen(haal=None, uit_pad=UIT_PAD, verslag_pad=VERSLAG):
    haal = haal or _haal
    r = ["# Omgevingsvisie per stadsdeel", "", f"Regeling: `{REGELING}`", ""]
    try:
        _titel, tekst = planregels.tekst_uit(haal(REGELING))
    except Exception as e:
        # Niet opgehaald is geen lege visie: het vorige bestand blijft staan.
        r.append(f"- niet opgehaald: {type(e).__name__} {e}; {uit_pad} is "
                 f"niet overschreven")
        with open(verslag_pad, "w", encoding="utf-8") as f:
            f.write("\n".join(r) + "\n")
        print("\n".join(r))
        return 0
    delen = stadsdelen(tekst)
    if not delen:
        r.append(f"- geen enkele stadsdeelparagraaf gevonden in {len(tekst)} "
                 f"tekens; {uit_pad} is niet overschreven")
        with open(verslag_pad, "w", encoding="utf-8") as f:
            f.write("\n".join(r) + "\n")
        print("\n".join(r))
        return 0
    koppel, zonder = buurt_naar_stadsdeel(delen)
    uit = {"regeling": REGELING, "bijgewerkt": dt.date.today().isoformat(),
           "stadsdelen": {sd: dict(d, kern=kernzinnen(d["tekst"]))
                          for sd, d in delen.items()},
           "buurten": koppel, "buurten_zonder_stadsdeel": zonder}
    with open(uit_pad, "w", encoding="utf-8") as f:
        json.dump(uit, f, ensure_ascii=False, indent=1)
    r.append(f"- {len(tekst)} tekens, {len(delen)} stadsdeelparagrafen")
    for sd, d in sorted(delen.items(), key=lambda x: float(x[1]["paragraaf"]
                                                            .split(".")[1])):
        r.append(f"  - {d['paragraaf']} {sd}: {len(d['tekst'])} tekens, "
                 f"{len(kernzinnen(d['tekst']))} kernzinnen")
    r.append("")
    r.append("## Ringbuurten")
    r.append("")
    for b in ring.BUURTEN:
        r.append(f"- {b}: " + (koppel[b] if b in koppel
                               else f"geen stadsdeel ({zonder[b]})"))
    with open(verslag_pad, "w", encoding="utf-8") as f:
        f.write("\n".join(r) + "\n")
    print("\n".join(r))
    return 0


def lees(pad=UIT_PAD):
    try:
        with open(pad, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def dossierregels(buurt, pad=UIT_PAD):
    """
    [(onderwerp, tekst, bron)] voor het dossier van een pand in deze buurt:
    het stadsdeel met paragraaf en de kernzinnen, letterlijk. Leeg als de
    visie nog niet is opgehaald; een buurt zonder stadsdeel zegt waarom.
    """
    v = lees(pad)
    if not v.get("stadsdelen"):
        return []
    bron = "Omgevingsvisie gemeente Nijmegen (CVDR744138)"
    sd = (v.get("buurten") or {}).get(buurt)
    if not sd:
        reden = (v.get("buurten_zonder_stadsdeel") or {}).get(
            buurt, "buurt buiten de ring")
        return [("omgevingsvisie", f"geen stadsdeel toe te wijzen: {reden}",
                 bron)]
    d = v["stadsdelen"].get(sd) or {}
    kern = " ".join(f"\u201c{z}\u201d" for z in (d.get("kern") or [])[:4])
    return [("omgevingsvisie",
             f"{sd} (paragraaf {d.get('paragraaf')}, afgeleid: de visie noemt "
             f"{buurt} in deze paragraaf)" + (f": {kern}" if kern else ""),
             bron)]


def proef():
    import os
    import tempfile
    afw = []
    # Opbouw zoals de visie van 28 november: inhoudsopgave, dan de tekst.
    tekst = "\n".join([
        "6.4 Nijmegen-Centrum", "6.7 Nijmegen-Oud-West", "6.12 Nijmegen-Oost",
        "Hoofdstuk 6 Stadsdelen",
        "6.4 Nijmegen-Centrum",
        "De binnenstad en de Benedenstad. Verdichting is hier mogelijk "
        "binnen de historische maat.",
        "6.7 Nijmegen-Oud-West",
        "Wolfskuil, Waterkwartier en Waalfront. Er is "
        "minder ruimte voor inbreiding dan elders.",
        "6.12 Nijmegen-Oost",
        "Bottendaal, Galgenveld, Altrade en Hunnerberg. De belangrijkste "
        "opgave is de balans tussen groei en leefbaarheid.",
        "7 Uitvoering", "In Galgenveld begint de uitvoering."])
    d = stadsdelen(tekst)
    if sorted(d) != ["Nijmegen-Centrum", "Nijmegen-Oost", "Nijmegen-Oud-West"]:
        afw.append(f"stadsdelen: {sorted(d)}")
    if d.get("Nijmegen-Oost", {}).get("paragraaf") != "6.12" or \
            "Uitvoering" in d.get("Nijmegen-Oost", {}).get("tekst", ""):
        afw.append(f"de laatste paragraaf loopt door in hoofdstuk 7: {d}")
    k, z = buurt_naar_stadsdeel(d)
    verwacht = {"Stadscentrum": "Nijmegen-Centrum",
                "Benedenstad": "Nijmegen-Centrum",
                "Bottendaal": "Nijmegen-Oost", "Galgenveld": "Nijmegen-Oost",
                "Altrade": "Nijmegen-Oost", "Hunnerberg": "Nijmegen-Oost",
                "Biezen": "Nijmegen-Oud-West"}
    if k != verwacht:
        afw.append(f"buurt naar stadsdeel: {k}")
    if z != {"St. Anna": "door geen stadsdeelparagraaf genoemd"}:
        afw.append(f"buurten zonder stadsdeel: {z}")
    k2, z2 = buurt_naar_stadsdeel(
        {"A": {"tekst": "Altrade ligt hier."},
         "B": {"tekst": "Ook Altrade."}}, ("Altrade",))
    if k2 or "genoemd in A, B" not in z2.get("Altrade", ""):
        afw.append(f"een buurt in twee stadsdelen krijgt toch een stadsdeel: "
                   f"{k2}, {z2}")
    kz = kernzinnen(d["Nijmegen-Oud-West"]["tekst"])
    if kz != ["Er is minder ruimte voor inbreiding dan elders."]:
        afw.append(f"kernzinnen: {kz}")
    # Ophalen: mislukt laat het oude bestand staan.
    m = tempfile.mkdtemp()
    up, vp = os.path.join(m, "u.json"), os.path.join(m, "v.md")
    with open(up, "w", encoding="utf-8") as f:
        json.dump({"oud": True}, f)

    def mis(_u):
        raise OSError("403")
    stdout, sys.stdout = sys.stdout, open(os.devnull, "w")
    try:
        ophalen(mis, up, vp)
        if lees(up) != {"oud": True}:
            afw.append("een mislukte ophaling overschrijft het oude bestand")
        ophalen(lambda _u: "<p>" + tekst.replace("\n", "</p><p>") + "</p>",
                up, vp)
    finally:
        sys.stdout.close()
        sys.stdout = stdout
    if lees(up).get("buurten", {}).get("Bottendaal") != "Nijmegen-Oost":
        afw.append(f"ophalen legt de koppeling niet vast: {lees(up)}")
    dr = dossierregels("Biezen", up)
    if not dr or "Nijmegen-Oud-West (paragraaf 6.7" not in dr[0][1] or \
            "inbreiding" not in dr[0][1]:
        afw.append(f"dossierregel: {dr}")
    if "geen stadsdeel" not in dossierregels("St. Anna", up)[0][1]:
        afw.append("een buurt zonder stadsdeel zegt niet waarom")
    if dossierregels("Biezen", os.path.join(m, "bestaat-niet.json")):
        afw.append("zonder opgehaalde visie komt er toch een dossierregel")
    for a in afw:
        print("AFWIJKING: " + a, file=sys.stderr)
    print(f"Proef omgevingsvisie: {len(afw)} afwijkingen", file=sys.stderr)
    return 1 if afw else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proef", action="store_true")
    a = ap.parse_args()
    if a.proef:
        return proef()
    return ophalen()


if __name__ == "__main__":
    sys.exit(main())
