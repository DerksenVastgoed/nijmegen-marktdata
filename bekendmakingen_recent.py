#!/usr/bin/env python3
"""
Alle officiële bekendmakingen van de gemeente Nijmegen van de laatste weken.

WAAROM DIT BESTAAT. Tot 11 november haalde de vastgoedbrief zijn bekendmakingen
zelf op, met een filter op de ring en op een lijst straten. Die lijst stond in
de code, en daar stonden ook straten tussen waar de eigenaars van de brief
panden hebben. In een openbare repo hoort zo'n lijst niet. Daarom haalt deze
module alles van Nijmegen op, zonder enige selectie, en kiest de brief daarna
zelf wat hij wil lezen.

WAT ER IN bekendmakingen_recent.json STAAT.
  opgehaald  tijdstip van de laatste geslaagde ronde, in UTC
  vanaf      de eerste dag die is opgevraagd
  records    elke bekendmaking als {titel, datum, type, url}
  fout       leeg, of de reden dat de laatste poging mislukte

"NIET OPGEHAALD" IS NIET "NIETS GEPUBLICEERD". Mislukt een ronde, dan blijft
het vorige bestand staan met zijn eigen tijdstip, en komt de reden in "fout".
Een lezer ziet zo aan opgehaald hoe oud de gegevens zijn, in plaats van een
lege lijst die eruitziet als een rustige week.
"""
import argparse
import datetime as dt
import json
import os
import sys

import sru

PAD = "bekendmakingen_recent.json"
DAGEN = 30


def lees(pad=PAD):
    try:
        with open(pad, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def ronde(dagen=DAGEN, pad=PAD, haal=None, nu=None):
    """
    Haal de laatste `dagen` dagen op en schrijf ze weg. Geeft 0 bij succes.

    haal en nu zijn er voor de proef: een nep-SRU en een vaste klok.
    """
    nu = nu or dt.datetime.now(dt.timezone.utc)
    vanaf = (nu.date() - dt.timedelta(days=dagen)).isoformat()
    haal = haal or (lambda cql: sru.haal(cql))
    oud = lees(pad)
    try:
        records = [sru.parse_record(r) for r in haal(sru.bouw_cql(vanaf))]
    except Exception as e:
        oud["fout"] = f"{nu.isoformat(timespec='seconds')}: {str(e)[:200]}"
        with open(pad, "w", encoding="utf-8") as f:
            json.dump(oud, f, ensure_ascii=False, indent=1)
        print(f"NIET OPGEHAALD: {e}. Het vorige bestand blijft staan "
              f"(opgehaald {oud.get('opgehaald') or 'nooit'}).", file=sys.stderr)
        return 1
    gezien, uniek = set(), []
    for r in records:
        k = (r["titel"], r["datum"], r["url"])
        if k not in gezien:
            gezien.add(k)
            uniek.append(r)
    uniek.sort(key=lambda r: (r["datum"], r["titel"]), reverse=True)
    uit = {"opgehaald": nu.isoformat(timespec="seconds"), "vanaf": vanaf,
           "bron": sru.SRU_URL, "records": uniek, "fout": ""}
    with open(pad, "w", encoding="utf-8") as f:
        json.dump(uit, f, ensure_ascii=False, indent=1)
    print(f"{len(uniek)} bekendmakingen van {vanaf} tot nu "
          f"({len(records) - len(uniek)} dubbel)", file=sys.stderr)
    return 0


def proef():
    import tempfile
    import xml.etree.ElementTree as ET
    fouten = []

    def check(naam, echt, wil):
        if echt != wil:
            fouten.append(f"{naam}: {echt!r}, verwacht {wil!r}")

    recs = [el for el in ET.fromstring(sru.VOORBEELD).iter()
            if sru.lokaal(el.tag) == "record"]
    klok = dt.datetime(2026, 11, 11, 14, 0, tzinfo=dt.timezone.utc)
    with tempfile.TemporaryDirectory() as t:
        pad = os.path.join(t, "r.json")
        check("geslaagde ronde", ronde(10, pad, lambda c: recs + recs, klok), 0)
        d = lees(pad)
        check("dubbel eruit", len(d.get("records") or []), 2)
        check("tijdstip", d.get("opgehaald"), "2026-11-11T14:00:00+00:00")
        check("vanaf", d.get("vanaf"), "2026-11-01")
        check("geen fout", d.get("fout"), "")

        # EEN MISLUKTE RONDE LAAT HET VORIGE BESTAND STAAN, met de reden.
        # Zonder dit zou een storing bij de SRU een lege lijst schrijven, en
        # dan leest de brief "vandaag niets gepubliceerd".
        def stuk(c):
            raise RuntimeError("503")
        later = klok + dt.timedelta(hours=3)
        check("mislukte ronde geeft 1", ronde(10, pad, stuk, later), 1)
        d = lees(pad)
        check("records blijven", len(d.get("records") or []), 2)
        check("tijdstip blijft het oude", d.get("opgehaald"),
              "2026-11-11T14:00:00+00:00")
        check("fout genoemd", "503" in (d.get("fout") or ""), True)

    for f in fouten:
        print(f"FOUT {f}", file=sys.stderr)
    print(f"Proef bekendmakingen_recent: {len(fouten)} fouten. Gedekt: een "
          f"ronde schrijft records, tijdstip en begindatum, haalt dubbele eruit, "
          f"en een mislukte ronde laat het vorige bestand staan met de reden.",
          file=sys.stderr)
    return 1 if fouten else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dagen", type=int, default=DAGEN)
    ap.add_argument("--proef", action="store_true")
    a = ap.parse_args()
    sys.exit(proef() if a.proef else ronde(a.dagen))
