#!/usr/bin/env python3
"""
Telt per ringbuurt hoeveel adressen er zijn en levert de postcodes als
werkvoorraad.

Bron: de PDOK-locatieserver, dezelfde dienst die marktprijzen_bag.py al
gebruikt om de buurt van een adres op te zoeken. Open data, geen sleutel, en
hij kan filteren op buurtnaam.

WAAROM DIT BESTAAT. De gegevens over oppervlakte en energielabel komen nu
binnen op het moment dat een pand te koop staat. Daardoor kennen we de voorraad
alleen voor zover die in de verkoop is geweest: 1.260 panden met 6.338
adressen. Een vraag als "welke panden in Bottendaal zijn groter dan 150 m2 met
label E of slechter" is daarmee niet te stellen, en dat is precies de vraag die
een acquisitielijst oplevert in plaats van een reactie op het aanbod.

WAT DE EERSTE METING OPLEVERDE, op 9 oktober 2026, en waarom dit script er nu
anders uitziet dan toen:

  1. De locatieserver levert GEEN pand-id. Het veld pandid werd gevraagd en
     kwam bij geen enkel adres terug. De eerste opzet haalde alle adressen op
     om daaruit de panden te verzamelen, en kwam dus op nul panden uit. Dat het
     script opschreef welke gevraagde velden ontbraken, is wat dat aan het
     licht bracht in plaats van een stille nul.
  2. De paginering loopt vast bij tienduizend. Stadscentrum meldde 11.975
     adressen en leverde er 10.100; dat is de grens die Solr aan diep
     doorbladeren stelt. De meting was daar dus onvolledig.
  3. Een adres is niet een woning. In type:adres zitten ook winkels,
     kantoren, garageboxen en bergingen.

WAT ER OP 10 OKTOBER BIJ KWAM, en wat punt 2 en 3 hierboven in een ander licht
zet: dit script filterde op buurtnaam zonder de gemeente erbij, en die
buurtnamen bestaan elders in Nederland ook. Gemeten met en zonder het
gemeentefilter:

  Altrade         3.452    3.452        0 vervuild
  Bottendaal      2.568    2.568        0
  Galgenveld      4.287    3.494      793
  Benedenstad     5.098    1.911    3.187   (62 procent)
  Biezen          9.443    6.083    3.360
  Stadscentrum   11.975    7.357    4.618
  TOTAAL         36.823   24.865   11.958   (32 procent)

Altrade en Bottendaal zijn als buurtnaam uniek voor Nijmegen en hadden niets;
de andere vier haalden adressen uit Boskoop, Nieuwegein, Amersfoort, Vianen,
Gorinchem, Dongen, Doetinchem en Assen.

Dat verklaart twee dingen die eerder als eigenaardigheid waren opgeschreven.
Benedenstad gold als het uiterste bewijs dat een adres geen woning is, 5.098
adressen tegen 1.639 woningen van het CBS. Dat was geen eigenaardigheid van
Benedenstad maar 62 procent vervuiling: 1.911 tegen 1.639 is gewoon
plausibel. En Stadscentrum liep tegen de grens van tienduizend aan met 11.975,
maar werkelijk zijn het er 7.357. Daarmee wordt de grens van Solr niet meer
geraakt. De eigen noodrem MAX_PER_BUURT stond op vijfduizend en werd door
Stadscentrum en Biezen nog wel geraakt, en die is daarom naar 9.500 gezet:
nu past elke buurt in één ronde, is die ronde compleet, en gaat de tweede
ronde per straat met haar bekende gat niet meer af. Hij blijft staan als
vangnet, niet als vaste werkwijze.

Daarom haalt dit script nu twee dingen op, en geen adressen meer. Het aantal
adressen per buurt komt uit het veld numFound van een vraag met rows=0: één
verzoek, geen paginering, dus ook geen grens van tienduizend. En de postcodes
komen uit type:postcode, een paar honderd per buurt, ruim onder die grens en
dus compleet.

Die postcodes zijn de werkvoorraad voor de volgende stap. Een BAG-vraag met
postcode levert alle adressen in die postcode mét pandIdentificatie,
oppervlakte en gebruiksdoel in één keer. Dat is ongeveer 1.750 vragen voor de
hele ring, in plaats van een vraag per adres, en het levert meteen het
onderscheid tussen een woning en een garagebox.

Gebruik:
  python buurtinventaris.py                 # alle ringbuurten uit ring.py
  python buurtinventaris.py --buurt Biezen  # een enkele buurt, om te proeven
  python buurtinventaris.py --uit elders.json
"""

