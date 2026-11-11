#!/usr/bin/env python3
"""
De maximale kale huur per punt, voor zelfstandige (WWS) en onzelfstandige
(WWSO) woonruimte, per kalenderjaar.

EEN BRON. Tot 11 november stond deze tabel drie keer in het ecosysteem: in de
beheer-app (huurtabellen.json), en in wwso.py van de vastgoedbrief, die de
WWSO-tabel boven 100 punten benaderde met een vaste stap van € 5,2747 per punt.
Die benadering week bij 137 van de 150 puntenaantallen tussen 101 en 250 af van
de officiele tabel, tot € 0,13 bij 243 punten. Nu staat de tabel hier, en lezen
de app en de brief hem hiervandaan.

BRON. Volkshuisvesting Nederland, "Maximale huurprijsgrenzen", per 1 januari,
als xlsx; de vindplaats per jaar staat in huurtabellen.json onder "bronnen".
Elk jaar in oktober of november verschijnt de tabel voor het volgende jaar.
Die komt erin via een pull request, en proef() meet hem na.

Boven 250 punten telt elk punt als het verschil tussen 249 en 250.
"""
import datetime as dt
import json
import os
import sys

PAD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "huurtabellen.json")
STELSELS = ("zelfstandig", "onzelfstandig")

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


def jaar_voor(stelsel, jaar=None, tabellen=None):
    """
    Het jaar van de tabel die geldt: het gevraagde jaar, of het laatste jaar
    dat er is en niet later valt. Geeft (jaar, actueel) terug; actueel is
    False als de tabel van het gevraagde jaar ontbreekt.
    """
    t = (tabellen or lees())[stelsel]
    jaar = int(jaar or dt.date.today().year)
    beschikbaar = sorted(int(j) for j in t)
    eerder = [j for j in beschikbaar if j <= jaar]
    if not eerder:
        raise KeyError(f"geen {stelsel} tabel voor {jaar} of eerder")
    return eerder[-1], eerder[-1] == jaar


def max_huur(stelsel, punten, jaar=None, tabellen=None):
    """De maximale kale huur bij dit puntenaantal, afgerond op hele punten."""
    j, _ = jaar_voor(stelsel, jaar, tabellen)
    rij = (tabellen or lees())[stelsel][str(j)]
    p = max(0, int(round(punten)))
    if p <= 250:
        return rij[p]
    return round(rij[250] + (p - 250) * (rij[250] - rij[249]), 2)


# IJKPUNTEN UIT DE OFFICIELE TABELLEN. Wie een nieuw jaar toevoegt, zet hier
# twee waarden uit dat jaar bij, rechtstreeks uit het xlsx van de bron.
IJKPUNTEN = (
    ("zelfstandig", 2026, 159, 1042.73),
    ("zelfstandig", 2026, 40, 250.26),
    ("onzelfstandig", 2026, 100, 822.35),
    ("onzelfstandig", 2026, 101, 827.56),
)


def proef(tabellen=None):
    fouten = []
    d = tabellen or lees()
    for stelsel in STELSELS:
        for jaar, rij in sorted(d.get(stelsel, {}).items()):
            if len(rij) != 251:
                fouten.append(f"{stelsel} {jaar}: {len(rij)} waarden, verwacht "
                              f"251 (0 t/m 250 punten)")
                continue
            daalt = [p for p in range(1, 251) if rij[p] < rij[p - 1]]
            if daalt:
                fouten.append(f"{stelsel} {jaar}: daalt bij {daalt[:5]}")
            if f"{stelsel}_{jaar}" not in d.get("bronnen", {}):
                fouten.append(f"{stelsel} {jaar}: geen bron vermeld")
    for stelsel, jaar, p, wil in IJKPUNTEN:
        try:
            echt = max_huur(stelsel, p, jaar, d)
        except Exception as e:
            fouten.append(f"ijkpunt {stelsel} {jaar} {p}: {e}")
            continue
        if abs(echt - wil) > 0.005:
            fouten.append(f"ijkpunt {stelsel} {jaar} {p} punten: {echt}, "
                          f"verwacht {wil}")
    # HET LOPENDE JAAR MOET ER ZIJN. Op 1 januari wordt deze proef rood als de
    # nieuwe tabel ontbreekt; dan rekent alles anders stil met vorig jaar.
    nu = dt.date.today().year
    for stelsel in STELSELS:
        if str(nu) not in d.get(stelsel, {}):
            fouten.append(f"de {stelsel} tabel voor {nu} ontbreekt")
    # DE PROEF MOET ZIJN EIGEN FOUT ZIEN. Een tabel met een verschoven waarde
    # moet het ijkpunt laten afgaan.
    if tabellen is None:
        kapot = json.loads(json.dumps(d))
        kapot["zelfstandig"]["2026"][159] += 1
        if not proef_stil(kapot):
            fouten.append("een verkeerde waarde bij 159 punten wordt niet gezien")
    for f in fouten:
        print(f"FOUT {f}", file=sys.stderr)
    if tabellen is None:
        print(f"Proef huurtabel: {len(fouten)} fouten. Gedekt: 251 waarden per "
              f"tabel, nooit dalend, bron per jaar, {len(IJKPUNTEN)} ijkpunten, "
              f"de tabel van {nu}, en dat een verkeerde waarde wordt gezien.",
              file=sys.stderr)
    return 1 if fouten else 0


def proef_stil(tabellen):
    """True als proef() op deze tabellen een fout vindt, zonder te printen."""
    oud = sys.stderr
    try:
        sys.stderr = open(os.devnull, "w")
        return proef(tabellen) != 0
    finally:
        sys.stderr.close()
        sys.stderr = oud


if __name__ == "__main__":
    if "--proef" in sys.argv:
        sys.exit(proef())
    print(__doc__)
    sys.exit(0)
