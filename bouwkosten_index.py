#!/usr/bin/env python3
"""
Indexering van de verbouwkosten.

De RVO-kostenkentallen hebben peildatum mei 2025. Bouwkosten staan niet stil,
dus zonder indexering rekent de brief met cijfers die steeds verder achterlopen
en schat hij elke verbouwing te laag in.

BDB is de gangbare index in het vak, maar die zit achter een abonnement. Het
CBS publiceert een bruikbaar alternatief: tabel 85728NED, de inputprijsindex
bouwkosten nieuwbouwwoningen, basisjaar 2021. Die meet loon en materiaal apart,
en dat is precies waar een verbouwing uit bestaat. Grondkosten, winst en risico
zitten er niet in, wat voor onze toepassing juist klopt.

Gebruik:
  python bouwkosten_index.py            # haal de index op en toon de factor
  python bouwkosten_index.py --vanaf 2025-05
"""

import argparse
import datetime as dt
import json
import os
import sys

import requests

try:
    from diagnose import leg_vast, wis
except Exception:  # noqa
    def leg_vast(*_a):
        pass

    def wis(*_a):
        pass

TABEL = "85728NED"
ODATA = f"https://opendata.cbs.nl/ODataApi/OData/{TABEL}/TypedDataSet"
INDEX_PAD = "bouwkosten_index.json"

# Peildatum van de RVO-kostenkentallen waarmee de brief rekent
PEILDATUM = "2025-05"

# De kolom met het indexcijfer. De tabel heeft ook een kolom met de
# verandering ten opzichte van een jaar eerder; die mogen we NIET pakken, want
# dan rekenen we met een percentage in plaats van een indexniveau.
REEKS = "InputprijsindexBouwkosten_1"
VERBODEN_KOLOMMEN = ("ontwikkeling", "tov", "mutatie", "verandering")

# De tabel geeft per maand een rij per component: loon, materiaal en totaal.
# We willen het totaal.
COMPONENTEN = f"https://opendata.cbs.nl/ODataApi/OData/{TABEL}/Componenten"


def _periode_naar_maand(code):
    """CBS schrijft maanden als 2026MM07; daar maken we 2026-07 van."""
    if not code or "MM" not in code:
        return ""
    jaar, maand = code.split("MM")
    return f"{jaar}-{maand}"


def _totaal_component():
    """
    De sleutel van de component 'totaal' in de dimensie Componenten.

    Zonder deze filter krijg je per maand drie rijen, en wint de laatste die
    toevallig binnenkomt. Dan kan de index ongemerkt op materiaal of loon
    uitkomen in plaats van op het totaal.
    """
    try:
        r = requests.get(COMPONENTEN, timeout=(15, 60))
        r.raise_for_status()
        opties = r.json().get("value", [])
    except Exception as e:
        leg_vast("bouwkosten", f"De lijst met componenten kon niet worden "
                               f"opgehaald: {str(e)[:120]}")
        return None, []
    titels = [(o.get("Key", "").strip(), o.get("Title", "")) for o in opties]
    for sleutel, titel in titels:
        if "totaal" in titel.lower():
            return sleutel, titels
    return None, titels


def haal_index():
    """
    De maandreeks van de inputprijsindex bouwkosten.

    Geeft een dict van maand naar indexcijfer. Lukt het ophalen niet, dan geeft
    het een lege dict terug; de aanroeper rekent dan zonder indexering en meldt
    dat.
    """
    # De ODataApi van het CBS kent geen $skip; die geeft zelf een nextLink mee
    # zolang er meer rijen zijn. Dus die volgen we, in plaats van zelf te
    # bladeren.
    rijen, url = {}, ODATA
    kolom = None
    wis("bouwkosten")
    totaal, componenten = _totaal_component()
    if totaal:
        print(f"  component totaal: {totaal}", file=sys.stderr)
    for _ronde in range(25):                    # ruim genoeg voor acht jaar
        try:
            r = requests.get(url, timeout=(15, 60))
            r.raise_for_status()
            body = r.json()
        except Exception as e:
            print(f"Index ophalen mislukt: {e}", file=sys.stderr)
            leg_vast("bouwkosten", f"Het CBS gaf een fout bij {url[:90]}: "
                                   f"{str(e)[:200]}")
            return rijen

        waarden = body.get("value", [])

        # De kolomnaam bij het CBS krijgt vaak een achtervoegsel, zoals _1.
        # Staat de verwachte naam er niet in, dan zoeken we de kolom voor de
        # totale bouwkosten zelf, en melden we welke we hebben gekozen.
        if kolom is None and waarden:
            sleutels = list(waarden[0].keys())
            if REEKS in sleutels:
                kolom = REEKS
            else:
                bruikbaar = [k for k in sleutels
                             if not any(v in k.lower() for v in VERBODEN_KOLOMMEN)]
                kandidaten = [k for k in bruikbaar
                              if "index" in k.lower() and "bouwkosten" in k.lower()]
                kandidaten = kandidaten or [k for k in bruikbaar
                                            if "index" in k.lower()]
                if kandidaten:
                    kolom = kandidaten[0]
                    print(f"  kolom '{REEKS}' niet gevonden, gebruik '{kolom}'",
                          file=sys.stderr)
                else:
                    print(f"  geen kolom voor de totale bouwkosten gevonden. "
                          f"Beschikbaar: {sleutels}", file=sys.stderr)
                    leg_vast("bouwkosten",
                             f"Geen kolom voor de totale bouwkosten. Het CBS gaf "
                             f"deze kolommen: {', '.join(sleutels)}")
                    return rijen

        for rij in waarden:
            maand = _periode_naar_maand((rij.get("Perioden") or "").strip())
            if not maand:
                continue                        # jaar- en kwartaalcijfers
            # Alleen de component totaal, anders overschrijven loon en
            # materiaal elkaar per maand
            if totaal and (rij.get("Componenten") or "").strip() != totaal:
                continue
            cijfer = rij.get(kolom)
            if cijfer is None:
                continue
            try:
                rijen[maand] = float(cijfer)
            except (TypeError, ValueError):
                continue

        url = body.get("odata.nextLink") or body.get("@odata.nextLink")
        if not url:
            break

    if not rijen and componenten and not totaal:
        leg_vast("bouwkosten",
                 "Geen component 'totaal' gevonden. Beschikbaar: "
                 + "; ".join(f"{k} = {t}" for k, t in componenten[:6]))
    if not rijen:
        perioden = sorted({(r.get("Perioden") or "") for r in waarden})[:6] \
            if waarden else []
        leg_vast("bouwkosten",
                 f"Het CBS antwoordde, maar er zaten geen maandcijfers in. Kolom "
                 f"gebruikt: {kolom}. Voorbeelden van perioden: "
                 f"{', '.join(perioden) or 'geen'}. Maanden horen de vorm "
                 f"2026MM07 te hebben.")
    return rijen


