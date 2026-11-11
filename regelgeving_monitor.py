#!/usr/bin/env python3
"""
Houdt de regels bij die deze portefeuille raken, en meldt wanneer er een
wijzigt.

Twee bronnen, allebei van KOOP en allebei zonder sleutel:

  CVDR, de Centrale Voorziening Decentrale Regelgeving. Hierin staan de
  gemeentelijke verordeningen, waaronder de Huisvestingsverordening Nijmegen.
  Dit is de bron die ertoe doet: de opkoopbescherming, de WOZ-grenzen voor
  kamerverhuur en de weigeringsgronden staan daar, en ze veranderen.

  BWB, het Basiswettenbestand. De landelijke wetten: Huisvestingswet,
  Wet op belastingen van rechtsverkeer, Wet betaalbare huur.

Het script onthoudt per regeling de laatste wijzigingsdatum. Verandert die,
dan is dat een signaal: de regel waarop de brief rekent is aangepast.

Gebruik:
  python regelgeving_monitor.py            # controleer op wijzigingen
  python regelgeving_monitor.py --toon     # laat zien wat er wordt gevolgd
"""

import argparse
import datetime as dt
import json
import os

import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET

import requests

SRU = "https://zoekservice.overheid.nl/sru/Search"
STATUS_PAD = "regelgeving_status.json"
GEMEENTE = "Nijmegen"

# Gemeentelijke verordeningen die deze portefeuille raken. De zoekterm moet
# breed genoeg zijn om een hernoemde verordening te blijven vinden.
GEMEENTELIJK = [
    ("huisvesting", "Huisvestingsverordening: opkoopbescherming, omzetting, "
                    "onttrekking en de WOZ-grenzen voor kamerverhuur"),
    ("erfgoed", "Erfgoedverordening: monumenten en beschermde stadsbeelden"),
    ("parkeer", "Parkeerverordening: parkeereis en vergunningen bij splitsing"),
    # De Beleidsregels Kamerverhuur 2021 vervallen op 16 november 2026, en
    # daarop zijn de kamertoets en de herroeping van Professor
    # Molkenboerstraat 20A gebaseerd. Een opvolger of een quotum moet hier
    # verschijnen zodra hij gepubliceerd is.
    ("kamerverhuur", "Beleidsregels Kamerverhuur: insluiting, "
                     "aaneenschakeling, afval, fietsen en geluid; vervallen per "
                     "16 november 2026"),
    ("leegstand", "Leegstandverordening: Nijmegen heeft er bewust geen, zie "
                  "BEWUST_AFWEZIG; een treffer hier is dus nieuws"),
    ("bouw", "Bouwverordening"),
    # De gemeentelijke lasten en heffingen: die zitten nu als percentage in de
    # exploitatiekosten, terwijl de tarieven jaarlijks worden vastgesteld.
    ("onroerende", "Verordening onroerendezaakbelastingen: het OZB-tarief voor "
                   "woningen en niet-woningen, dat per WOZ-waarde doorwerkt in de "
                   "exploitatiekosten"),
    ("rioolheffing", "Rioolheffing: een vaste last per pand of per gebruiker"),
    ("afvalstoffenheffing", "Afvalstoffenheffing: een vaste last per woning"),
    ("leges", "Legesverordening: wat een omgevingsvergunning of een "
              "omzettingsvergunning kost bij splitsen of verkameren"),
    # Het omgevingsplan regelt wat er op een adres mag. Nijmegen kondigde in
    # september 2025 een wijziging aan over short stay, met besluitvorming
    # voorzien in maart 2026; die zagen we niet, want we volgden het plan niet.
    ("omgevingsplan", "Omgevingsplan: wat op een adres is toegestaan, waaronder "
                      "een logiesfunctie en regels over short stay"),
]

# TERMEN WAARVAN WE WETEN DAT NIJMEGEN GEEN REGELING HEEFT. Een zoekterm
# zonder treffer wordt gemeld, want meestal zoeken we verkeerd. Maar bij
# leegstand zoeken we goed: de Notitie leegstand van december 2023 zegt dat
# Nijmegen de Leegstandwet niet inzet. De leegstand was flink gedaald, en een
# verordening zou ongeveer twee fte per jaar kosten. Wat wel bestaat, is de
# vergunning voor tijdelijke verhuur onder de Leegstandwet, en die staat in
# de landelijke wet en niet in een verordening.
# Een melding die afgaat bij goed gedrag leert de lezer het verslag over te
# slaan. Daarom keert de vlag hier om: geen treffer is wat we verwachten, en
# een treffer betekent dat de gemeente van koers is veranderd.
BEWUST_AFWEZIG = {
    "leegstand": ("Notitie leegstand, december 2023: geen leegstandverordening "
                  "(https://nijmegen.bestuurlijkeinformatie.nl/Document/View/"
                  "bb899590-f561-4cc7-a95b-88e1cc989f28)"),
}

