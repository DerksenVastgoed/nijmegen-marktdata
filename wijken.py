#!/usr/bin/env python3
"""
De wijkkeuzes van het zoekprofiel, met de CBS-buurten die bij elke keuze horen.

WAAROM DIT BESTAAT. Tot 11 november stond de wijkindeling op vier plekken: de
keuzelijst van het zoekprofiel, een lijst met zoekpatronen in de wachtlijst, de
opties van het HubSpot-veld en een lijst straten in de beheer-app. De wachtlijst
raadde de wijk uit de tekst van het adres. Gemeten op de 377 straten van
straat_buurt_cache.json: 239 straten in een wijk van het zoekprofiel werden
niet herkend, en 4 kregen een verkeerde wijk. "Noord" zat in de Arend
Noorduijnstraat (Bottendaal) en "heyendaal" in de Heyendaalseweg (Galgenveld).

HOE HET NU GAAT. Een adres heeft een CBS-buurt; die geeft de PDOK Locatieserver
per adres (niet per straat: een straat loopt vaak door meerdere buurten). Dit
bestand zegt bij welke keuze een buurt hoort. Een buurt die bij geen keuze
hoort, geeft geen keuze, en dan filtert de wachtlijst niet op wijk. Er wordt
nooit geraden.

WAT HIER STAAT EN WAT GEMETEN WORDT. KEUZES is onze eigen indeling: de keuzes
staan ook openbaar op het zoekprofiel. Een keuze is een of meer CBS-wijken of
CBS-buurten, met hun naam zoals het CBS ze schrijft. Welke buurten in een wijk
liggen, staat hier niet: dat haalt `--verversen` op uit de CBS Wijk- en
Buurtkaart (PDOK) en schrijft het naar wijken.json. Een naam in KEUZES die het
CBS niet kent, laat de verversing stoppen in plaats van een lege keuze op te
leveren.

Gebruik:
  python wijken.py --verversen   CBS-indeling ophalen, wijken.json schrijven
  python wijken.py --proef       wijken.json nameten, zonder netwerk
"""
import json
import os
import sys

try:
    from diagnose import leg_vast, wis
except Exception:  # noqa
    def leg_vast(*_a):
        pass

    def wis(*_a):
        pass

PAD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wijken.json")
GEMEENTE = "Nijmegen"
# De nieuwste jaargang die PDOK heeft, wint. Buurtgrenzen veranderen zelden,
# maar een nieuwe wijk of buurt moet erin komen.
JAREN = ("2025", "2024", "2023")
PDOK_TMPL = ("https://api.pdok.nl/cbs/wijken-en-buurten-{jaar}/ogc/v1/collections/"
             "{soort}/items?f=json&limit=2000&bbox=5.700,51.770,5.950,51.900")

# code, label op het zoekprofiel, en waaruit de keuze bestaat. "Nijmegen-Noord"
# is de hele CBS-wijk (Lent, Oosterhout, Ressen en de rest), niet alleen Lent.
KEUZES = (
    ("centrum", "Centrum", {"wijk": ["Centrum"]}),
    ("bottendaal", "Bottendaal", {"buurt": ["Bottendaal"]}),
    ("galgenveld", "Galgenveld", {"buurt": ["Galgenveld"]}),
    ("hunnerberg", "Hunnerberg", {"buurt": ["Hunnerberg"]}),
    ("biezen", "De Biezen", {"buurt": ["Biezen"]}),
    ("altrade", "Altrade", {"buurt": ["Altrade"]}),
    ("hengstdal", "Hengstdal", {"buurt": ["Hengstdal"]}),
    ("hees", "Hees en Heseveld", {"buurt": ["Hees", "Heseveld"]}),
    ("heyendaal", "Heyendaal en Brakkenstein", {"buurt": ["Heijendaal", "Brakkenstein"]}),
    ("dukenburg", "Dukenburg en Lindenholt", {"wijk": ["Dukenburg", "Lindenholt"]}),
    ("noord", "Nijmegen-Noord", {"wijk": ["Nijmegen-Noord"]}),
)
MAAKT_NIET_UIT = ("maakt_niet_uit", "Maakt niet uit")