def lees_index():
    if not os.path.exists(INDEX_PAD):
        return {}
    try:
        with open(INDEX_PAD, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def schrijf_index(reeks):
    try:
        with open(INDEX_PAD, "w", encoding="utf-8") as f:
            json.dump(reeks, f, ensure_ascii=False, indent=1, sort_keys=True)
    except Exception as e:
        print(f"Kon {INDEX_PAD} niet schrijven: {e}", file=sys.stderr)


def indexfactor(vanaf=PEILDATUM, reeks=None):
    """
    Met welke factor moeten de kentallen vermenigvuldigd worden?

    Geeft de factor, de gebruikte maanden en het percentage terug. Ontbreekt de
    reeks, dan is de factor 1 en weet de aanroeper dat er niet geindexeerd is.
    """
    reeks = reeks if reeks is not None else lees_index()
    if not reeks:
        return {"factor": 1.0, "geindexeerd": False}

    maanden = sorted(reeks)
    if vanaf not in reeks:
        # De dichtstbijzijnde maand die er wel is
        eerder = [m for m in maanden if m <= vanaf]
        vanaf = eerder[-1] if eerder else maanden[0]

    laatste = maanden[-1]
    basis, nu = reeks[vanaf], reeks[laatste]
    if not basis:
        return {"factor": 1.0, "geindexeerd": False}

    factor = nu / basis
    return {
        "factor": round(factor, 4),
        "geindexeerd": True,
        "vanaf": vanaf,
        "tot": laatste,
        "pct": round((factor - 1) * 100, 1),
    }


def omschrijf(info):
    """Een zin bij de indexering, voor in de brief."""
    if not info.get("geindexeerd"):
        return ("De verbouwkosten zijn niet geindexeerd: de bouwkostenindex "
                "kon niet worden opgehaald. De bedragen hebben peildatum "
                f"{PEILDATUM} en lopen dus achter.")
    richting = "gestegen" if info["pct"] >= 0 else "gedaald"
    return (f"Verbouwkosten geindexeerd van {info['vanaf']} naar "
            f"{info['tot']}: de bouwkosten zijn in die periode "
            + f"{abs(info['pct']):.1f}".replace(".", ",")
            + f"% {richting}. Bron: CBS inputprijsindex bouwkosten "
              f"nieuwbouwwoningen, tabel {TABEL}.")


def main():
    # Zelfde host als de woningprijsindex, en daar bleek het IPv6-verkeer van de
    # runner nergens heen te kunnen. Dus hier ook over IPv4.
    try:
        from woningprijsindex import alleen_ipv4
        alleen_ipv4()
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--vanaf", default=PEILDATUM)
    ap.add_argument("--verversen", action="store_true")
    args = ap.parse_args()

    reeks = lees_index()
    vorige_maand = (dt.date.today().replace(day=1)
                    - dt.timedelta(days=1)).strftime("%Y-%m")

    # Verversen als het bestand ontbreekt of de laatste maand mist. Het CBS
    # publiceert circa dertig dagen na de verslagmaand, dus twee maanden
    # achterstand is normaal.
    if args.verversen or not reeks or max(reeks, default="") < vorige_maand:
        print(f"Bouwkostenindex ophalen (tabel {TABEL})", file=sys.stderr)
        nieuw = haal_index()
        if nieuw:
            reeks = nieuw
            schrijf_index(reeks)
            print(f"  {len(reeks)} maanden, laatste: {max(reeks)}",
                  file=sys.stderr)
        else:
            print("  niets opgehaald; de bestaande reeks blijft staan",
                  file=sys.stderr)

    info = indexfactor(args.vanaf, reeks)
    print(omschrijf(info))
    if info.get("geindexeerd"):
        print(f"factor: {info['factor']}", file=sys.stderr)


if __name__ == "__main__":
    main()