# Landelijke wetten. De nummers zijn de vaste BWB-identificatie.
LANDELIJK = [
    ("BWBR0035303", "Huisvestingswet 2014"),
    ("BWBR0002740", "Wet op belastingen van rechtsverkeer, de overdrachtsbelasting"),
    ("BWBR0002672", "Uitvoeringsbesluit belastingen van rechtsverkeer"),
    # Hierin staat bijlage I met de huurprijstabel: de maximale huur per
    # puntental. Die wordt elk jaar per 1 januari geindexeerd, en daarmee
    # verschuift ook de grens tussen middenhuur en vrije sector. Verandert dit
    # besluit, dan moet de tabel in wwso.py worden bijgewerkt.
    ("BWBR0003237", "Besluit huurprijzen woonruimte, de huurprijstabel"),
    ("BWBR0002481", "Uitvoeringswet huurprijzen woonruimte"),
]

HEADERS = {"Accept": "application/xml",
           "User-Agent": "NijmegenVastgoedMonitor/1.0"}


def titel_klopt(verwacht, gevonden):
    """
    Wijst dit nummer naar de wet die we denken te volgen?

    BWBR0002481 leverde de Uitvoeringswet Nederlands-Duits Executieverdrag op
    terwijl we de Uitvoeringswet huurprijzen woonruimte volgen. Het script nam
    die titel over, en zo stond er een executieverdrag in de brief aan pa. Nu
    moet minstens een kenmerkend woord overeenkomen.
    """
    algemeen = {"wet", "besluit", "regeling", "uitvoeringswet", "de", "het",
                "van", "en", "op", "voor", "woonruimte"}
    woorden = {w.strip(",.").lower() for w in (verwacht or "").split()
               if len(w) > 3} - algemeen
    laag = (gevonden or "").lower()
    if not woorden:
        return True
    return any(w in laag for w in woorden)


def _tekst(element, naam):
    """Haalt de tekst uit het eerste element met deze naam, ongeacht namespace."""
    for el in element.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == naam and el.text:
            return el.text.strip()
    return ""


def bevraag(connection, query, aantal=50):
    """Eén SRU-bevraging, met herhaalpogingen want de dienst is weleens traag."""
    params = {
        "x-connection": connection,
        "version": "2.0",
        "operation": "searchRetrieve",
        "query": query,
        "maximumRecords": aantal,
    }
    url = SRU + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    for poging in range(1, 4):
        try:
            r = requests.get(url, headers=HEADERS, timeout=(15, 60))
            if r.status_code == 503:
                raise RuntimeError("503 Service Unavailable")
            r.raise_for_status()
            return ET.fromstring(r.content)
        except Exception as e:
            if poging == 3:
                print(f"  bevraging mislukt ({connection}): {e}", file=sys.stderr)
                return None
            time.sleep(poging * 10)
    return None


def records(root):
    """De losse records uit een SRU-antwoord."""
    if root is None:
        return []
    uit = []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] == "record":
            uit.append(el)
    return uit