def _veld(props, *namen):
    """Een veld uit PDOK, ongeacht hoofdletters."""
    laag = {k.lower(): v for k, v in props.items()}
    for n in namen:
        if n in laag and laag[n] not in (None, ""):
            return laag[n]
    return None


def _alle(url):
    """Alle features, ook als PDOK ze over pagina's verdeelt (link rel=next)."""
    import requests
    uit = []
    while url and len(uit) < 20000:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        j = r.json()
        uit += [f.get("properties", {}) for f in j.get("features", [])]
        url = next((l.get("href") for l in j.get("links", [])
                    if l.get("rel") == "next"), None)
    return uit


def haal_indeling():
    """
    (jaar, {buurtnaam: wijknaam}) voor de gemeente, uit PDOK. Gooit een fout
    met de gevonden veldnamen als de velden er niet zijn: dan is de vorm van
    PDOK veranderd, en dat moet opvallen.
    """
    laatste = None
    for jaar in JAREN:
        try:
            wf = _alle(PDOK_TMPL.format(jaar=jaar, soort="wijken"))
            bf = _alle(PDOK_TMPL.format(jaar=jaar, soort="buurten"))
        except Exception as e:
            laatste = f"{jaar}: {e}"
            continue
        wijknaam = {_veld(p, "wijkcode"): _veld(p, "wijknaam") for p in wf
                    if _veld(p, "gemeentenaam") == GEMEENTE}
        uit = {}
        for p in bf:
            if _veld(p, "gemeentenaam") != GEMEENTE:
                continue
            naam, code = _veld(p, "buurtnaam"), _veld(p, "wijkcode")
            if naam and code in wijknaam:
                uit[naam] = wijknaam[code]
        if not uit:
            velden = sorted(bf[0]) if bf else []
            raise RuntimeError(f"PDOK {jaar}: geen buurten van {GEMEENTE} herkend; "
                               f"velden in een buurt: {velden[:30]}")
        return jaar, uit
    raise RuntimeError(f"geen jaargang van PDOK bereikbaar ({laatste})")


def bouw(jaar, buurt_wijk):
    """De inhoud van wijken.json, of een fout als een naam in KEUZES niet bestaat."""
    wijk_namen = set(buurt_wijk.values())
    fouten, keuzes, al = [], [], {}
    for code, label, uit in KEUZES:
        buurten = []
        for w in uit.get("wijk", []):
            if w not in wijk_namen:
                fouten.append(f"{code}: CBS-wijk '{w}' bestaat niet in {jaar}")
            buurten += [b for b, wk in buurt_wijk.items() if wk == w]
        for b in uit.get("buurt", []):
            if b not in buurt_wijk:
                fouten.append(f"{code}: CBS-buurt '{b}' bestaat niet in {jaar}")
            buurten.append(b)
        for b in buurten:
            if b in al:
                fouten.append(f"buurt '{b}' hoort bij {al[b]} en bij {code}")
            al[b] = code
        keuzes.append({"code": code, "label": label, "buurten": sorted(set(buurten))})
    if fouten:
        raise ValueError("; ".join(fouten) + f". CBS-wijken in {jaar}: "
                         + ", ".join(sorted(wijk_namen)))
    return {
        "bron": f"CBS Wijk- en Buurtkaart {jaar} via PDOK; keuzes uit wijken.py",
        "jaar": jaar,
        "maakt_niet_uit": {"code": MAAKT_NIET_UIT[0], "label": MAAKT_NIET_UIT[1]},
        "keuzes": keuzes,
        "buurt_wijk": dict(sorted(buurt_wijk.items())),
    }


_CACHE = None


def lees(pad=PAD):
    global _CACHE
    if _CACHE is None or pad != PAD:
        with open(pad, encoding="utf-8") as f:
            d = json.load(f)
        if pad != PAD:
            return d
        _CACHE = d
    return _CACHE


def keuze_voor_buurt(buurt, indeling=None):
    """De code van de keuze waar een CBS-buurt bij hoort, of None."""
    d = indeling or lees()
    for k in d["keuzes"]:
        if buurt in k["buurten"]:
            return k["code"]
    return None


