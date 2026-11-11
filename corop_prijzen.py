#!/usr/bin/env python3
"""
Prijzen en transacties voor het COROP-gebied Arnhem/Nijmegen.

Waarom dit naast de bestaande cijfers staat: de brief zette onze eigen
vraagprijsmedianen tot nu toe af tegen de CBS-index voor heel Gelderland. Daar
zitten Winterswijk en Nijmegen in dezelfde bak. Het COROP-gebied
Arnhem/Nijmegen is een stuk dichterbij, en uit dezelfde tabel komt het aantal
transacties, wat iets zegt over de krapte in de markt.

Landelijk, provincie en COROP blijven alle drie in beeld: wijken ze van elkaar
af, dan is dat verschil zelf het signaal.

Bron: CBS-tabel 85819NED, prijsindex 2020=100 per COROP-gebied, ongeveer 22
dagen na afloop van een kwartaal.
"""
import argparse
import datetime as dt
import json
import sys

TABEL = "85819NED"
UIT_PAD = "corop_prijzen.json"
# Niet de code raden maar opzoeken: CBS hernummert gebieden af en toe, en een
# verkeerde code levert stilletjes de cijfers van een andere regio op.
ZOEK_REGIO = "arnhem/nijmegen"
KWARTALEN = 16


def _cbs():
    """De ophaalfuncties van de woningprijsindex hergebruiken."""
    from woningprijsindex import _haal, BASIS, alleen_ipv4
    alleen_ipv4()
    return _haal, BASIS


def regiocode(haal, basis):
    """
    De code van het COROP-gebied, opgezocht op naam.

    Geeft None terug als het gebied er niet tussen staat; dan schrijven we
    liever niets dan de cijfers van de verkeerde regio.
    """
    rijen = haal(f"{basis}/{TABEL}/RegioS")
    for rij in rijen:
        titel = (rij.get("Title") or "").strip().lower()
        if ZOEK_REGIO in titel.replace(" ", ""):
            # De sleutel ongewijzigd teruggeven, mét de spaties die het CBS
            # eraan plakt. Op de afgeknipte code levert het filter nul rijen op
            # en haalt het script elke run de hele tabel van ruim vijfduizend
            # rijen op. Met de volledige sleutel is het een paar honderd.
            return rij.get("Key", ""), rij.get("Title", "").strip()
    for rij in rijen:                      # ruimer: los van de schuine streep
        titel = (rij.get("Title") or "").lower()
        if "arnhem" in titel and "nijmegen" in titel:
            return rij.get("Key", ""), rij.get("Title", "").strip()
    return None, None


def _getal(waarde):
    try:
        return float(waarde)
    except (TypeError, ValueError):
        return None


def _veld_een_van(rij, *woordsets):
    """Het eerste veld dat bij een van deze woordcombinaties past."""
    for woorden in woordsets:
        waarde = _veld(rij, *woorden)
        if waarde is not None:
            return waarde
    return None


def _veld(rij, *woorden):
    """
    De waarde van het eerste veld waarvan de naam al deze woorden bevat.

    De kolomnamen van het CBS eindigen op een volgnummer dat per tabelversie
    verandert, en soms wijzigt de naam zelf. Zoeken op woorden is daarom
    steviger dan een vaste sleutel, en voorkomt dat een naamswijziging
    stilletjes lege cijfers oplevert.
    """
    for sleutel, waarde in rij.items():
        laag = sleutel.lower()
        if all(w in laag for w in woorden):
            g = _getal(waarde)
            if g is not None:
                return g
    return None


def kwartaalreeks(rijen):
    """De kwartaalrijen op volgorde, met de velden die we gebruiken."""
    uit = {}
    for rij in rijen:
        # De periodesleutel heet Perioden, maar in een Engelstalige variant
        # Periods; daarom zoeken in plaats van aannemen.
        periode = ""
        for sleutel, waarde in rij.items():
            if "period" in sleutel.lower():
                periode = str(waarde or "").strip()
                break
        if "KW" not in periode.upper():    # jaar- en maandrijen overslaan
            continue
        # Nederlandse en Engelse kolomnamen allebei afvangen; het CBS biedt
        # sommige tabellen in beide talen aan en de opzet wijkt dan af.
        uit[periode] = {
            "index": _veld_een_van(rij, ("prijsindex",), ("priceindex",)),
            "kwartaal_pct": _veld_een_van(rij, ("ontwikkeling", "vorige"),
                                          ("development", "previous")),
            "jaar_pct": _veld_een_van(rij, ("ontwikkeling", "jaar"),
                                      ("development", "year")),
            "transacties": _veld_een_van(rij, ("aantal", "woningen"),
                                         ("number", "dwellings"),
                                         ("aantal", "verkocht")),
            "gemiddelde_prijs": _veld_een_van(rij, ("gemiddelde", "prijs"),
                                              ("average", "price")),
        }
        uit[periode]["transacties_jaar_pct"] = None
    return uit