import argparse
import datetime as dt
import json
import sys
import time

import requests

PDOK = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free"
PDOK_HEADERS = {"User-Agent": "NijmegenVastgoedMonitor/1.0"}
UIT = "buurtinventaris.json"
GESCHIEDENIS = "pandgeschiedenis.json"

# Honderd per vraag is wat de locatieserver aan een gewone zoekopdracht geeft.
PER_VRAAG = 100

# Noodrem tegen een eindeloze lus, en niet de grens van de dienst zelf. Solr
# stopt bij tienduizend; dit blijft daaronder.
#
# WAAROM DIT VAN VIJFDUIZEND OMHOOG IS. Met het gemeentefilter erbij is de
# grootste buurt Stadscentrum met 7.357 adressen en de tweede Biezen met
# 6.083. Op vijfduizend raakten die twee dus de noodrem, en dan gaat de tweede
# ronde per straat af. Die ronde heeft een bekend gat: een straat die volledig
# buiten de eerste ronde viel komt er niet in voor, want de straatnamen komen
# uit de eerste ronde. Met 9.500 past elke buurt in één ronde en is die ronde
# compleet, en blijft de noodrem bestaan voor het geval een buurt ooit groeit.
#
# Zonder het filter was Stadscentrum 11.975 en liep hij ook tegen de grens van
# Solr aan: 11.975 gemeld, 10.100 geleverd. Dat is dus twee keer hetzelfde
# probleem, en de vervuiling was in beide gevallen de oorzaak.
MAX_PER_BUURT = 9500


def buurten_lijst():
    """
    De ringbuurten, uit ring.py.

    Eén plek waar die namen staan. Twee lijsten gaan uit elkaar lopen, en dan
    meet dit script een andere ring dan de brief beschrijft. Hier stond een
    eigen terugvallijst voor als de import mislukte; die is weg, want een
    terugval die stil de oude ring meet is erger dan een fout. ring.py
    importeert niets en kan dus niet mislukken.
    """
    import ring
    return list(ring.BUURTEN)


def dekt_ring(pad=None):
    """
    Dekt de bewaarde inventaris alle buurten van de ring?

    WAAROM. De workflow ververst de inventaris alleen op zondag of als het
    bestand ontbreekt. Op 15 oktober kwamen Hunnerberg en St. Anna erbij; zonder
    deze toets had de voorraad tot zondag de nieuwe buurten niet gekend, en
    daarna pas de labels en de 3D BAG. Nu ziet de workflow het zelf.
    """
    pad = pad or UIT
    try:
        with open(pad, encoding="utf-8") as f:
            per = json.load(f).get("postcodes_per_buurt") or {}
    except Exception:
        return False
    return all(per.get(b) for b in buurten_lijst())


def _vraag(params):
    """Eén verzoek aan de locatieserver, of None bij een fout."""
    try:
        r = requests.get(PDOK, params=params, headers=PDOK_HEADERS, timeout=30)
        r.raise_for_status()
        return r.json().get("response", {})
    except Exception as e:
        print(f"  locatieserver: {e}", file=sys.stderr)
        return None


VELDEN = "postcode straatnaam buurtnaam gemeentenaam"