def haal_gemeentelijk():
    """
    De Nijmeegse verordeningen die we volgen.

    EEN ZOEKTERM ZONDER TREFFER LEEST ALS EEN VERORDENING DIE NIET VERANDERT.
    Nagemeten op 14 oktober 2026, op de stand die deze module zelf had
    opgebouwd: 80 gemeentelijke regelingen, en daarvan is er GEEN ENKELE over
    parkeren, erfgoed of leegstand. Alle 80 zijn belastingverordeningen uit
    2012 tot 2014: leges, onroerendezaakbelasting, rioolheffing en
    afvalstoffenheffing. Van de tien zoektermen leverden drie er nooit iets
    op, en dat was aan de uitkomst niet te zien: het gezondheidsrapport kon
    alleen melden dat er niets was veranderd.

    WAT ER WAARSCHIJNLIJK AAN DE HAND IS, en dit is een vermoeden met een
    meting eronder, geen vaststelling. De query is `title any "parkeer"`, en
    `any` matcht hele woorden. "Parkeerverordening" is een woord, dus
    "parkeer" matcht daar niet op. De termen die het wel doen zijn precies de
    termen die als los woord in de titel staan: leges, rioolheffing,
    afvalstoffenheffing, onroerende. En "bouw" gaf exact een treffer, in
    "Verordening Ik Bouw Betaalbaar", waar Bouw een eigen woord is. Dat is
    een sterke aanwijzing. Het commentaar bij GEMEENTELIJK zegt dat de
    zoekterm breed genoeg moet zijn om een hernoemde verordening te blijven
    vinden, en dat was dus een aanname over hoe de dienst zoekt.

    DAAROM MEER DAN EEN VORM PER TERM, en de dienst mag zeggen welke werkt.
    Welke vorm een treffer gaf staat in de stand, zodat de volgende ronde het
    antwoord geeft in plaats van mijn vermoeden.

    En een term die in GEEN enkele vorm iets oplevert, komt als zodanig in de
    uitkomst te staan. Niet gevonden en niet veranderd mogen niet hetzelfde
    woord krijgen.
    """
    gevonden = {}
    zonder_treffer = []
    gebruikte_vorm = {}
    for term, waarom in GEMEENTELIJK:
        # DRIE VORMEN. De eerste is wat er stond; de tweede voegt het woord
        # verordening toe, want zo heten ze; de derde probeert een jokerteken.
        # Werkt er geen, dan staat de term in zonder_treffer.
        vormen = [f'(creator=="{GEMEENTE}") and (title any "{term}")',
                  f'(creator=="{GEMEENTE}") and (title any "{term}verordening")',
                  f'(creator=="{GEMEENTE}") and (title any "{term}*")']
        hier = 0
        for vorm in vormen:
            root = bevraag("cvdr", vorm)
            hier = len(list(records(root)))
            if hier:
                gebruikte_vorm[term] = vorm
                break
            time.sleep(1)
        if not hier:
            zonder_treffer.append(term)
            print(f"  {term}: geen enkele vorm gaf een treffer", file=sys.stderr)
            time.sleep(1)
            continue
        root = bevraag("cvdr", gebruikte_vorm[term])
        for rec in records(root):
            titel = _tekst(rec, "title")
            if not titel or term.lower() not in titel.lower():
                continue
            sleutel = _tekst(rec, "identifier") or titel
            gevonden[sleutel] = {
                "titel": titel,
                "gewijzigd": (_tekst(rec, "modified")
                              or _tekst(rec, "issued")
                              or _tekst(rec, "date")),
                "geldig_vanaf": _tekst(rec, "inwerkingtredingDatum"),
                "geldig_tot": _tekst(rec, "uitwerkingtredingDatum"),
                "waarom": waarom,
                "term": term,
                "bron": "gemeente",
                "url": _tekst(rec, "preferredUrl") or _tekst(rec, "publicatieurl"),
            }
        time.sleep(1)
    # De bevindingen over de zoektermen zelf gaan mee in de uitkomst, onder
    # een sleutel die geen regeling kan zijn.
    gevonden["_zoektermen"] = zoektermen_meta(zonder_treffer, gebruikte_vorm)
    return gevonden


def zoektermen_meta(zonder_treffer, gebruikte_vorm):
    """
    Wat de zoektermen opleverden, gesplitst naar wat we verwachtten.

    zonder_treffer   termen zonder treffer waar we wel een regeling verwachten
    bewust_afwezig   termen zonder treffer die zo horen (zie BEWUST_AFWEZIG)
    onverwacht       termen uit BEWUST_AFWEZIG die toch een treffer gaven
    """
    return {
        "zonder_treffer": [t for t in zonder_treffer if t not in BEWUST_AFWEZIG],
        "bewust_afwezig": [t for t in zonder_treffer if t in BEWUST_AFWEZIG],
        "onverwacht": sorted(t for t in gebruikte_vorm if t in BEWUST_AFWEZIG),
        "vorm_per_term": gebruikte_vorm,
        "bron": "meta",
    }


