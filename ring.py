"""
De ring: welke buurten de brief volgt. De enige plek waar dat staat.

WAAROM EEN EIGEN BESTAND. Op 15 oktober 2026 stond de lijst op vijf plekken
met de hand uitgeschreven: marktprijzen_bag, buurten_tabel, drie keer in
brief_verhalend en als terugval in buurtinventaris. Een buurt erbij zetten in
marktprijzen_bag had de CBS-tabel, de buurtportretten en de weetjes niet
geraakt. Dat is dezelfde fout als een lijst met namen die bijgewerkt moet
worden, en die fout is hier vaker gemaakt. Dit bestand importeert niets, zodat
elk script het kan lezen zonder marktprijzen_bag mee te laden.

WAT ER AAN HANGT als je een buurt toevoegt. buurtinventaris haalt bij de
eerstvolgende run de postcodes op (de workflow ziet zelf dat de inventaris de
ring niet meer dekt), de voorraad haalt daarna de woningen en labels op, en
start de inhaalslag van de 3D BAG als er meer dan 300 panden bij zijn
gekomen. Er hoeft dus niets met de hand. De huur per buurt is sinds 20 oktober 2026
een meting (marktprijzen_bag.huur_per_buurt en huur_referentie); een nieuwe
buurt valt op de stad terug tot hij genoeg advertenties heeft. De
beschermde gezichten worden sinds 18 oktober 2026 per pand gemeten
(gezicht.py), en de nieuwe panden krijgen die meting vanzelf.

GESCHIEDENIS.
  tot 15-10-2026  Stadscentrum, Benedenstad, Bottendaal, Galgenveld, Altrade,
                  Biezen.
  15-10-2026      Hunnerberg en St. Anna erbij, op verzoek van Mark. Gemeten in
                  kamerverhuur_per_buurt.json: St. Anna 65 en Hunnerberg 50
                  kamerverhuurobjecten, meer dan Biezen (46) en Benedenstad
                  (16) die al in de ring zaten. De namen zijn zoals het CBS en
                  de locatieserver ze schrijven.
"""

BUURTEN = (
    "Stadscentrum", "Benedenstad", "Bottendaal", "Galgenveld",
    "Altrade", "Biezen", "Hunnerberg", "St. Anna",
)

# Aan welke kant van het centrum, alleen voor de CBS-tabel in de brief.
ZIJDE = {"Biezen": "west", "St. Anna": "zuid"}


def zijde(buurt):
    return ZIJDE.get(buurt, "oost")


def elders_uitgeschreven(map_=".", drempel=4):
    """
    Welke andere .py-bestanden een eigen lijst van de ring bevatten.

    Telt per bestand hoeveel ringnamen er binnen vijf opeenvolgende regels als
    string tussen aanhalingstekens staan. Vier of meer is een lijst, geen
    toevallige vermelding in een zin. Woordenboeken met een waarde per buurt
    (de huuraanname, de beschermde gezichten) tellen niet: dat zijn gegevens,
    geen definitie van de ring. Commentaarregels tellen niet mee, want
    daar mag de geschiedenis van de ring best staan.
    """
    import glob
    import os
    import re
    gevonden = []
    for pad in sorted(glob.glob(os.path.join(map_, "*.py"))):
        if os.path.basename(pad) == "ring.py":
            continue
        try:
            with open(pad, encoding="utf-8") as f:
                regels = [r for r in f if not r.lstrip().startswith("#")]
        except OSError:
            continue
        for i in range(len(regels)):
            stuk = "".join(regels[i:i + 5])
            # Als sleutel van een woordenboek ("Biezen": 18) is het gegevens
            # per buurt, geen lijst van de ring; die tellen niet.
            n = sum(1 for b in BUURTEN
                    for q in ('"', "'")
                    if re.search(re.escape(q + b + q) + r"(?!\s*:)", stuk))
            if n >= drempel:
                gevonden.append(os.path.basename(pad))
                break
    return gevonden


def proef():
    """De ring heeft geen dubbele namen en elke naam is een echte string."""
    import sys
    afw = []
    if len(set(BUURTEN)) != len(BUURTEN):
        afw.append("een buurt staat dubbel in de ring")
    if any(not isinstance(b, str) or b != b.strip() or not b for b in BUURTEN):
        afw.append("een buurtnaam is leeg of heeft spaties eromheen")
    for pad in elders_uitgeschreven():
        afw.append(f"{pad} schrijft de ring zelf uit in plaats van ring.py te lezen")
    for a in afw:
        print("AFWIJKING: " + a, file=sys.stderr)
    print(f"Proef ring: {len(afw)} afwijkingen", file=sys.stderr)
    return 1 if afw else 0


if __name__ == "__main__":
    # python3 ring.py --proef; zonder argument doet het hetzelfde.
    import sys
    sys.exit(proef())