# DE GEMEENTE ERBIJ, WANT BUURTNAMEN ZIJN NIET UNIEK.
#
# Dit filterde op buurtnaam alleen: fq=["type:adres", 'buurtnaam:"Biezen"'].
# Die buurtnamen bestaan elders in Nederland ook, en daardoor stonden er in
# buurtinventaris.json 491 postcodes van de 1.733 die niet in Nijmegen liggen:
# 2771 Boskoop, 3431 Nieuwegein, 3828 Amersfoort, 4131 Vianen, 4201 Gorinchem,
# 5103 Dongen, 7001 Doetinchem en 9401 Assen. Altrade en Bottendaal zijn als
# buurtnaam uniek voor Nijmegen en hadden nul vervuiling; Benedenstad, Biezen,
# Galgenveld en Stadscentrum hadden het wel.
#
# Dat raakte meer dan de postcodes. Het aantal adressen per buurt komt uit
# numFound van dezelfde vraag, dus die 34.946 adressen waren op dezelfde manier
# te hoog, en de straatnamen die de tweede ronde per straat gebruikt ook.
#
# GEMEENTE EN NIET WOONPLAATS. Gemeente Nijmegen bevat ook de woonplaatsen
# Lent, Oosterhout en Ressen. Filteren op woonplaatsnaam zou die eruit gooien.
# Onze zes buurten liggen om het centrum, dus dat zou nu niets schelen, maar
# het is de verkeerde grens om te kiezen.
GEMEENTE = "Nijmegen"
GEMEENTEVELD = "gemeentenaam"


def _basis_fq(buurt):
    """De filter voor één buurt, met de gemeente erbij."""
    return ["type:adres", f'buurtnaam:"{buurt}"',
            f'{GEMEENTEVELD}:"{GEMEENTE}"']


def aantal_adressen(buurt):
    """
    Hoeveel adresseerbare objecten deze buurt heeft, uit numFound.

    Met rows=0 vraagt dit alleen de telling op en geen records. Eén verzoek,
    dus geen paginering en geen grens van tienduizend. Let op wat het telt:
    adressen, niet woningen. Winkels, kantoren, garageboxen en bergingen
    hebben ook een adres.

    Geeft (aantal, aantal_zonder_gemeentefilter) terug.

    HET FILTER CONTROLEERT ZICHZELF. Deze functie vraagt het ook zonder het
    gemeentefilter, en dat is geen verspilling van een verzoek maar de enige
    manier om te weten dat het filter werkelijk iets doet. Solr geeft namelijk
    geen fout op een veld waarop niet te filteren is; het negeert de filter en
    geeft dezelfde telling. Dat is exact hoe deze fout is ontstaan: een route
    die werkte werd vervangen door een route die stil hetzelfde deed. Het
    verschil tussen de twee tellingen is de vervuiling, en staat in de uitvoer.
    """
    antwoord = _vraag({"q": "*", "fq": _basis_fq(buurt),
                       "rows": 0, "wt": "json"})
    ruw = _vraag({"q": "*", "fq": ["type:adres", f'buurtnaam:"{buurt}"'],
                  "rows": 0, "wt": "json"})
    return (None if antwoord is None else antwoord.get("numFound"),
            None if ruw is None else ruw.get("numFound"))


def _sweep(fq, pauze, grens=None):
    """
    Doorbladeren tot de server niets meer geeft, of tot de grens.

    Geeft (records, gemeld, volledig) terug. Het gemelde aantal is wat de
    server zegt te hebben; dat vergelijken we met wat we ophaalden, want een
    stil afgekapte pagina is anders niet te zien.
    """
    # Niet als standaardwaarde in de functiekop: die wordt bij het inlezen
    # vastgeklonken, en dan heeft het aanpassen van MAX_PER_BUURT geen effect.
    # Dat kostte me een proef die leek te slagen terwijl de grens nooit werd
    # geraakt.
    if grens is None:
        grens = MAX_PER_BUURT
    records, gemeld, start = [], None, 0
    while start < grens:
        antwoord = _vraag({"q": "*", "fq": fq, "rows": PER_VRAAG,
                           "start": start, "fl": VELDEN, "wt": "json"})
        if antwoord is None:
            return records, gemeld, False
        if gemeld is None:
            gemeld = antwoord.get("numFound")
        docs = antwoord.get("docs") or []
        records.extend(docs)
        if len(docs) < PER_VRAAG:
            break
        start += PER_VRAAG
        time.sleep(pauze)
    volledig = gemeld is not None and len(records) >= gemeld
    return records, gemeld, volledig