def haal_landelijk():
    """De landelijke wetten die we volgen."""
    gevonden = {}
    for bwb, naam in LANDELIJK:
        root = bevraag("BWB", f'(dcterms.identifier=="{bwb}")', aantal=5)
        recs = records(root)
        if not recs:
            continue
        rec = recs[0]
        opgehaald = _tekst(rec, "title") or naam
        gevonden[bwb] = {
            "titel": opgehaald,
            "gewijzigd": (_tekst(rec, "modified") or _tekst(rec, "date")),
            "geldig_vanaf": _tekst(rec, "inwerkingtredingDatum"),
            "waarom": naam,
            "bron": "landelijk",
            "sleutel": bwb,
            # Wijst dit nummer naar de wet die we denken te volgen? Zo niet,
            # dan blijft hij uit de brief en staat het als melding in de
            # bijlage, want dan klopt onze eigen lijst niet.
            "titel_wijkt_af": not titel_klopt(naam, opgehaald),
            "url": f"https://wetten.overheid.nl/{bwb}",
        }
        if gevonden[bwb]["titel_wijkt_af"]:
            print(f"  {bwb}: verwacht '{naam}', kreeg '{opgehaald[:60]}'",
                  file=sys.stderr)
        time.sleep(1)
    return gevonden



# Landelijke wetgeving in wording. Een persbericht zegt wat het kabinet wil,
# het Staatsblad zegt wat er is aangenomen. Dat verschil telt: een voorgesteld
# tarief is geen tarief.
RIJKSTERMEN = [
    ("overdrachtsbelasting", "het tarief in de aankoopkosten"),
    ("huurprijzen woonruimte", "het puntenstelsel en de huurgrenzen"),
    ("huurtoeslag", "de grenzen waarbinnen je huurder toeslag krijgt"),
    ("goed verhuurderschap", "verplichtingen voor verhuurders"),
    ("betaalbare huur", "de regulering van de middenhuur"),
    ("box 3", "de belasting op vermogen bij prive-bezit"),
]


def rijkspublicaties(dagen=7):
    """
    Wetgeving en regelingen op rijksniveau die deze portefeuille raken.

    We zoeken in het Staatsblad en de Staatscourant, dus in wat daadwerkelijk
    is gepubliceerd. Kamerstukken laten we buiten beschouwing: daar staat te
    veel in dat nooit wet wordt.
    """
    vanaf = (dt.date.today() - dt.timedelta(days=dagen)).isoformat()
    gevonden = []
    for term, waarom in RIJKSTERMEN:
        # "any" splitst de term op losse woorden, waardoor "box 3" matcht op
        # elke titel met een 3 erin en "huurprijzen woonruimte" op alles met
        # het woord woonruimte. Met "all" moeten alle woorden voorkomen.
        query = (f'c.product-area==officielepublicaties and '
                 f'(dt.type=="Wet" or dt.type=="AMvB" or dt.type=="Regeling" or '
                 f'dt.type=="Besluit") and '
                 f'dt.title all "{term}" and dt.date>="{vanaf}"')
        root = bevraag_sru(query)
        for rec in records(root):
            titel = _tekst(rec, "title")
            if not titel:
                continue
            # Alle woorden van de term moeten in de titel staan. De SRU is
            # soms ruimhartig; zo houden we alleen de echte treffers over.
            woorden_t = [w for w in term.lower().split() if len(w) > 2]
            if woorden_t and not all(w in titel.lower() for w in woorden_t):
                continue
            gevonden.append({
                "titel": titel,
                "datum": _tekst(rec, "date") or _tekst(rec, "available"),
                "soort": _tekst(rec, "type"),
                "waarom": waarom,
                "url": _tekst(rec, "preferredUrl") or _tekst(rec, "publicatieurl"),
            })
        time.sleep(1)
    # Ontdubbelen op titel
    uniek = {}
    for g in gevonden:
        uniek.setdefault(g["titel"], g)
    return list(uniek.values())


def bevraag_sru(query, aantal=25):
    """De SRU van de officiele bekendmakingen, dezelfde als voor de gemeente."""
    params = {"version": "2.0", "operation": "searchRetrieve",
              "query": query, "maximumRecords": aantal}
    url = ("https://repository.overheid.nl/sru?"
           + urllib.parse.urlencode(params, quote_via=urllib.parse.quote))
    for poging in range(1, 4):
        try:
            r = requests.get(url, headers=HEADERS, timeout=(15, 60))
            if r.status_code == 503:
                raise RuntimeError("503")
            r.raise_for_status()
            return ET.fromstring(r.content)
        except Exception as e:
            if poging == 3:
                print(f"  rijkspublicaties mislukt: {e}", file=sys.stderr)
                return None
            time.sleep(poging * 10)
    return None