def verversen():
    try:
        jaar, bw = haal_indeling()
        inhoud = bouw(jaar, bw)
    except Exception as e:
        leg_vast("wijken", f"wijkindeling niet ververst: {e}")
        print(f"FOUT {e}", file=sys.stderr)
        return 1
    with open(PAD, "w", encoding="utf-8") as f:
        json.dump(inhoud, f, ensure_ascii=False, indent=1)
        f.write("\n")
    wis("wijken")
    print(f"wijken.json: {len(inhoud['keuzes'])} keuzes, {len(bw)} buurten ({jaar})",
          file=sys.stderr)
    return 0


def proef(indeling=None):
    """
    Nameten zonder netwerk:
    - elke keuze heeft buurten en elke buurt hoort bij hooguit een keuze;
    - de codes en labels zijn die van KEUZES, in dezelfde volgorde;
    - elke buurt in straat_buurt_cache.json (uit de Locatieserver) kent het
      CBS-bestand, anders schrijven de twee bronnen buurten verschillend;
    - de vier straten die de oude raadmethode fout had, komen goed uit;
    - en bouw() ziet zijn eigen fout: een onbekende naam en een dubbele buurt.
    """
    fouten = []
    try:
        d = indeling or lees()
    except Exception as e:
        print(f"FOUT wijken.json niet leesbaar: {e}", file=sys.stderr)
        return 1
    codes = [k["code"] for k in d["keuzes"]]
    if codes != [k[0] for k in KEUZES]:
        fouten.append(f"de keuzes in wijken.json ({codes}) zijn niet die van KEUZES")
    if [k["label"] for k in d["keuzes"]] != [k[1] for k in KEUZES]:
        fouten.append("de labels in wijken.json zijn niet die van KEUZES")
    gezien = {}
    for k in d["keuzes"]:
        if not k["buurten"]:
            fouten.append(f"keuze {k['code']} heeft geen buurten")
        for b in k["buurten"]:
            if b in gezien:
                fouten.append(f"buurt {b} hoort bij {gezien[b]} en {k['code']}")
            gezien[b] = k["code"]
    try:
        with open(os.path.join(os.path.dirname(PAD), "straat_buurt_cache.json"),
                  encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        cache = {}
    onbekend = sorted({b for b in cache.values() if b and b not in d["buurt_wijk"]})
    if onbekend:
        fouten.append(f"{len(onbekend)} buurten uit straat_buurt_cache.json kent het "
                      f"CBS-bestand niet: {onbekend[:5]}")
    # DE STRATEN DIE DE OUDE RAADMETHODE FOUT HAD. Die haalde de wijk uit de
    # straatnaam; deze vier gingen fout.
    for straat, moet in (("Arend Noorduijnstraat", "bottendaal"),
                         ("Dr. Claas Noorduijnstraat", "hunnerberg"),
                         ("Heyendaalseweg", "galgenveld")):
        if straat in cache and keuze_voor_buurt(cache[straat], d) != moet:
            fouten.append(f"{straat} ({cache[straat]}) geeft niet {moet}")
    if "Nieuwe Dukenburgseweg" in cache and \
            keuze_voor_buurt(cache["Nieuwe Dukenburgseweg"], d) == "dukenburg":
        fouten.append("Nieuwe Dukenburgseweg (Goffert) valt onder dukenburg")

    # DE PROEF MOET ZIJN EIGEN FOUT ZIEN.
    nep = {b: "Oost" for b in ("Bottendaal", "Galgenveld")}
    try:
        bouw("nep", nep)
        fouten.append("bouw() accepteert keuzes met namen die niet bestaan")
    except ValueError:
        pass

    for f in fouten:
        print(f"FOUT {f}", file=sys.stderr)
    print(f"Proef wijken: {len(fouten)} fouten. {len(d['keuzes'])} keuzes, "
          f"{len(gezien)} buurten met een keuze, CBS {d.get('jaar')}.", file=sys.stderr)
    return 1 if fouten else 0


if __name__ == "__main__":
    if "--verversen" in sys.argv:
        sys.exit(verversen())
    if "--proef" in sys.argv:
        sys.exit(proef())
    print(__doc__)