def postcodes_van(buurt, pauze=0.2):
    """
    De postcodes van een buurt, uit de adresrecords.

    EERST GEPROBEERD EN HET WERKTE NIET: type:postcode met een filter op
    buurtnaam. Dat leverde op 10 oktober nul records voor alle zes de buurten,
    terwijl dezelfde filter op type:adres er 34.946 gaf. Een postcoderecord
    geeft buurtnaam wel terug als je het opvraagt, maar je kunt er blijkbaar
    niet op filteren: in Solr kan een veld bewaard zijn zonder doorzoekbaar te
    zijn. Daarmee brak ik een route die werkte, en de stap meldde toch succes
    omdat er "|| echo overgeslagen" achter stond.

    Dus nu weer via de adressen, die bewezen werken, en de postcode staat op
    elk adresrecord. Blijft de buurt onder de grens die Solr aan diep
    doorbladeren stelt, dan is de lijst compleet. Stadscentrum liep daar op 9
    oktober tegenaan: 11.975 gemeld en 10.100 opgehaald. Voor die buurten komt
    er een tweede ronde per straat, want per straat zijn het er nooit meer dan
    een paar honderd. De straatnamen komen uit de eerste ronde, en een straat
    die volledig buiten de eerste tienduizend viel wordt daarmee gemist; de
    uitvoer zegt dan ook niet dat de buurt volledig is.
    """
    fq = _basis_fq(buurt)
    records, gemeld, volledig = _sweep(fq, pauze)
    postcodes = {(d.get("postcode") or "").replace(" ", "").upper()
                 for d in records}
    postcodes.discard("")
    straten = {d.get("straatnaam") for d in records if d.get("straatnaam")}
    extra_vragen = 0
    if not volledig and straten:
        for straat in sorted(straten):
            deel, _g, _v = _sweep(fq + [f'straatnaam:"{straat}"'], pauze,
                                  grens=2000)
            extra_vragen += 1
            for d in deel:
                pc = (d.get("postcode") or "").replace(" ", "").upper()
                if pc:
                    postcodes.add(pc)
    return sorted(postcodes), gemeld, len(records), volledig, extra_vragen