def render_rijk(items):
    """Alleen tonen als er iets is gepubliceerd."""
    if not items:
        return []
    r = ["", "### Landelijke regelgeving gepubliceerd", ""]
    for it in items:
        r.append(f"- **{it['titel']}**"
                 + (f" ({it['soort']}, {it['datum'][:10]})" if it.get("datum") else "")
                 + (f" [bekijken]({it['url']})" if it.get("url") else ""))
        r.append(f"  _Raakt {it['waarom']}._")
    r.append("")
    r.append("_Dit is wat er daadwerkelijk is gepubliceerd in het Staatsblad of de "
             "Staatscourant, niet wat is voorgesteld. Een voorgesteld tarief is "
             "geen tarief._")
    return r


def lees_status():
    if not os.path.exists(STATUS_PAD):
        return {}
    try:
        with open(STATUS_PAD, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def schrijf_status(status):
    try:
        with open(STATUS_PAD, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, indent=1, sort_keys=True)
    except Exception as e:
        print(f"Kon {STATUS_PAD} niet schrijven: {e}", file=sys.stderr)


def render(wijzigingen, nieuw):
    """Alleen iets tonen als er werkelijk iets is veranderd."""
    if not wijzigingen and not nieuw:
        return []
    r = ["", "## Regelgeving gewijzigd", ""]
    for sleutel, was, wordt in wijzigingen:
        r.append(f"- **{wordt['titel']}** is gewijzigd: laatste wijziging staat nu "
                 f"op {wordt.get('gewijzigd') or 'onbekend'}, was "
                 f"{was.get('gewijzigd') or 'onbekend'}."
                 + (f" [bekijken]({wordt['url']})" if wordt.get("url") else ""))
        r.append(f"  _Waarom dit telt: {wordt['waarom']}._")
    for sleutel, wordt in nieuw:
        if wordt.get("titel_wijkt_af"):
            # Niet in de brief: het nummer wijst naar een andere wet dan we
            # volgen. Dat is een fout in onze lijst en geen nieuws voor de lezer.
            continue
        r.append(f"- **{wordt['titel']}** is nieuw in beeld."
                 + (f" [bekijken]({wordt['url']})" if wordt.get("url") else ""))
        r.append(f"  _Waarom dit telt: {wordt['waarom']}._")
    afwijkend = [w for _s, w in nieuw if w.get("titel_wijkt_af")]
    if afwijkend:
        r.append("")
        r.append("_Niet getoond: " + ", ".join(
            f"{w['titel']} onder nummer {w.get('sleutel', '?')}"
            for w in afwijkend[:3])
            + ". Dat nummer wijst naar een andere wet dan we volgen; "
              "controleer de lijst in regelgeving_monitor.py._")
    r.append("")
    r.append("_De brief rekent met deze regels. Verandert er een, controleer dan "
             "of de grenzen in het script nog kloppen: de WOZ-grenzen voor "
             "kamerverhuur en opkoopbescherming, de weigeringsgronden en de "
             "overdrachtsbelasting._")
    return r


MELDINGEN_PAD = "regelgeving_meldingen.json"


def voeg_melding_toe(pad, tekst, bewaar_dagen=60, vandaag=None):
    """
    Een melding met datum toevoegen aan een meldingenbestand.

    WAAROM. Tot 11 november draaide deze monitor in de brief, en schreef hij
    zijn wijzigingen naar een bestand dat de brief diezelfde run las en daarna
    weggooide. Sinds de verhuizing naar nijmegen-marktdata draait hij in een
    andere repo dan de lezer. Daarom staat elke melding hier met een datum, en
    houdt de lezer zelf bij wat hij al heeft gemeld. Meldingen ouder dan
    bewaar_dagen gaan weg.
    """
    vandaag = vandaag or dt.date.today()
    try:
        with open(pad, encoding="utf-8") as f:
            lijst = json.load(f)
    except Exception:
        lijst = []
    grens = (vandaag - dt.timedelta(days=bewaar_dagen)).isoformat()
    lijst = [m for m in lijst if (m.get("datum") or "") >= grens]
    lijst.append({"datum": vandaag.isoformat(), "tekst": tekst})
    with open(pad, "w", encoding="utf-8") as f:
        json.dump(lijst, f, ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--toon", action="store_true",
                    help="laat zien wat er wordt gevolgd, zonder te vergelijken")
    ap.add_argument("--uit", default="")
    args = ap.parse_args()

    print("Regelgeving ophalen", file=sys.stderr)
    huidig = {}
    huidig.update(haal_gemeentelijk())
    huidig.update(haal_landelijk())

    if not huidig:
        print("Niets gevonden. De opzet van de SRU is mogelijk gewijzigd; "
              "controleer zoekservice.overheid.nl", file=sys.stderr)
        return

    print(f"  {len(huidig)} regelingen gevonden", file=sys.stderr)
    if args.toon:
        for sleutel, g in sorted(huidig.items(), key=lambda x: x[1]["titel"]):
            print(f"  {g['titel'][:70]:72} {g.get('gewijzigd', '')[:10]}",
                  file=sys.stderr)
        return

    vorig = lees_status()
    # Welke zoektermen we al eens hebben opgehaald. Een nieuwe term levert in
    # een klap de hele geschiedenis op: bij het toevoegen van de belasting-
    # verordeningen kwamen alle jaargangen sinds 2011 als "nieuw in beeld"
    # binnen. Die leggen we stil vast als uitgangspunt.
    bekende_termen = set(vorig.get("_termen") or [])
    alle_termen = {g.get("term") for g in huidig.values() if g.get("term")}
    eerste_keer = alle_termen - bekende_termen

    wijzigingen, nieuw, basis = [], [], 0
    for sleutel, g in huidig.items():
        if str(sleutel).startswith("_"):
            continue
        was = vorig.get(sleutel)
        if not was:
            if not vorig:      # bij de eerste run is alles nieuw, dat is geen signaal
                pass
            elif g.get("term") in eerste_keer:
                basis += 1     # nieuwe zoekterm: wel bewaren, niet melden
            else:
                nieuw.append((sleutel, g))
        elif (was.get("gewijzigd") or "") != (g.get("gewijzigd") or ""):
            wijzigingen.append((sleutel, was, g))

    huidig["_termen"] = sorted(bekende_termen | alle_termen)
    schrijf_status(huidig)
    if basis:
        print(f"  {basis} regelingen bij {len(eerste_keer)} nieuwe zoektermen als "
              f"uitgangspunt vastgelegd, niet gemeld", file=sys.stderr)

    rijk = rijkspublicaties()
    if rijk:
        print(f"  {len(rijk)} landelijke publicaties gevonden", file=sys.stderr)

    regels = render(wijzigingen, nieuw) + render_rijk(rijk)
    if regels:
        for r in regels:
            print(r)
        if args.uit:
            with open(args.uit, "w", encoding="utf-8") as f:
                f.write("\n".join(regels) + "\n")
        voeg_melding_toe(MELDINGEN_PAD, "\n".join(regels))
        print(f"\n{len(wijzigingen)} gewijzigd, {len(nieuw)} nieuw", file=sys.stderr)
    else:
        print("Geen wijzigingen in de gevolgde regelgeving", file=sys.stderr)


def proef():
    """Zonder netwerk: een melding komt erbij met datum, en oude gaan weg."""
    import tempfile
    fouten = []
    with tempfile.TemporaryDirectory() as t:
        pad = os.path.join(t, "m.json")
        voeg_melding_toe(pad, "oud", vandaag=dt.date(2026, 8, 1))
        voeg_melding_toe(pad, "nieuw", vandaag=dt.date(2026, 11, 11))
        with open(pad, encoding="utf-8") as f:
            lijst = json.load(f)
        if [m["tekst"] for m in lijst] != ["nieuw"]:
            fouten.append(f"een melding van 102 dagen oud blijft staan: {lijst}")
        voeg_melding_toe(pad, "erbij", vandaag=dt.date(2026, 11, 12))
        with open(pad, encoding="utf-8") as f:
            lijst = json.load(f)
        if [m["datum"] for m in lijst] != ["2026-11-11", "2026-11-12"]:
            fouten.append(f"een tweede melding vervangt de eerste: {lijst}")
    for f in fouten:
        print(f"FOUT {f}", file=sys.stderr)
    print(f"Proef regelgeving_monitor: {len(fouten)} fouten", file=sys.stderr)
    return 1 if fouten else 0


if __name__ == "__main__":
    if "--proef" in sys.argv:
        sys.exit(proef())
    sys.exit(main() or 0)