def samenvatting(reeks, regionaam):
    """Wat de brief nodig heeft: de laatste stand en de richting."""
    if not reeks:
        return None
    laatste = max(reeks)
    r = reeks[laatste]
    return {
        "gebied": regionaam,
        "periode": laatste,
        "index": r["index"],
        "kwartaal_pct": r["kwartaal_pct"],
        "jaar_pct": r["jaar_pct"],
        "transacties": r["transacties"],
        "transacties_jaar_pct": r["transacties_jaar_pct"],
        "gemiddelde_prijs": r["gemiddelde_prijs"],
        "reeks": {k: reeks[k] for k in sorted(reeks)[-KWARTALEN:]},
        "opgehaald": dt.date.today().isoformat(),
        "bron": f"CBS {TABEL}, prijsindex bestaande koopwoningen per COROP",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uit", default=UIT_PAD)
    ap.add_argument("--stil", action="store_true")
    args = ap.parse_args()

    try:
        haal, basis = _cbs()
    except Exception as e:
        print(f"CBS-hulpfuncties niet te laden: {str(e)[:120]}", file=sys.stderr)
        return 1

    try:
        code, naam = regiocode(haal, basis)
    except Exception as e:
        print(f"Regiolijst niet op te halen: {str(e)[:120]}", file=sys.stderr)
        return 1
    if not code:
        print(f"COROP-gebied met '{ZOEK_REGIO}' niet gevonden in {TABEL}; "
              f"niets weggeschreven", file=sys.stderr)
        return 1

    try:
        rijen = haal(f"{basis}/{TABEL}/TypedDataSet",
                     {"$filter": f"RegioS eq '{code}'"})
    except Exception as e:
        print(f"Cijfers niet op te halen: {str(e)[:120]}", file=sys.stderr)
        return 1

    reeks = kwartaalreeks(rijen)
    if not reeks:
        # Het CBS bewaart regiocodes met spaties erachter. Een filter op de
        # afgeknipte code kan daardoor niets opleveren. Dan halen we de tabel
        # zonder filter op en zoeken we de regio er zelf uit.
        print(f"Geen kwartaalrijen bij filter op '{code}' ({len(rijen)} rijen "
              f"terug); nu zonder filter. Kost een paar seconden extra; als dit "
              f"elke run gebeurt, klopt de sleutel niet", file=sys.stderr)
        try:
            alles = haal(f"{basis}/{TABEL}/TypedDataSet")
        except Exception as e:
            print(f"Ook zonder filter niets: {str(e)[:120]}", file=sys.stderr)
            return 1
        eigen = [r for r in alles
                 if str(r.get("RegioS", "")).strip() == code.strip()]
        print(f"Zonder filter: {len(alles)} rijen, waarvan {len(eigen)} voor "
              f"{naam}", file=sys.stderr)
        if alles and not eigen:
            print(f"Voorbeeld van een rij: "
                  f"{list(alles[0].items())[:6]}", file=sys.stderr)
        reeks = kwartaalreeks(eigen)

    stand = samenvatting(reeks, naam)
    if not stand:
        print("Geen kwartaalcijfers gevonden; zie de regels hierboven voor "
              "wat de bron wel teruggaf", file=sys.stderr)
        return 1

    with open(args.uit, "w", encoding="utf-8") as f:
        json.dump(stand, f, ensure_ascii=False, indent=1)
    # Deze regel ook bij --stil, want anders eindigt het logboek zonder
    # uitkomst en lijkt het alsof de stap halverwege is gestopt.
    print(f"{naam} {stand['periode']}: index {stand['index']}, "
          f"{stand['jaar_pct']}% op jaarbasis, "
          f"{int(stand['transacties'] or 0)} transacties", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