def bekend_uit_geschiedenis():
    """Wat we al hebben nagekeken, uit pandgeschiedenis.json."""
    try:
        with open(GESCHIEDENIS, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return 0, 0
    panden = d.get("_panden") or {}
    adressen = sum(len(v.get("bag_eenheden") or []) for v in panden.values()
                   if isinstance(v, dict))
    return len(panden), adressen


def proef():
    """
    De filter en de zelfcontrole nameten, zonder netwerk.

    WAAROM DIT NODIG IS. Solr geeft geen fout op een veld waarop niet te
    filteren is: het negeert de filter en geeft dezelfde telling terug. Deze
    hele fout is daardoor onopgemerkt gebleven, en een reparatie die stil
    niets doet zou op precies dezelfde manier onopgemerkt blijven. Dus wordt
    hier getoetst dat het verschil tussen de twee tellingen werkelijk wordt
    opgemerkt.
    """
    global _vraag
    echt = _vraag
    afw = []

    verwacht = ["type:adres", 'buurtnaam:"Biezen"', 'gemeentenaam:"Nijmegen"']
    if _basis_fq("Biezen") != verwacht:
        afw.append(f"de filter is {_basis_fq('Biezen')} in plaats van "
                   f"{verwacht}")
    if "gemeentenaam" not in VELDEN:
        afw.append("gemeentenaam staat niet in de gevraagde velden, dus het "
                   "veld komt niet terug op de records")

    stand = {"werkt": True}

    def nep(params):
        met_gemeente = any(GEMEENTEVELD in f for f in params.get("fq") or [])
        if met_gemeente and stand["werkt"]:
            return {"numFound": 1911, "docs": []}
        return {"numFound": 5098, "docs": []}

    try:
        _vraag = nep
        stand["werkt"] = True
        werkend = aantal_adressen("Benedenstad")
        stand["werkt"] = False
        genegeerd = aantal_adressen("Benedenstad")
    finally:
        _vraag = echt

    if werkend != (1911, 5098):
        afw.append(f"met een werkend filter kwam er {werkend} uit in plaats "
                   f"van (1911, 5098)")
    if genegeerd != (5098, 5098):
        afw.append(f"met een genegeerd filter kwam er {genegeerd} uit; dan "
                   f"is het verschil niet te zien en blijft de vervuiling "
                   f"onopgemerkt")
    if werkend[0] == werkend[1]:
        afw.append("de twee tellingen zijn gelijk terwijl het filter werkt; "
                   "dan meet deze proef niets")

    # Een inventaris van de oude ring dekt de nieuwe niet, en dat moet de
    # workflow zien; anders wacht een nieuwe buurt tot zondag.
    import os
    import tempfile
    ring_nu = buurten_lijst()
    with tempfile.TemporaryDirectory() as d:
        oud = os.path.join(d, "oud.json")
        vol = os.path.join(d, "vol.json")
        with open(oud, "w", encoding="utf-8") as f:
            json.dump({"postcodes_per_buurt": {b: ["6511AA"]
                                               for b in ring_nu[:-1]}}, f)
        with open(vol, "w", encoding="utf-8") as f:
            json.dump({"postcodes_per_buurt": {b: ["6511AA"]
                                               for b in ring_nu}}, f)
        if dekt_ring(oud):
            afw.append("een inventaris zonder de laatste ringbuurt telt als "
                       "dekkend; dan wordt een nieuwe buurt niet opgehaald")
        if not dekt_ring(vol):
            afw.append("een volledige inventaris telt als onvolledig; dan "
                       "wordt hij elke dag opnieuw opgehaald")

    for a in afw:
        print(f"AFWIJKING: {a}", file=sys.stderr)
    print(f"Proef: {len(afw)} afwijkingen. Gedekt: de filter zelf, dat "
          f"gemeentenaam wordt opgevraagd, en dat een genegeerd filter aan "
          f"het verschil tussen de twee tellingen te zien is.",
          file=sys.stderr)
    return 1 if afw else 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--uit", default=UIT)
    p.add_argument("--buurt", action="append",
                   help="Alleen deze buurt; meerdere keren te geven")
    p.add_argument("--pauze", type=float, default=0.2,
                   help="Seconden tussen twee pagina's")
    p.add_argument("--proef", action="store_true",
                   help="de filter nameten zonder netwerk")
    p.add_argument("--dekt-ring", action="store_true",
                   help="exitcode 0 als de bewaarde inventaris elke "
                        "ringbuurt kent, anders 1")
    args = p.parse_args()

    if args.proef:
        return proef()
    if args.dekt_ring:
        ok = dekt_ring(args.uit)
        print("Inventaris dekt de ring" if ok else
              "Inventaris mist een ringbuurt; opnieuw ophalen", file=sys.stderr)
        return 0 if ok else 1

    buurten = args.buurt or buurten_lijst()
    panden_bekend, adressen_bekend = bekend_uit_geschiedenis()
    print(f"Al nagekeken: {panden_bekend} panden met {adressen_bekend} "
          f"adressen", file=sys.stderr)

    per_buurt, postcodes_per_buurt, alle_postcodes = {}, {}, set()
    filter_deed_niets = []
    for naam in buurten:
        adressen, adressen_ruw = aantal_adressen(naam)
        (postcodes, gemeld, doorgebladerd,
         volledig, extra) = postcodes_van(naam, args.pauze)
        alle_postcodes |= set(postcodes)
        postcodes_per_buurt[naam] = postcodes
        buiten = ((adressen_ruw or 0) - (adressen or 0)
                  if adressen is not None and adressen_ruw is not None
                  else None)
        if adressen and adressen_ruw and adressen == adressen_ruw:
            filter_deed_niets.append(naam)
        per_buurt[naam] = {
            "adressen": adressen,
            "adressen_zonder_gemeentefilter": adressen_ruw,
            "adressen_buiten_de_gemeente": buiten,
            "adressen_doorgebladerd": doorgebladerd,
            "adressen_gemeld": gemeld,
            "postcodes": len(postcodes),
            "volledig": volledig,
            "tweede_ronde_per_straat": extra,
        }
        print(f"{naam}: {adressen} adressen, {doorgebladerd} doorgebladerd, "
              f"{len(postcodes)} postcodes"
              + (f", {buiten} adressen buiten {GEMEENTE} weggelaten"
                 if buiten else "")
              + (f", {extra} straten apart opgehaald" if extra else "")
              + ("" if volledig else "  LET OP: eerste ronde onvolledig"),
              file=sys.stderr)

    # HEEFT HET GEMEENTEFILTER IETS GEDAAN? Solr geeft geen fout op een veld
    # waarop niet te filteren is: het negeert de filter en geeft dezelfde
    # telling. Heet het veld anders dan GEMEENTEVELD, dan zou deze reparatie
    # dus stil niets doen en zou de inventaris precies zo vervuild blijven.
    # Altrade en Bottendaal zijn als buurtnaam uniek voor Nijmegen en hebben
    # werkelijk geen vervuiling, dus die horen hier thuis; alle zes is het
    # teken dat de filter wordt genegeerd.
    if len(filter_deed_niets) == len(per_buurt) and len(per_buurt) > 2:
        print(f"LET OP: het filter {GEMEENTEVELD}:\"{GEMEENTE}\" verandert "
              f"bij geen enkele buurt iets. Dan wordt het genegeerd en is de "
              f"inventaris nog net zo vervuild. Vraag de dienst welke velden "
              f"een adresrecord heeft.", file=sys.stderr)

    # DE POSTCODES NOG EEN KEER NAGEKEKEN, op het patroon waaraan de fout te
    # zien was. Dit is geen filter maar een melding: een getal in de uitvoer is
    # wat de volgende keer het verschil maakt tussen een stille fout en een
    # zichtbare.
    per_begin = {}
    for pc in alle_postcodes:
        per_begin[pc[:4]] = per_begin.get(pc[:4], 0) + 1
    vreemd = {k: v for k, v in per_begin.items() if not k.startswith("65")}
    if vreemd:
        print(f"LET OP: {sum(vreemd.values())} van de {len(alle_postcodes)} "
              f"postcodes beginnen niet met 65: "
              + ", ".join(f"{k} ({v})" for k, v in sorted(vreemd.items())),
              file=sys.stderr)

    totaal_adressen = sum(g["adressen"] or 0 for g in per_buurt.values())
    uit = {
        "opgehaald": dt.date.today().isoformat(),
        "bron": (f"PDOK locatieserver v3_1, filter op buurtnaam én "
                 f"{GEMEENTEVELD}:{GEMEENTE}"),
        "let_op": ("adressen is het aantal adresseerbare objecten en niet het "
                   "aantal woningen: winkels, kantoren en garageboxen hebben "
                   "ook een adres. Het onderscheid komt uit het gebruiksdoel "
                   "in de BAG, en dat zit niet in deze dienst."),
        "per_buurt": per_buurt,
        "totaal": {
            "adressen": totaal_adressen,
            "postcodes": len(alle_postcodes),
            "buurten_volledig": sum(1 for g in per_buurt.values()
                                    if g["volledig"]),
            "buurten_gevraagd": len(per_buurt),
            "postcodes_per_viercijferig": dict(sorted(per_begin.items())),
            "panden_al_nagekeken": panden_bekend,
            "adressen_al_nagekeken": adressen_bekend,
        },
        "postcodes_per_buurt": postcodes_per_buurt,
    }

    if not len(alle_postcodes):
        print("Geen enkele postcode opgehaald; bestand niet overschreven.",
              file=sys.stderr)
        return 1

    try:
        with open(args.uit, "w", encoding="utf-8") as f:
            json.dump(uit, f, ensure_ascii=False, indent=1, sort_keys=True)
    except Exception as e:
        print(f"Kon {args.uit} niet schrijven: {e}", file=sys.stderr)
        return 1

    t = uit["totaal"]
    print(f"\n{t['adressen']} adressen en {t['postcodes']} postcodes in "
          f"{t['buurten_gevraagd']} buurten, waarvan "
          f"{t['buurten_volledig']} volledig opgehaald. Al nagekeken: "
          f"{t['adressen_al_nagekeken']} adressen in "
          f"{t['panden_al_nagekeken']} panden.", file=sys.stderr)
    print(f"Weggeschreven naar {args.uit}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
