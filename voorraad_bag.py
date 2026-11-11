#!/usr/bin/env python3
"""
Haalt de oppervlakte en het energielabel op van de hele woningvoorraad in de
ringbuurten uit ring.py, niet alleen van wat te koop staat.

Drie fasen, elk met een tijdbudget:

  1. De panden uit de BAG via PDOK, om PDOK's eigen pandsleutel om te zetten
     naar de zestiencijferige BAG-pandidentificatie. Zonder die omzetting
     sluit voorraad.json niet aan op pandgeschiedenis.json.
  2. De verblijfsobjecten uit de BAG via PDOK, in een ronde over een raster
     van tegels om Nijmegen, daarna lokaal gezeefd op onze 1.733 postcodes.

     WAAROM PER GEBIED EN NIET PER POSTCODE. Dit heeft op 10 oktober vier
     keer gefaald, elke keer omdat ik een eigenschap van een dienst aannam.
     De BAG-API van het Kadaster weigert een postcode zonder huisnummer. PDOK
     laat alleen geometry en identificatie als filter toe, op alle zes
     collecties, dus een vraag per postcode kan daar niet. Wat wel kan is een
     ronde over een gebied, en dat blijkt goedkoper dan beide: 164.634
     objecten in 248,4 seconden over 22 tegels. De postcode staat wel in het
     antwoord, dus zeven kan lokaal.

     Dat maakt deze fase ook eenvoudiger dan hij was. Geen achterstand, geen
     versheid per postcode, geen bewaarde cursor, geen hervatten. Elke ronde
     leest alles opnieuw.
  3. EP-Online per adres, voor de woningen die nog geen label hebben. Dat gaat
     per adres en niet per postcode, dus 15.000 vragen, ongeveer 4,6 uur. Dat
     past niet in één run. Daarom werkt deze fase een achterstand weg: elke
     run een tijdbudget, de oudste eerst, en de stand blijft staan. Bij 45
     minuten per run zijn 2.455 adressen, dus de ring is in zeven runs
     rond.

WAAROM EEN TIJDBUDGET EN GEEN AANTAL. Ik kan deze code hier niet proeven: de
sleutels zitten in de repo-secrets en deze omgeving mag de BAG en EP-Online
niet benaderen. Een budget in aantallen gokt dus het tempo, en gokt verkeerd
zodra een dienst langzamer is dan gedacht. Een budget in minuten klopt altijd:
het script stopt wanneer de tijd om is, bewaart wat het heeft, en gaat de
volgende run verder. De eerste run vertelt het echte tempo.

WAT ER NIET IN ZIT. Dit script vult alleen voorraad.json. Het verandert niets
aan de brief en niets aan pandgeschiedenis.json. Eerst de gegevens, dan kijken
wat ze waard zijn, dan pas de brief. Andersom levert een mooie regel op basis
van een bestand dat nog nergens over gaat.

LET OP BIJ DE OPPERVLAKTE. Een verblijfsobject kan meer dan één adres hebben,
een hoofdadres met nevenadressen. De oppervlakte is dan die van het hele
object en niet van wat achter één huisnummer zit. Sinds het ophalen per gebied
gaat is dat geen probleem meer voor de telling: er wordt rechtstreeks naar
verblijfsobjecten gevraagd, dus elk object komt één keer voorbij en de
oppervlakte hoort bij precies dat object. Wie de nevenadressen zelf wil zien,
moet de collectie adres bevragen; die staat hier niet in.

Vereist env: EP_API_KEY voor fase 3. Fase 1 en 2 gaan naar PDOK
en vragen geen sleutel.

Gebruik:
  python voorraad_bag.py                          # beide fasen, standaardbudget
  python voorraad_bag.py --bag-minuten 40 --labels-minuten 45
  python voorraad_bag.py --alleen bag             # of: --alleen labels
  python voorraad_bag.py --buurt Bottendaal       # eerst één buurt proeven
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import time

import requests


import eponline as _epo
import pandsleutel as _psl
INVENTARIS = "buurtinventaris.json"
UIT = "voorraad.json"

# De stand van de laatste ronde, los van de gegevens. Dit bestand wordt altijd
# overschreven, ook als er niets is opgehaald, want juist dan moet de reden
# bewaard blijven. voorraad.json wordt alleen overschreven als er werkelijk
# iets in staat; anders zou een mislukte ronde de voorraad van vorige week
# wissen.
STAND = "voorraad_stand.json"

# De BAG via PDOK, als OGC API Features. Open data, geen sleutel.
PDOK = "https://api.pdok.nl/kadaster/bag/ogc/v2/collections"
PDOK_BASE = f"{PDOK}/verblijfsobject/items"

# Gemeten op 10 oktober: 200, 500 en 1.000 komen voluit terug, 2.000 wordt op
# 1.000 afgekapt. Duizend is dus het maximum en niet een voorzichtige keuze.
PDOK_LIMIT = 1000

# HET GEBIED, NIET DE POSTCODE. PDOK laat alleen geometry en identificatie als
# filter toe, op alle zes collecties. Postcode staat wel in het antwoord maar is
# niet filterbaar, dus er is geen vraag per postcode mogelijk. Daarom één ronde
# over een doos en daarna lokaal zeven op onze postcodes.
#
# Deze doos is met opzet te groot: hij is een bovengrens om Nijmegen heen, geen
# schatting van de ring. Dat mag, want hij kost niets. Gemeten op 10 oktober:
# 164.634 objecten, in één doos 165 pagina's in 146,7 seconden en in tegels
# 201 pagina's in 248,4 seconden. In tegels duurt het langer omdat elke tegel
# zijn eigen eerste pagina heeft en een gedeelde tegel opnieuw wordt gelezen,
# en dat is de prijs voor een ronde die het haalt (zie doorloop).
#
# EN HIJ KAPT NIETS AF. De doos om de gevonden treffers was
# 5,83189-5,88500 bij 51,82759-51,85880. De marge tot deze doos is west
# 0,082, oost 0,095, zuid 0,068 en noord 0,041 graad; noord is de kleinste en
# dat is nog altijd ruim vier kilometer. Zou de doos de ring ergens raken, dan
# zouden de Nijmeegse postcodes daar leeg blijven, en dat wordt per ronde
# geteld (zie postcodes_leeg_nijmegen in de stand; in de eerste echte ronde
# waren dat 2 van de 1.242). Een te kleine doos faalt hier dus hardop en niet
# stil.
DOOS = "5.75,51.76,5.98,51.90"

# Statussen waarbij het object niet bestaat. De collectie bevat ook historie:
# het eerste object dat PDOK op 10 oktober teruggaf had status "Verblijfsobject
# ingetrokken". Zonder deze zeef zou de voorraad gesloopte en nooit gebouwde
# woningen meetellen, en elk aantal dat de brief eruit haalt zou te hoog zijn
# zonder dat er iets faalt.
NIET_BESTAAND = ("ingetrokken", "niet gerealiseerd", "ten onrechte opgevoerd")

# DE PIJPLIJN IS GEEN VOORRAAD. Een verblijfsobject met status "gevormd" is
# geregistreerd maar nog niet gereedgemeld: het pand heeft vergunning of de
# bouw is gestart, en pas bij de gereedmelding komt het object in de
# woonvoorraad. Het CBS rekent ze daarom tot de pijplijn en niet tot de
# voorraad.
#
# Wat het ons kostte, gemeten op 11 oktober. Van de 22.096 woningen in de ring
# hadden 2.168 deze status, bijna 11 procent. Daardoor stond onze voorraad
# 15,9 procent boven het CBS-cijfer van 19.061; zonder de pijplijn is dat 4,5
# procent. En het werkte door in twee dingen die de brief werkelijk zegt:
#
#   134 huisnummers leken uit meer dan een woning te bestaan terwijl er
#   hoogstens een in gebruik was. Dat is de telling waar de insluitingstoets
#   voor kamerverhuur op leunt, dus daar hing een advies aan.
#
#   In de plint van Stadscentrum stond het aandeel niet-woonfunctie op 18,0
#   procent in plaats van 21,4, en de beleidsregel laat hoogstens 30 procent
#   toe. Dat is het verschil tussen ruim onder de grens en er dichtbij.
#
# Ze gaan niet weg maar apart. 2.168 woningen die naar de ring komen is voor
# ons geen ruis: het is bijna 11 procent extra voorraad in zes buurten, en per
# straat te zien.
PIJPLIJN = ("gevormd",)

# IN HOEVEEL TEGELS DE DOOS WORDT GEDEELD. Vier bij vier is zestien tegels,
# gemiddeld ruim tienduizend objecten per tegel bij de 164.634 die er in de
# hele doos staan. Dat is ongeveer elf pagina's per tegel, en zo diep
# doorbladeren hield PDOK wel vol. In één doos ging het de tweede keer mis bij
# pagina 123 van 165.
TEGELS = 4

# Een tegel die het alsnog niet haalt wordt in vieren gedeeld. Drie keer delen
# maakt van één tegel maximaal 64 kleintjes, en dan is de vraag zo eenvoudig
# dat de oorzaak ergens anders ligt dan in de omvang.
MAX_DELINGEN = 3

# GEEN BAG-SLEUTEL MEER. De BAG-API van het Kadaster weigert een postcode
# zonder huisnummer, dus die route is vervallen; PDOK vraagt geen sleutel. De
# sleutel stond hier nog en werd nergens gebruikt, en de workflow geeft hem
# nog mee. Dat is niet erg, maar het suggereert een afhankelijkheid die er
# niet is.

EP_API_KEY = os.environ.get("EP_API_KEY", "")
EP_BASE = "https://public.ep-online.nl/api/v5/PandEnergielabel"
EP_HEADERS = {"Authorization": EP_API_KEY, "Accept": "application/json"}

# Hetzelfde tempo als marktprijzen_bag.py aanhoudt. Niet sneller: beide
# diensten zijn gratis en een blokkade kost meer dan de winst.
TEMPO = 1.1

# Tussen twee pagina's bij PDOK. De verkenning deed op 10 oktober 165 pagina's
# achter elkaar zonder pauze en zonder één 429, dus 1,1 seconde is hier niet
# nodig en zou een ronde van twee minuten naar vijf brengen. Een kwart seconde
# houdt het netjes en kost veertig seconden per ronde.
TEMPO_PDOK = 0.25

# GEEN VERSHEID PER POSTCODE MEER. Toen er per postcode werd gevraagd was dat
# nodig om 1.733 vragen over meer runs te verdelen. Een hele ronde kost nu vier
# minuten, dus elke ronde leest alles opnieuw en er is geen achterstand om bij
# te houden. De constante die dat regelde is weg; deze uitleg staat er omdat
# de vraag "waarom wordt een postcode niet overgeslagen" anders terugkomt.

# Een adres waarvan EP-Online geen label kende, na een jaar nog eens vragen.
# Een label wordt geregistreerd bij een verkoop of een verbouwing, dus "niet
# bekend" is een momentopname en geen eigenschap van het pand.
LABEL_OPNIEUW_DAGEN = 365

# VANAF WANNEER DE REKENMETHODE BIJ EEN LABEL WORDT BEWAARD. Labels die
# daarvoor zijn opgehaald hebben geen methode, en een gevonden label komt pas
# aan de beurt als het verloopt. Deze datum haalt die groep een keer in: wie
# voor deze dag is gezien en geen methode heeft, wordt opnieuw gevraagd. Dat
# de grens een DATUM is en niet "zolang de methode ontbreekt", is wat hem
# laat eindigen: een adres waarvan EP-Online geen Berekeningstype geeft,
# krijgt na die ene vraag de datum van vandaag en komt niet terug.
METHODE_VANAF = "2026-10-12"

# VANAF WANNEER "GEEN LABEL" EEN ANTWOORD IS. Tot de merge van PR 41, in de
# nacht van 11 op 12 oktober, las haal_label() een veldnaam die EP-Online niet
# geeft. Elk adres dat toen werd gevraagd kreeg "geen label" en de datum van
# die dag, en kwam daarmee pas na LABEL_OPNIEUW_DAGEN terug. Gemeten op 14
# oktober: 1.097 adressen zonder label met een vraagdatum voor deze grens, en
# daarvan kent de pandgeschiedenis er 57 wel een label (5,2 procent). Voor de
# 5.485 adressen zonder label die na de grens zijn gevraagd is dat 5 (0,09
# procent). Wie voor deze dag "geen label" kreeg, wordt dus een keer opnieuw
# gevraagd. Ook hier is de grens een datum en geen veld, zodat de inhaalslag
# ophoudt: na de vraag staat de datum van vandaag erin.
GEEN_LABEL_BETROUWBAAR_VANAF = "2026-10-12"

# DE GEMEENTECODE VAN NIJMEGEN, de eerste vier cijfers van elk BAG-id dat de
# gemeente heeft uitgegeven. Een adres zonder woonplaats is niet uniek: op 14
# oktober stonden er 29 objecten uit andere gemeenten in de voorraad, alle 29
# binnengekomen als "bekendmaking", omdat hun straat en huisnummer gelijk
# waren aan een Nijmeegs adres met een bekendmaking (Bachstraat 3 drie keer,
# Schoolstraat 15 vier keer). Het id weet in welke gemeente het object ligt;
# het adres weet dat niet.
GEMEENTECODE = "0268"


def _stuk_gevraagd(r):
    """
    Of dit record "geen label" kreeg van de kapotte aanroep van voor
    GEEN_LABEL_BETROUWBAAR_VANAF. Een plek voor de wachtrij en de telling in
    de stand, zodat die twee niet uiteen kunnen lopen. Een privelabel en een
    definitieve weigering waren wel echte antwoorden en tellen niet mee.
    """
    gezien = r.get("label_gezien") or ""
    return (bool(gezien) and gezien < GEEN_LABEL_BETROUWBAAR_VANAF
            and not r.get("label") and not r.get("label_prive")
            and not r.get("label_fout"))


def _lees(pad, standaard):
    try:
        with open(pad, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return standaard


def _schrijf(pad, data):
    try:
        with open(pad, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
        return True
    except Exception as e:
        print(f"Kon {pad} niet schrijven: {e}", file=sys.stderr)
        return False


def adressleutel(straat, nr, letter, toev):
    """
    De adressleutel van een record, uit pandsleutel.sleutel().

    HIER STOND EEN EIGEN FUNCTIE: kleine letters, spaties eruit, verder niets.
    Die liet punten, accenten en titels staan, en week daardoor op 14 oktober
    bij 2.692 van de 24.703 records af van de sleutel die de rest van de repo
    gebruikt: "st.annastraat1d" tegen "stannastraat1d",
    "professorschrijnenstraat11" tegen "profschrijnenstraat11",
    "mariënburgsestraat10" tegen "marienburgsestraat10", "deruyterstraat105"
    tegen "ruyterstraat105". Een join op dit veld miste die adressen stil.
    gezondheid.py ving het af door ook een eigen kale vorm te proberen, en
    aanbodprofiel.py rekende de sleutel uit het adres opnieuw uit. De naam
    blijft staan omdat de proef op de botsing hem gebruikt; het rekenwerk is
    van pandsleutel.
    """
    return _psl.sleutel(straat, f"{nr}{letter or ''}{toev or ''}")


def postcodes_uit_inventaris(buurten=None):
    """
    De zeef: {postcode: buurt} uit buurtinventaris.json.

    Een dict en geen lijst, want er wordt niet meer per postcode gevraagd maar
    per gebied, en daarna wordt elk object in de doos hierin opgezocht.

    ALLE BUURTEN PER POSTCODE, NIET ÉÉN. Achtentwintig postcodes staan in twee
    buurten. Werd daar de eerste op alfabet gekozen, dan verloor Stadscentrum
    er elke keer een, want die staat alfabetisch laatste van de zes. En
    Stadscentrum is precies de buurt waarover de plintregel in de brief
    rekent, dus dat was een vaste afwijking in één richting: 24 van de 471
    postcodes van Stadscentrum vielen uit de telling, zonder dat er iets
    faalde en zonder dat de dekking erop reageerde. Welke van de twee buurten
    het werkelijk is, is uit een postcode niet te zeggen. Dan is beide
    bewaren eerlijker dan één kiezen.
    """
    d = _lees(INVENTARIS, {})
    per_buurt = d.get("postcodes_per_buurt") or {}
    if not per_buurt:
        print(f"Geen postcodes in {INVENTARIS}; draai eerst "
              f"buurtinventaris.py", file=sys.stderr)
        return {}
    uit = {}
    for buurt, lijst in sorted(per_buurt.items()):
        if buurten and buurt not in buurten:
            continue
        for pc in lijst:
            sleutel = (pc or "").replace(" ", "").upper()
            if sleutel:
                uit.setdefault(sleutel, []).append(buurt)
    dubbel = sum(1 for b in uit.values() if len(b) > 1)
    buiten = sum(1 for pc in uit if not pc.startswith("65"))
    if dubbel:
        print(f"{dubbel} postcodes staan in meer dan één buurt; alle buurten "
              f"worden bewaard", file=sys.stderr)
    if buiten:
        # DIT IS EEN FOUT IN DE INVENTARIS EN NIET HIER. Gemeten op 10
        # oktober: 491 van de 1.733 postcodes liggen niet in Nijmegen, maar in
        # Boskoop, Gorinchem, Dongen, Assen en vier andere plaatsen. Ze kunnen
        # hier geen schade doen, want de doos ligt om Nijmegen en ze matchen
        # dus nooit een object. Maar ze verdoezelden wel het signaal dat de
        # doos moet bewaken, en daarom staan ze apart gemeld.
        print(f"{buiten} van de {len(uit)} postcodes in {INVENTARIS} liggen "
              f"niet in Nijmegen (beginnen niet met 65); dat is een fout in de "
              f"inventaris", file=sys.stderr)
    return {pc: tuple(b) for pc, b in uit.items()}


def anders_aantal(voorraad):
    """Hoeveel niet-woningen er in de voorraad staan."""
    return len(voorraad.get("niet_woningen") or {})


def _is_woning(doelen):
    return any("woonfunctie" == d for d in (doelen or []))


def _queryables():
    """
    Welke velden PDOK wel als filter toestaat.

    Alleen bedoeld voor de foutmelding. De dienst zegt bij een geweigerd filter
    welk veld niet mag, maar niet welke wel mogen, en die lijst staat op een
    eigen pagina. In een try, want een mislukking hier mag de eigenlijke
    foutmelding niet opeten.
    """
    try:
        r = requests.get(PDOK_BASE.replace("/items", "/queryables"),
                         params={"f": "json"}, timeout=(10, 30))
        if r.status_code != 200:
            return f"queryables gaf HTTP {r.status_code}"
        eigenschappen = (r.json() or {}).get("properties") or {}
        return ", ".join(sorted(eigenschappen)) or "geen velden gemeld"
    except Exception as e:
        return f"queryables niet op te halen ({type(e).__name__})"


def _bestaat(status):
    """Of de status van een object zegt dat het er werkelijk staat."""
    s = (status or "").lower()
    return not any(w in s for w in NIET_BESTAAND)


def _in_pijplijn(status):
    """Of dit object geregistreerd is maar nog niet in gebruik gemeld."""
    s = (status or "").lower()
    return any(w in s for w in PIJPLIJN)


def _pand_uuids(p):
    """De panden van een verblijfsobject, uit het veld pand.href.

    PDOK zet het pand niet als identificatie in het antwoord maar als lijst
    met URL's naar zijn eigen kenmerk: pand.href is
    ["https://.../collections/pand/items/4c396a25-0e16-586f-a298-..."]. Het
    laatste stuk van die URL is PDOK's eigen sleutel voor dat pand, niet de
    zestiencijferige BAG-pandidentificatie. Die wordt in fase_panden()
    opgezocht; lukt dat niet, dan blijft het veld pand leeg in plaats van dat
    er een getal in staat dat op een pandidentificatie lijkt maar het niet is.
    """
    hrefs = p.get("pand.href") or p.get("pand") or []
    if isinstance(hrefs, str):
        hrefs = [hrefs]
    uit = []
    for h in hrefs:
        deel = str(h).rstrip("/").rsplit("/", 1)[-1]
        if deel:
            uit.append(deel)
    return uit


def _normaliseer(p):
    """
    Een PDOK-verblijfsobject in de vorm die de rest van deze module verwacht.

    WAAROM DIT ER IS. Fase 1 haalde eerst bij de BAG-API van het Kadaster alle
    adressen in een postcode op. Dat kan niet: die dienst antwoordt met
    "Minimale combinatie van parameters moet worden opgegeven", want op
    adressenuitgebreid moet er minstens een huisnummer bij de postcode. Per
    adres zou 34.946 aanroepen zijn, bijna elf uur.

    PDOK biedt dezelfde registratie als OGC API Features, en daar staat het
    verblijfsobject met oppervlakte, gebruiksdoel, postcode, straat en pand in
    één collectie. Open data, geen sleutel nodig.

    De veldnamen verschillen alleen. Die omzetting staat hier en niet in
    fase_bag(), zodat de rest van de module niet weet uit welke dienst de
    gegevens komen en een volgende wisseling één functie kost.

    Let op het enkelvoud: PDOK geeft gebruiksdoel als één tekst, de BAG-API gaf
    gebruiksdoelen als lijst. _is_woning() verwacht een lijst, dus dat wordt
    hier een lijst. Was dat niet gebeurd, dan had geen enkel adres een
    woonfunctie gehad en was de voorraad leeg gebleven zonder dat er iets
    faalde, precies zoals vandaag al twee keer is gebeurd.
    """
    doel = p.get("gebruiksdoel")
    doelen = ([d.strip() for d in doel.split(",") if d.strip()]
              if isinstance(doel, str) else list(doel or []))
    return {
        "openbareRuimteNaam": p.get("openbare_ruimte_naam") or "",
        "huisnummer": p.get("huisnummer") or "",
        "huisletter": p.get("huisletter") or "",
        "huisnummertoevoeging": p.get("toevoeging") or "",
        "gebruiksdoelen": doelen,
        "oppervlakte": p.get("oppervlakte"),
        "pandIdentificaties": _pand_uuids(p),
        "adresseerbaarObjectIdentificatie": p.get("identificatie") or "",
        "adresseerbaarObjectStatus": p.get("status") or "",
        "postcode": (p.get("postcode") or "").replace(" ", "").upper(),
    }


SIGNAALBRON = "pandgeschiedenis.json"


def signaaladressen(pad=SIGNAALBRON):
    """
    De adressen waarover een bekendmaking is gepubliceerd.

    WAAROM DIT ER IS. Op 14 oktober stond Mark voor Berg en Dalseweg 11, een
    kernsignaal uit de brief van die ochtend: een aanvraag om splitsingen van
    2 naar 4 woningen te legaliseren. Hij vroeg of de vergunning ook over
    nummer 13 gaat. Wij konden niets zeggen: geen oppervlakte, geen bouwjaar,
    geen gebruiksdoel, geen idee hoeveel eenheden erin zitten. Dat pand ligt
    in Hunnerberg, en de voorraad dekt zes ringbuurten.

    NAGEMETEN OVER ALLE SIGNALEN. 327 panden in pandgeschiedenis.json hebben
    een bekendmaking. 150 daarvan staan in de voorraad, 177 niet. Van die 177
    is er bij 131 nooit gekeken, en alle 131 hebben een huisnummer, dus ze
    zijn op te halen. Over meer dan de helft van onze eigen signalen kunnen we
    dus niets zeggen.

    EN HET KOST GEEN ENKELE EXTRA VRAAG. Fase 2 haalt elke ronde alle
    verblijfsobjecten van Nijmegen op, 164.634 stuks, en zeeft die daarna op
    onze postcodes. De gegevens van nummer 11 zijn dus al binnen en worden
    weggegooid. Dit maakt de zeef één regel ruimer.
    """
    # SINDS DE SPLITSING NIET MEER HIER. Op 11 november verhuisde deze module
    # naar de openbare repo nijmegen-marktdata; pandgeschiedenis.json bleef in
    # de privé brief. Tot de bekendmakingen hier ook worden opgehaald, ontbreekt
    # het bestand en haalt de ronde alleen de ring op. Dat zeggen we hardop:
    # "niet gekeken" mag niet lijken op "geen signalen".
    if not os.path.exists(pad):
        print(f"LET OP: {pad} ontbreekt, dus adressen met een bekendmaking "
              f"buiten de ring worden deze ronde niet opgehaald",
              file=sys.stderr)
        return set()
    try:
        with open(pad, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return set()
    uit = set()
    for sleutel, pand in (d or {}).items():
        if not isinstance(pand, dict):
            continue
        if not any((e or {}).get("soort") == "bekendmaking"
                   for e in (pand.get("gebeurtenissen") or [])):
            continue
        uit.add(str(sleutel))
        adres = pand.get("adres") or ""
        kaal = "".join(c for c in adres.lower() if c.isalnum())
        if kaal:
            uit.add(kaal)
    return uit


def punt_uit(kenmerk):
    """
    Het punt van een verblijfsobject, als lengte- en breedtegraad.

    WAAROM DIT ER IS. De parkeernorm verschilt per zone: 0,70 per woning in de
    binnenstad, 0,8 bij Hatertseweg 338, 1,25 in de schil, en in gereguleerd
    gebied kan de eis helemaal wegvallen. Zonder te weten in welke zone een
    pand ligt, is elke parkeerberekening in de brief een gok. De gemeente
    publiceert die zones als open data, maar een zone bepalen vraagt een punt,
    en in voorraad.json stonden 20.045 records zonder een enkele coordinaat.

    EN HET KOST GEEN ENKELE EXTRA VRAAG. PDOK stuurt bij elk verblijfsobject
    de geometrie mee in hetzelfde antwoord; die werd weggegooid. Precies
    hetzelfde als bij de postcodezeef eerder vandaag.

    DE TOETS OP "point" IS EEN VANGNET EN GEEN WERKENDE REGEL. Hem weghalen
    verandert niets dat te meten is: bij een vlak of een lijn is co[0] zelf
    een lijst, en float() daarvan mislukt al. Hij staat er omdat de bedoeling
    dan in de code staat en niet alleen in een uitzondering.

    WAT ALS DE GEOMETRIE ER NIET IS. Dan geeft deze functie None terug en
    telt de ronde dat. Niet gokken en niet terugvallen op het midden van de
    postcode: een punt dat net in de verkeerde zone ligt, levert een
    parkeernorm op die klopt zolang niemand hem nameet.
    """
    g = (kenmerk or {}).get("geometry") or {}
    co = g.get("coordinates")
    soort = (g.get("type") or "").lower()
    if soort == "point" and isinstance(co, (list, tuple)) and len(co) >= 2:
        try:
            lon, lat = float(co[0]), float(co[1])
        except (TypeError, ValueError):
            return None
    else:
        return None
    # PDOK's OGC API Features levert standaard CRS84, dus lengtegraad eerst.
    # Nijmegen ligt rond 5,8 oost en 51,8 noord. Staat het omgekeerd, dan valt
    # dat hier op in plaats van in een zone die er net naast zit.
    if not (3.0 <= lon <= 8.0 and 50.0 <= lat <= 54.0):
        return None
    return [round(lon, 6), round(lat, 6)]


def waarom_houden(a, pc, pcs, signalen=(), ident=""):
    """
    Bewaren we dit verblijfsobject, en waarom.

    Geeft (buurten, herkomst) terug. Is herkomst leeg, dan valt het object
    buiten alles wat wij volgen.

    Twee redenen om iets te bewaren, en ze blijven apart:
      focusbuurt    het ligt in een postcode van de ringbuurten (ring.py)
      bekendmaking  er is een bekendmaking over dit adres gepubliceerd

    DIE HERKOMST STAAT IN HET RECORD, en dat is geen administratie. Alles wat
    per buurt rekent, moet alleen de focusbuurten tellen: een pand dat hier
    staat omdat er een vergunning over werd gepubliceerd, hoort niet in een
    buurtgemiddelde. Zonder dat veld is dat onderscheid na het opslaan niet
    meer te maken.
    """
    buurten = pcs.get(pc)
    if buurten:
        return list(buurten), "focusbuurt"
    if not signalen:
        return None, ""
    # EEN SIGNAAL GAAT OVER NIJMEGEN. De bekendmaking komt van de gemeente
    # Nijmegen, dus een object met hetzelfde adres in een andere gemeente is
    # een naamgenoot en geen signaal. Zie GEMEENTECODE.
    if ident and not str(ident).startswith(GEMEENTECODE):
        return None, ""
    straat = str(a.get("openbareRuimteNaam") or "")
    nr = str(a.get("huisnummer") or "")
    letter = str(a.get("huisletter") or "")
    if not straat or not nr:
        return None, ""
    # Twee vormen proberen: met en zonder huisletter. De bekendmaking noemt
    # "Berg en Dalseweg 11-11A", waaruit ons pand de sleutel bergendalseweg11
    # kreeg; het verblijfsobject 11A moet daar ook aan hangen.
    for kandidaat in (straat + nr + letter, straat + nr):
        kaal = "".join(c for c in kandidaat.lower() if c.isalnum())
        if kaal in signalen:
            return [], "bekendmaking"
    return None, ""


def _deel(doos):
    """Een doos in vier gelijke dozen."""
    x1, y1, x2, y2 = [float(v) for v in doos.split(",")]
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    return [f"{a:.6f},{b:.6f},{c:.6f},{d:.6f}" for a, b, c, d in
            ((x1, y1, mx, my), (mx, y1, x2, my),
             (x1, my, mx, y2), (mx, my, x2, y2))]


def _raster(doos, n):
    """Een doos in n bij n gelijke dozen, van links naar rechts."""
    x1, y1, x2, y2 = [float(v) for v in doos.split(",")]
    bx, by = (x2 - x1) / n, (y2 - y1) / n
    uit = []
    for i in range(n):
        for j in range(n):
            uit.append(f"{x1 + i * bx:.6f},{y1 + j * by:.6f},"
                       f"{x1 + (i + 1) * bx:.6f},{y1 + (j + 1) * by:.6f}")
    return uit


def _tegel(collectie, doos, per_pagina, stoppen):
    """
    Eén tegel doorbladeren. Geeft (gelukt, paginas, objecten, reden) terug.

    stoppen() zegt of het tijdbudget om is. Werpt niets op: een mislukking
    moet haar reden meenemen, want die bepaalt of de tegel wordt gedeeld.
    """
    url = f"{PDOK}/{collectie}/items"
    params = {"f": "json", "limit": PDOK_LIMIT, "bbox": doos}
    paginas = objecten = 0
    while True:
        if stoppen():
            return False, paginas, objecten, "tijdbudget om"
        body, reden = _pagina(url, params)
        if reden and "netwerk" in reden:
            # Eén herkansing bij een netwerkhapering. Bij een antwoord van de
            # dienst zelf heeft herhalen geen zin; dan is delen het antwoord.
            time.sleep(2)
            body, reden = _pagina(url, params)
        if reden:
            return False, paginas, objecten, reden
        kenmerken = body.get("features")
        if kenmerken is None:
            return (False, paginas, objecten,
                    "geen features in het antwoord; velden: "
                    + ", ".join(sorted(body)[:8]))
        paginas += 1
        objecten += len(kenmerken)
        try:
            per_pagina(kenmerken)
        except Exception as e:
            return False, paginas, objecten, f"verwerken mislukte: {e}"
        volgende = next((l.get("href") or "" for l in (body.get("links") or [])
                         if l.get("rel") == "next"), "")
        if not volgende:
            return True, paginas, objecten, ""
        url, params = volgende, None
        time.sleep(TEMPO_PDOK)


def doorloop(collectie, budget, per_pagina, voortgang=None):
    """
    Alle kenmerken van een PDOK-collectie in DOOS, tegel voor tegel.

    per_pagina(kenmerken) krijgt elke pagina zodra hij binnen is, zodat een
    ronde die halverwege afbreekt niet alles verliest wat er al was.

    WAAROM IN TEGELS EN NIET IN ÉÉN DOOS. Eerst ging dit in één doos. Dat
    lukte de eerste keer (165 pagina's, 164.634 objecten, 146,7 seconden) en
    de tweede keer niet: PDOK antwoordde op pagina 123 met HTTP 500, "querying
    the features took too long (timeout encountered). Simplify your request
    and try again". Diep doorbladeren in een verzameling van ruim 160.000
    objecten zit dus aan de rand van wat de dienst volhoudt, en of het lukt is
    wisselvallig. Dat is het ergste soort grens: hij valt soms weg en laat dan
    een voorraad achter die voor driekwart klopt.

    "Simplify your request" is letterlijk het antwoord. Een kleinere doos is
    een eenvoudiger vraag, dus de ronde gaat per tegel. En een tegel die het
    alsnog niet haalt wordt in vieren gedeeld en opnieuw geprobeerd, tot
    MAX_DELINGEN diep. Dat stelt zich zelf in op de werkelijke dichtheid: de
    binnenstad is druk en de uiterwaarden zijn leeg, en dat hoef ik dan niet
    te weten.

    HERVATTEN PER TEGEL, SINDS 9 NOVEMBER 2026. Hier stond dat een ronde
    twee tot drie minuten kost en dat hervatten dus niet nodig was. Dat was
    gemeten en het klopte tot en met 2 november: 195 pagina's panden in 270
    tot 540 seconden, 171 pagina's objecten in 197 tot 395. Op 3 november
    werd PDOK in beide collecties tegelijk trager, van 1,2 tot 2,8 naar 3,5
    tot 22,5 seconden per pagina, en daarna kwam geen enkele ronde meer rond
    in tien minuten: 8 runs op rij. Een ronde die nooit afkomt verwijdert nooit iets en laat
    de helft van de pandsleutels open.

    Daarom nu met voortgang: de rij met tegels die nog wachten wordt in het
    meegegeven dict bewaard, en de volgende run gaat daarmee verder. Een
    tegel die halverwege op het budget stuit, gaat terug in de rij en wordt
    de volgende keer opnieuw gelopen; de objecten die hij al gaf, schaden
    niet (zie de opmerking bij het delen). Het bezwaar van een cursor die
    verloopt geldt hier niet: een tegel is een vaste doos en geen
    paginaverwijzing van PDOK. ronde_af betekent met voortgang: de hele
    cyclus is rond, over hoeveel runs ook. Zonder voortgang (None) gedraagt
    dit zich als voorheen: elke aanroep begint opnieuw.

    Geeft een dict met de stand terug; de fout staat erin en wordt niet
    opgeworpen, want een mislukte ronde moet zijn reden bewaren.
    """
    start = time.time()

    def stoppen():
        return time.time() - start > budget

    hervat = bool(voortgang and voortgang.get("wacht"))
    if hervat:
        wacht = [(d, int(n)) for d, n in voortgang["wacht"]]
        tegels_totaal = int(voortgang.get("tegels_totaal") or len(wacht))
        klaar_tegels = int(voortgang.get("tegels_klaar") or 0)
        gedeeld = int(voortgang.get("tegels_gedeeld") or 0)
    else:
        wacht = [(t, 0) for t in _raster(DOOS, TEGELS)]
        tegels_totaal = len(wacht)
        klaar_tegels = gedeeld = 0
    paginas = objecten = 0
    klaar_bij_start = klaar_tegels
    fout = ""
    while wacht:
        if stoppen():
            fout = (f"tijdbudget van {budget:.0f}s om na {klaar_tegels} van de "
                    f"{tegels_totaal} tegels; de ronde is niet af")
            break
        doos, diepte = wacht.pop()
        gelukt, p, o, reden = _tegel(collectie, doos, per_pagina, stoppen)
        paginas += p
        objecten += o
        if gelukt:
            klaar_tegels += 1
            continue
        if "tijdbudget" in reden:
            fout = (f"tijdbudget van {budget:.0f}s om in tegel {doos} na "
                    f"{klaar_tegels} van de {tegels_totaal} tegels")
            # TERUG IN DE RIJ, EN GEDEELD ALS HIJ AL PAGINA'S GAF. Ging hij
            # heel terug, dan begon een tegel die langer duurt dan het hele
            # budget elke run opnieuw en kwam de cyclus nooit rond, zonder dat
            # er iets faalde. Gedeeld is elk kind kleiner, dus er komt altijd
            # voortgang. Gaf hij nog niets, dan stuitte het budget er al op
            # voor de eerste pagina, en dan zegt dat niets over de tegel.
            if p and diepte < MAX_DELINGEN:
                gedeeld += 1
                tegels_totaal += 3
                wacht.extend((d, diepte + 1) for d in _deel(doos))
            else:
                wacht.append((doos, diepte))
            break
        if diepte >= MAX_DELINGEN:
            fout = (f"tegel {doos} bleef mislukken na {diepte} delingen: "
                    f"{reden}")
            break
        # DELEN EN OPNIEUW. De objecten die deze tegel al heeft afgeleverd
        # komen in de kleinere tegels nog een keer voorbij. Dat is geen
        # probleem: fase_bag slaat een object over dat hij deze ronde al zag,
        # dus de tellingen blijven kloppen en het schrijven is onschadelijk.
        gedeeld += 1
        # Vier kinderen erbij, de ouder eraf: netto drie.
        tegels_totaal += 3
        wacht.extend((d, diepte + 1) for d in _deel(doos))
    af = not wacht and not fout
    if voortgang is not None:
        # Een tegel die blijft mislukken na MAX_DELINGEN is geen budgetkwestie;
        # die rij wordt niet bewaard, anders loopt elke run op dezelfde tegel
        # vast. De volgende run begint dan een nieuwe cyclus.
        bewaren = wacht if (wacht and "bleef mislukken" not in fout) else []
        runs = int(voortgang.get("runs") or 0) + 1 if hervat else 1
        begonnen = (voortgang.get("begonnen") if hervat else None) \
            or dt.date.today().isoformat()
        voortgang.clear()
        if bewaren:
            voortgang.update({"wacht": [[d, n] for d, n in bewaren],
                              "tegels_totaal": tegels_totaal,
                              "tegels_klaar": klaar_tegels,
                              "tegels_gedeeld": gedeeld,
                              "runs": runs, "begonnen": begonnen})
        cyclus = {"cyclus_runs": runs, "cyclus_begonnen": begonnen,
                  "hervat": hervat}
    else:
        cyclus = {}
    return dict({"paginas": paginas, "objecten": objecten,
                 "tegels": klaar_tegels, "tegels_gedeeld": gedeeld,
                 "tegels_over": len(wacht),
                 # Wat deze run zelf afmaakte. Met voortgang is tegels de
                 # stand van de cyclus; dit is de voortgang van vandaag, en
                 # nul betekent dat de cyclus stilstaat.
                 "tegels_deze_run": klaar_tegels - klaar_bij_start,
                 "seconden": round(time.time() - start, 1),
                 "ronde_af": af, "fout": fout}, **cyclus)


def _pagina(url, params):
    """Eén pagina ophalen. Geeft (body, fout) terug, werpt niets op."""
    try:
        r = requests.get(url, params=params or {}, timeout=(15, 90))
    except Exception as e:
        return {}, f"netwerk: {type(e).__name__}: {e}"
    if r.status_code == 429:
        return {}, "429 te veel vragen"
    if r.status_code != 200:
        # HET ANTWOORD ERBIJ, want de dienst zet er zelf in wat er mis is. Bij
        # de BAG-API kwam er tien keer "HTTP 400" uit en dat vertelde alleen
        # dat de vraag werd geweigerd, niet waarom.
        reden = ""
        try:
            body = r.json()
            reden = " ".join(str(body.get(k, "")) for k in
                             ("title", "detail", "code", "description")).strip()
            for inval in (body.get("invalidParams") or []):
                reden += (f" | {inval.get('name', '?')}: "
                          f"{inval.get('reason', '?')}")
        except Exception:
            reden = r.text[:200]
        # GAAT HET OVER HET FILTER, VRAAG DAN WELKE VELDEN WEL MOGEN. PDOK
        # antwoordde op 10 oktober: "property 'postcode' cannot be used in CQL
        # filter, is not a queryable property". Dat zegt wat er niet mag en
        # niet wat er wel mag, en die lijst staat op een eigen pagina van
        # dezelfde dienst.
        if "queryable" in reden.lower() or "cql" in reden.lower():
            reden += " | WEL FILTERBAAR: " + _queryables()
        return {}, f"HTTP {r.status_code}: {reden[:600]}"
    try:
        return r.json(), ""
    except Exception as e:
        return {}, f"antwoord onleesbaar: {e}"


# De velden die uit de pandfase komen. Ze gaan samen mee of samen niet:
# een pand uit het oude record met een status uit de nieuwe ronde zou twee
# rondes door elkaar halen.
PANDVELDEN = ("pand", "panden", "pand_status", "pand_statussen",
              "pand_bouwjaar", "pand_bouwjaren")


def pandvelden(alle_panden, pandstatus, pandbouwjaar):
    """
    De velden naast pand die uit de pandfase komen, voor een lijst van
    BAG-pandidentificaties. Pand zelf zet de aanroeper; hier staan panden,
    pand_status(sen) en pand_bouwjaar/-jaren, alleen als ze er zijn.

    EEN IMPLEMENTATIE. Dit stond eerst alleen in fase_bag. Sinds de rondes
    over meer runs hervatten, rekent ook vul_open_panden() deze velden uit
    voor een object waarvan de pandfase het pand pas een run later vond. Twee
    kopieen zouden uiteenlopen.

    DE STATUS VAN HET PAND, ALS DE PANDFASE HEM MEEGAF. Dit is het verschil
    tussen nieuwbouw en transformatie: een object met status "gevormd" in een
    pand dat vergunning heeft of in bouw is, is nieuwbouw en pijplijn;
    hetzelfde object in een pand dat al in gebruik is, is een transformatie en
    rekent het CBS niet tot de pijplijn. Zonder dit veld is dat onderscheid
    niet te maken, en op 11 oktober was het dat dus niet. Bij een object in
    twee panden staan er twee statussen, en dan is "de" pandstatus geen enkel
    getal. Dat verschil hoort zichtbaar te zijn in het record en niet
    weggewerkt: welk van de twee de doorslag geeft is een keuze die later
    wordt gemaakt, met de gegevens erbij.

    HET BOUWJAAR VAN HET PAND. Bij een object in twee panden wordt het oudste
    genomen en niet het eerste: het gaat erom of dit object in bestaande
    voorraad zit, en dan is het oudste pand het antwoord. Dat is een keuze,
    dus hij staat hier opgeschreven.

    Panden staat er alleen als er werkelijk meer dan een is: anders staat er
    bij 22.000 records een lijst van een, en dat is een megabyte aan niets.
    """
    uit = {}
    if len(alle_panden) > 1:
        uit["panden"] = list(alle_panden)
    statussen_pand = [(pandstatus or {}).get(x) or "" for x in alle_panden]
    if any(statussen_pand):
        uit["pand_status"] = statussen_pand[0]
        if len(set(x for x in statussen_pand if x)) > 1:
            uit["pand_statussen"] = statussen_pand
    jaren = [(pandbouwjaar or {}).get(x) for x in alle_panden]
    jaren = [j for j in jaren if j]
    if jaren:
        uit["pand_bouwjaar"] = min(jaren)
        if len(set(jaren)) > 1:
            uit["pand_bouwjaren"] = sorted(set(jaren))
    return uit


def vul_open_panden(voorraad, open_panden, panden, pandstatus,
                    pandbouwjaar):
    """
    Geeft objecten op de open lijst hun pand, met de omzetting van deze run.

    open_panden is {vbo: [pandsleutels]}: objecten zonder pand waarvan de
    pandfase de sleutel nog niet had gezien. Een object gaat eraf als al zijn
    sleutels in de omzetting staan, of als het niet meer in de voorraad
    staat. Een sleutel die de pandfase kende maar zonder BAG-identificatie,
    geldt als gezien: dan is "geen pand" het antwoord en niet "nog niet
    gekeken".

    ALLE SLEUTELS IN DEZELFDE RUN. Een object in twee panden waarvan de
    panden in twee tegels liggen, wacht dus tot een run beide heeft. Een half
    opgelost object met het eerste pand als pand zou er net zo uitzien als
    een object in een pand.

    Geeft het aantal opgeloste objecten terug.
    """
    opgelost = 0
    secties = [voorraad.get(x) or {} for x in ("adressen", "pijplijn",
                                                "niet_woningen")]
    for vbo in list(open_panden):
        rec = next((sec[vbo] for sec in secties if vbo in sec), None)
        if rec is None:
            del open_panden[vbo]
            continue
        sleutels = open_panden[vbo] or []
        if any(s not in panden for s in sleutels):
            continue
        alle = []
        for s_ in sleutels:
            b = panden.get(s_) or ""
            if b and b not in alle:
                alle.append(b)
        for veld in PANDVELDEN:
            rec.pop(veld, None)
        rec["pand"] = alle[0] if alle else ""
        rec.update(pandvelden(alle, pandstatus, pandbouwjaar))
        del open_panden[vbo]
        opgelost += 1
    return opgelost


def fase_panden(budget, voortgang=None):
    """
    De omzetting van PDOK's pandsleutel naar de BAG-pandidentificatie.

    WAAROM DIT NODIG IS. Een verblijfsobject verwijst naar zijn pand met een
    URL naar PDOK's eigen kenmerk, niet met de zestiencijferige
    BAG-pandidentificatie. Zonder deze omzetting staat er in voorraad.json een
    sleutel die nergens op aansluit: pandgeschiedenis.json en marktprijzen_bag
    werken met de BAG-identificatie, en een join daarop zou nul treffers geven
    zonder dat er iets faalt. Precies de fout die dit project steeds inhaalt.

    De pandcollectie heeft dezelfde doos en hetzelfde tempo, dus dit kost een
    tweede ronde van ongeveer twee minuten.

    AANNAME DIE HIER WORDT GETOETST EN NIET GELOOFD. Bij het verblijfsobject is
    de kenmerksleutel "id" een uuid en staat de BAG-identificatie in
    properties. Of dat bij panden ook zo is, is niet gemeten. Komt de omzetting
    leeg terug, dan meldt de stand dat en blijft het veld pand leeg; de rest
    van de ronde gaat gewoon door.
    """
    kaart, status_per_pand, bouwjaar_per_pand, velden = {}, {}, {}, set()

    def per_pagina(kenmerken):
        for k in kenmerken:
            sleutel = k.get("id") or ""
            p = k.get("properties") or {}
            # WELKE VELDEN PDOK HIER WERKELIJK GEEFT. Deze fase las alleen
            # identificatie en gooide de rest weg, net als de objectfase op 10
            # oktober met gebruiksdoelen. Toen bleek het veld er wel te zijn.
            # Dus eerst opschrijven wat er binnenkomt, en dan pas iets
            # beweren: zonder meting is "de pandstatus hebben we niet" ook een
            # aanname.
            velden.update(p.keys())
            bag = (p.get("identificatie") or "")
            if sleutel and bag:
                kaart[str(sleutel)] = str(bag)
                # DE PANDSTATUS, ALS HIJ ERIN ZIT. Die is het verschil tussen
                # nieuwbouw en transformatie. Het CBS rekent een object met
                # status "gevormd" tot de pijplijn als het PAND vergunning
                # heeft of in bouw is; zit datzelfde object in een pand dat al
                # in gebruik is, dan is het een transformatie en valt het
                # buiten de pijplijn. Dat onderscheid konden we op 11 oktober
                # niet maken, en met dit veld wel.
                st = p.get("status") or ""
                if st:
                    status_per_pand[str(bag)] = str(st)
                # EN HET BOUWJAAR, OM DEZELFDE REDEN. Dit veld stond op 11
                # oktober al in velden_in_antwoord en werd toch weggegooid.
                # Het beslist de groep die de pandstatus alleen niet kan
                # splitsen: 697 van de 2.168 pijplijnwoningen zitten in een
                # pand dat al in gebruik is, en dat is of een splitsing van
                # bestaande voorraad of nieuwbouw die net is opgeleverd
                # terwijl de objecten nog niet in gebruik zijn gemeld. Een
                # pand van 1920 zegt het eerste, een pand van 2025 het
                # tweede. Zonder dit veld is dat een gok.
                jaar = p.get("bouwjaar")
                if jaar not in (None, ""):
                    try:
                        bouwjaar_per_pand[str(bag)] = int(str(jaar)[:4])
                    except ValueError:
                        # Een bouwjaar dat geen jaar is, is geen bouwjaar.
                        # Liever niets dan een getal dat nergens op slaat.
                        pass

    stand = (doorloop("pand", budget, per_pagina) if voortgang is None
             else doorloop("pand", budget, per_pagina, voortgang))
    stand["omzettingen"] = len(kaart)
    stand["met_status"] = len(status_per_pand)
    stand["met_bouwjaar"] = len(bouwjaar_per_pand)
    stand["velden_in_antwoord"] = sorted(velden)[:25]
    if status_per_pand:
        tel = {}
        for st in status_per_pand.values():
            tel[st] = tel.get(st, 0) + 1
        stand["pandstatussen"] = dict(sorted(tel.items(),
                                             key=lambda x: -x[1])[:10])
    if not kaart and not stand["fout"]:
        stand["fout"] = ("geen enkele omzetting; de pandcollectie levert geen "
                         "id met identificatie zoals verwacht")
    # De statuskaart gaat mee in de stand en niet als derde returnwaarde,
    # zodat elke bestaande aanroeper blijft werken.
    stand["_status_per_pand"] = status_per_pand
    stand["_bouwjaar_per_pand"] = bouwjaar_per_pand
    return kaart, stand


def fase_bag(voorraad, pcs, minuten, panden=None,
             pandstatus=None, pandbouwjaar=None,
             signalen=None, voortgang=None, open_panden=None):
    """
    Fase 1: alle verblijfsobjecten in de doos, daarna zeven op onze postcodes.

    WAAROM NIET MEER PER POSTCODE. PDOK laat postcode niet als filter toe, op
    geen van de zes collecties. Een vraag per postcode kan dus niet. Maar een
    ronde over het gebied om Nijmegen kostte gemeten 248,4 seconden voor
    164.634 objecten, dus het alternatief is niet duurder maar goedkoper dan de
    1.733 losse vragen die het ooit zouden zijn geweest.

    Dat verandert ook de aard van de fase. Er is geen achterstand meer, geen
    versheid per postcode en geen hervatten: elke ronde leest alles opnieuw en
    is binnen een paar minuten klaar. Het tijdbudget blijft als noodrem.

    DE SLEUTEL IS HET VERBLIJFSOBJECT EN NIET HET ADRES. Dat was eerst
    adressleutel(), straat plus nummer plus letter plus toevoeging zonder
    scheidingsteken. Daarin botsen huisnummer 1 toevoeging 2 en huisnummer 12
    op dezelfde sleutel, en 1B als huisletter met 1-B als toevoeging ook. De
    eerste echte ronde maakte zichtbaar hoe groot dat is: 22.096 objecten
    kwamen binnen en er bleven 22.003 records over, dus 93 woningen
    overschreven elkaar. Stil, en in de richting die het ergst is. De
    identificatie van het verblijfsobject kan niet botsen.

    EN ER WORDT NU OOK VERWIJDERD. Daarvoor werd alleen toegevoegd en
    overschreven. Een gesloopte woning bleef dan staan met haar oude status, en
    een winkel die woning werd stond in beide lijsten en werd twee keer
    geteld. Het aantal in de brief zou daardoor langzaam te hoog oplopen en
    plausibel blijven. Verwijderen gebeurt alleen na een afgemaakte ronde: een
    halve ronde weet niet wat er niet meer is.

    Geen sleutel nodig: PDOK is open data onder Public Domain Mark.
    """
    vandaag = dt.date.today().isoformat()
    gedaan = voorraad.setdefault("postcodes", {})
    adressen = voorraad.setdefault("adressen", {})
    # WAAROM DIT APART STAAT. Een adres zonder woonfunctie werd geteld en
    # daarna weggegooid, terwijl de BAG hem in hetzelfde antwoord meestuurt.
    # Winkels, kantoren en horeca in de plint zijn precies de verzameling die
    # de beleidsregel over de eerste bouwlaag raakt, en ze bewaren kost geen
    # enkele extra vraag. Ze staan onder een eigen sleutel en niet bij
    # "adressen", zodat fase 2 en alles wat later de woningvoorraad leest niet
    # ineens winkels meekrijgt. "adressen" blijft dus de woningvoorraad.
    anders = voorraad.setdefault("niet_woningen", {})
    # DE PIJPLIJN APART. Woningen met status "gevormd" horen hier en niet in
    # adressen; zie de uitleg bij de constante PIJPLIJN.
    pijplijn = voorraad.setdefault("pijplijn", {})
    panden = panden or {}
    opgelost = (vul_open_panden(voorraad, open_panden, panden, pandstatus,
                                pandbouwjaar) if open_panden else 0)

    tel = {"nieuw": 0, "bijgewerkt": 0, "onveranderd": 0, "woningen": 0,
           "overig": 0, "buiten_de_ring": 0, "weg": 0, "zonder_adres": 0,
           "zonder_pandsleutel": 0, "met_pand": 0, "gevormd": 0,
           "zonder_vbo": 0, "van_soort_gewisseld": 0, "opnieuw_gezien": 0,
           "in_de_pijplijn": 0, "opgeleverd": 0, "terug_in_de_pijplijn": 0,
           "meerdere_panden": 0, "om_een_signaal": 0,
           "met_punt": 0, "zonder_punt": 0, "punt_behouden": 0,
           "pand_behouden": 0, "pand_open": 0}
    # De adressen waarover een bekendmaking is gepubliceerd.
    # None betekent: zelf inlezen; een lege verzameling
    # betekent uitdrukkelijk geen signalen, en dat verschil
    # moet blijven bestaan voor de proef.
    signalen = signaaladressen() if signalen is None else signalen
    per_postcode = {}
    statussen = {}
    gezien_woning, gezien_anders = set(), set()
    gezien_pijplijn = set()
    # WAT DEZE CYCLUS AL GEZIEN IS, OOK IN EERDERE RUNS. Met voortgang loopt
    # een ronde over meer runs, en verwijderen mag pas als de hele cyclus rond
    # is. Dan moet bekend zijn wat de runs ervoor zagen; anders zou de laatste
    # run alles weggooien wat in de eerste tegels stond.
    hervat = bool(voortgang and voortgang.get("wacht"))
    if hervat:
        _g = voortgang.get("gezien") or {}
        gezien_woning.update(_g.get("woning") or [])
        gezien_pijplijn.update(_g.get("pijplijn") or [])
        gezien_anders.update(_g.get("anders") or [])
        for _pc in _g.get("postcodes") or []:
            per_postcode.setdefault(_pc, 0)
    opgeleverd = []
    # Elk object dat deze ronde al door verwerk() is gegaan, ook de objecten
    # buiten de ring en de historie, want ook die hebben tellers.
    gezien_alle = set()

    def verwerk(kenmerken):
        for k in kenmerken:
            p = k.get("properties") or {}

            # AL GEZIEN DEZE RONDE? HELEMAAL VOORAAN. Een tegel die pagina's
            # heeft afgeleverd en daarna mislukt wordt in vieren gedeeld en
            # opnieuw gelopen, dus dezelfde objecten komen nog een keer
            # voorbij. Stond deze regel verderop, dan liep alles wat ervoor
            # geteld wordt dubbel op: de statussen, de historie, nog_gevormd
            # en buiten_de_ring. Dat laatste is onschuldig, maar nog_gevormd
            # gedeeld door woningen_gezien is een drempel in het
            # gezondheidsrapport, en dan stond de teller voor en de noemer
            # achter de dedup. Een deling in een drukke tegel zou die drempel
            # dan halen zonder dat er iets aan de hand is.
            ident = str(p.get("identificatie") or "")
            if ident and ident in gezien_alle:
                tel["opnieuw_gezien"] += 1
                continue
            if ident:
                gezien_alle.add(ident)

            # DE ADRESVELDEN HIER AL, want de zeef heeft ze nodig: een object
            # buiten onze postcodes mag toch blijven als er een bekendmaking
            # over dat adres is. De omzetting is zuiver, dus eerder uitvoeren
            # verandert niets aan de tellers die hieronder staan.
            a = _normaliseer(p)
            pc = (p.get("postcode") or "").replace(" ", "").upper()
            buurten, herkomst = waarom_houden(a, pc, pcs, signalen, ident)
            if not herkomst:
                tel["buiten_de_ring"] += 1
                continue
            if herkomst == "bekendmaking":
                tel["om_een_signaal"] += 1
            status = p.get("status") or ""
            statussen[status] = statussen.get(status, 0) + 1
            # DE HISTORIE ERUIT. De collectie bevat ook ingetrokken en nooit
            # gerealiseerde objecten. Die meetellen zou elk aantal in de brief
            # te hoog maken zonder dat er iets faalt. Gemeten in de eerste
            # ronde: 1.955 ingetrokken en 427 niet gerealiseerd.
            if not _bestaat(status):
                tel["weg"] += 1
                continue
            if "gevormd" in status.lower():
                tel["gevormd"] += 1
            straat = a.get("openbareRuimteNaam", "")
            nr = a.get("huisnummer", "")
            if not straat or not nr:
                tel["zonder_adres"] += 1
                continue
            vbo = a.get("adresseerbaarObjectIdentificatie") or ""
            if not vbo:
                # Zonder identificatie is er geen sleutel die niet botst, en
                # dan is weglaten eerlijker dan terugvallen op het adres.
                tel["zonder_vbo"] += 1
                continue
            letter = a.get("huisletter") or ""
            toev = a.get("huisnummertoevoeging") or ""
            doelen = a.get("gebruiksdoelen") or []
            if herkomst == "focusbuurt":
                # ALLEEN DE FOCUSBUURTEN IN DEZE TWEE TELLINGEN. per_postcode
                # en gedaan beschrijven de ring. Een postcode die hier alleen
                # staat omdat er een bekendmaking over een adres was, zou
                # anders als afgewerkte ringpostcode gaan meetellen, en dan
                # klopt postcodes_leeg_nijmegen niet meer.
                per_postcode[pc] = per_postcode.get(pc, 0) + 1
                gedaan[pc] = vandaag

            # PDOK's pandsleutel omzetten naar de BAG-identificatie. Lukt dat
            # niet, dan blijft pand leeg: liever geen sleutel dan een sleutel
            # die op een pandidentificatie lijkt en nergens op aansluit.
            #
            # EEN VERBLIJFSOBJECT KAN IN MEER DAN EEN PAND LIGGEN. De
            # Waarderingskamer zegt het zo: "In de BAG ligt bij elk
            # verblijfsobject vast in welk pand (of panden) het
            # verblijfsobject is gelegen." Een woning over twee panden heen is
            # dus normaal, en de relatie is veel-op-veel.
            #
            # Hier stond een break op de eerste sleutel die oploste, en de
            # rest ging weg. Dat is dezelfde fout als met het gebruiksdoel en
            # met de zes veldnamen van EP-Online: de bron geeft een lijst en
            # wij houden er een over. Het raakt alles wat op pand joint: de
            # pandgeschiedenis, de 3D BAG, de bouwblokcontrole bij
            # kamerverhuur, en sinds vandaag de pandstatus die nieuwbouw van
            # transformatie scheidt. Welk pand je dan te pakken had, hing af
            # van de volgorde in het antwoord.
            #
            # Nu gaan ze alle mee. Het veld pand blijft de eerste, zodat elke
            # bestaande lezer blijft werken; wie het preciezer wil, leest
            # panden. En hoe vaak dit voorkomt staat in de stand, want tot nu
            # toe konden we dat niet eens meten.
            alle_panden = []
            for sleutel in a.get("pandIdentificaties") or []:
                bag_pand = panden.get(sleutel) or ""
                if bag_pand and bag_pand not in alle_panden:
                    alle_panden.append(bag_pand)
            pand = alle_panden[0] if alle_panden else ""
            if len(alle_panden) > 1:
                tel["meerdere_panden"] += 1
            if pand:
                tel["met_pand"] += 1
            elif a.get("pandIdentificaties"):
                tel["zonder_pandsleutel"] += 1

            woning = _is_woning(doelen)
            rec = {
                "adres": f"{straat} {nr}{letter}{('-' + toev) if toev else ''}",
                "sleutel": adressleutel(straat, nr, letter, toev),
                "postcode": pc,
                # ALLE BUURTEN EN NIET DE EERSTE OP ALFABET. Achtentwintig
                # postcodes staan in twee buurten. Werd daar de eerste op
                # alfabet gekozen, dan verloor Stadscentrum er elke keer een,
                # want die staat alfabetisch laatste. En Stadscentrum is
                # precies de buurt waarover de plintregel in de brief rekent,
                # dus dat was een vaste afwijking in één richting: 24 van de
                # 471 postcodes van Stadscentrum, zonder dat er iets faalde.
                "buurten": list(buurten),
                # WAAROM DIT RECORD ER IS. Zie waarom_houden(): alles wat per
                # buurt rekent, telt alleen focusbuurt mee.
                "herkomst": herkomst,
                # HET PUNT, VOOR DE PARKEERZONE. Zie punt_uit(). Ontbreekt de
                # geometrie, dan staat er niets en telt de ronde dat; een
                # geraden punt levert een parkeernorm op die klopt zolang
                # niemand hem nameet.
                "oppervlakte": a.get("oppervlakte"),
                "doelen": doelen,
                "pand": pand,
                "vbo": vbo,
                "status": status,
            }
            # Alleen opschrijven als er werkelijk meer dan een is: anders
            # staat er bij 22.000 records een lijst van een, en dat is een
            # megabyte aan niets.
            punt = punt_uit(k)
            if punt:
                rec["punt"] = punt
                tel["met_punt"] += 1
            else:
                tel["zonder_punt"] += 1
            # De pandvelden naast pand zelf: zie pandvelden().
            rec.update(pandvelden(alle_panden, pandstatus, pandbouwjaar))

            # BAG_GEZIEN ALLEEN BIJWERKEN ALS ER WERKELIJK IETS VERANDERDE.
            # Zou hier de datum van vandaag staan, dan verandert elk van de
            # 22.000 records elke ronde en is de dagelijkse wijziging het hele
            # bestand van ruim vijf megabyte. De repo zou dan met megabytes per
            # run groeien terwijl er niets nieuws in staat, en in de
            # geschiedenis zou niet te zien zijn wát er veranderde.
            # WAAR DIT OBJECT HOORT, EN WAAR HET VANDAAN KOMT. Drie secties:
            # woningen in gebruik, woningen in de pijplijn, en de rest. Een
            # object kan tussen alle drie bewegen, dus het bestaande record
            # wordt in alle drie opgezocht en niet alleen in de sectie waar
            # het nu in hoort. Zonder dat zou een oplevering een nieuw record
            # lijken en zou het oude blijven staan: dezelfde woning twee keer.
            in_pijplijn = _in_pijplijn(status)
            doel = pijplijn if (woning and in_pijplijn) else (
                adressen if woning else anders)
            vorige = None
            for sectie in (adressen, pijplijn, anders):
                if vbo in sectie:
                    vorige = sectie
                    break
            bestaand = (vorige.get(vbo) if vorige else None) or {}
            # EEN PUNT DAT WE AL HADDEN, BLIJFT STAAN. De ronde bouwt elk
            # record opnieuw op, dus een antwoord zonder geometrie zou het
            # punt weggooien. Dat is precies hoe op 12 oktober de
            # rekenmethode van 698 labels verdween. Dit staat vóór de
            # vergelijking met het oude record, zodat een behouden punt geen
            # wijziging heet.
            if not rec.get("punt") and bestaand.get("punt"):
                rec["punt"] = bestaand["punt"]
                tel["punt_behouden"] += 1
            # EEN PAND DAT WE AL HADDEN, BLIJFT STAAN ALS DE PANDFASE HET NIET
            # KON OPZOEKEN. De pandfase heeft een tijdbudget. Is dat op, dan
            # mist de omzetting een deel van de pandsleutels, en dan bouwde
            # deze regel het record opnieuw op met pand "". Op 7 november
            # stopte de pandfase na 9 van de 19 tegels en verloren 7.503 van
            # de 24.440 woningen hun pand; eerder gebeurde hetzelfde met
            # 8.590 en 8.575. Alles wat op pand joint viel dan stil om, onder
            # meer de bouwblokcontrole bij kamerverhuur: Keizer Karelplein 20
            # tot en met 31 is één pand, en zonder pand zag nummer 31 nummer
            # 30 niet meer tussen zichzelf en kamerpand 29.
            #
            # ALLEEN BIJ EEN SLEUTEL DIE NIET IN DE OMZETTING STAAT. Staat de
            # sleutel er wel in, dan heeft de pandfase hem gezien en geldt
            # wat zij zegt. Mist hij, dan is dat "niet gekeken" en niet
            # "geen pand", en dan overschrijft het oude record niets.
            _sleutels = a.get("pandIdentificaties") or []
            if (any(s not in panden for s in _sleutels)
                    and bestaand.get("pand")):
                for veld in PANDVELDEN:
                    if veld in bestaand:
                        rec[veld] = bestaand[veld]
                    else:
                        rec.pop(veld, None)
                tel["pand_behouden"] += 1
            # NOG NIETS OM TE BEHOUDEN: OP DE OPEN LIJST. Een nieuw object
            # waarvan de pandfase de sleutel deze run niet tegenkwam. De twee
            # fasen lopen elk in hun eigen tempo door de tegels, dus de run
            # waarin de pandfase deze sleutel wel ziet, hoeft deze tegel van
            # objecten niet te bezoeken. Zonder de lijst bleef zo'n object
            # zonder pand tot beide toevallig in dezelfde run langskwamen.
            if open_panden is not None:
                if (any(s not in panden for s in _sleutels)
                        and not rec.get("pand")):
                    open_panden[vbo] = sorted(_sleutels)
                    tel["pand_open"] += 1
                else:
                    open_panden.pop(vbo, None)
            zelfde = bool(bestaand) and all(bestaand.get(v) == rec[v]
                                            for v in rec)
            rec["bag_gezien"] = (bestaand.get("bag_gezien") or vandaag
                                 if zelfde else vandaag)

            # VAN SOORT GEWISSELD. Een winkel die woning wordt stond eerst in
            # beide lijsten en werd twee keer geteld.
            if vorige is not None and vorige is not doel:
                del vorige[vbo]
                if vorige is pijplijn and doel is adressen:
                    # DIT IS EEN OPLEVERING, EN HET ENIGE MOMENT WAAROP DE
                    # VOORRAAD WERKELIJK GROEIT. Een vergunning zegt dat het
                    # mag en een gevormd object zegt dat het geregistreerd is;
                    # pas de gereedmelding zegt dat er iemand kan wonen. Dat
                    # hoort geteld en gemeld, want het is het soort nieuws
                    # waar de brief voor bestaat.
                    tel["opgeleverd"] += 1
                    opgeleverd.append(rec["adres"])
                elif doel is pijplijn and vorige is adressen:
                    # De andere kant op: een object dat in gebruik was en nu
                    # weer gevormd heet. Dat hoort niet te gebeuren, dus als
                    # het gebeurt wil ik het zien in plaats van het stil te
                    # verwerken.
                    tel["terug_in_de_pijplijn"] += 1
                else:
                    tel["van_soort_gewisseld"] += 1

            if not woning:
                tel["overig"] += 1
                anders[vbo] = rec
                gezien_anders.add(vbo)
                continue
            if in_pijplijn:
                tel["in_de_pijplijn"] += 1
                gezien_pijplijn.add(vbo)
                pijplijn[vbo] = rec
                continue
            tel["woningen"] += 1
            gezien_woning.add(vbo)
            # EEN EERDER OPGEHAALD LABEL BLIJFT STAAN; dat komt uit fase 2.
            #
            # OP DE VOORVOEGSEL EN NIET OP EEN LIJSTJE. Hier stonden de drie
            # velden label, label_datum en label_gezien met de naam erin, en
            # op 12 oktober heb ik label_nta8800 toegevoegd zonder ze aan dit
            # lijstje toe te voegen. Gevolg: de objectronde van vannacht
            # gooide de rekenmethode van alle 698 bestaande labels weg, en
            # ook label_prive en label_fout, die er al langer stonden. Te
            # zien in de stand: 698 labels zonder methode, allemaal met
            # label_gezien 2026-10-11, tegen 581 met methode van vandaag.
            #
            # Een lijstje dat moet worden bijgewerkt als er een veld bij komt,
            # wordt niet bijgewerkt. Dit voorvoegsel hoeft dat niet: elk veld
            # dat fase 2 schrijft heet label-iets, en daarmee kan de volgende
            # toevoeging deze fout niet nog een keer maken.
            for veld, waarde in bestaand.items():
                if str(veld).startswith("label") and waarde is not None:
                    rec[veld] = waarde
            if not bestaand:
                tel["nieuw"] += 1
            elif zelfde:
                tel["onveranderd"] += 1
            else:
                tel["bijgewerkt"] += 1
            adressen[vbo] = rec

    stand = (doorloop("verblijfsobject", minuten * 60, verwerk)
             if voortgang is None else
             doorloop("verblijfsobject", minuten * 60, verwerk, voortgang))
    if voortgang is not None and voortgang.get("wacht"):
        # Gesorteerd, zodat twee runs met dezelfde verzameling hetzelfde
        # bestand geven en de diff alleen de nieuwe sleutels laat zien.
        voortgang["gezien"] = {"woning": sorted(gezien_woning),
                               "pijplijn": sorted(gezien_pijplijn),
                               "anders": sorted(gezien_anders),
                               "postcodes": sorted(per_postcode)}

    # WAT ER NIET MEER IS, GAAT ERUIT. Alleen na een afgemaakte ronde, want een
    # halve ronde weet niet wat er niet meer is en zou de helft van de ring
    # weggooien.
    verwijderd = 0
    if stand["ronde_af"]:
        # EN ALLEEN BINNEN DE GEVRAAGDE POSTCODES. Zonder deze voorwaarde
        # wiste "python voorraad_bag.py --buurt Bottendaal" de andere vijf
        # buurten: die objecten komen binnen als buiten_de_ring, staan niet in
        # gezien, en zouden dus verdwijnen. Dat commando staat in de docstring
        # aanbevolen als manier om één buurt te proeven, dus het was een
        # proefdraai die 22.096 woningen op ongeveer 1.700 zette en dat
        # commit, zonder dat er iets faalde.
        for lijst, gezien in ((adressen, gezien_woning),
                              (pijplijn, gezien_pijplijn),
                              (anders, gezien_anders)):
            for vbo in [v for v, r in lijst.items()
                        if v not in gezien
                        and (r.get("postcode") or "") in pcs]:
                del lijst[vbo]
                verwijderd += 1
        # En de postcodes die niet meer in de zeef zitten, zodat de dekking
        # niet op een postcode blijft staan die er niet meer bij hoort.
        for pc in [x for x in gedaan if x not in pcs]:
            del gedaan[pc]

    # DE LEGE POSTCODES TELLEN, GESPLITST. Dit is de controle op de doos: raakt
    # hij de ring ergens niet, dan blijven de postcodes daar leeg. Maar de
    # eerste echte ronde liet zien dat 491 van de 1.733 postcodes in de
    # inventaris helemaal niet in Nijmegen liggen: 2771 Boskoop, 4201
    # Gorinchem, 5103 Dongen, 9401 Assen en nog vier. Die zouden het signaal
    # over de doos voorgoed verdoezelen. Daarom apart: alleen een lege
    # Nijmeegse postcode zegt iets over de doos.
    #
    # EN ALLEEN NA EEN AFGEMAAKTE RONDE. Een postcode in een tegel die deze
    # run niet aan de beurt was, is niet gekeken en niet leeg. Op 7 november
    # stonden er zo 897 "lege" Nijmeegse postcodes in de stand, met in het
    # gezondheidsrapport het advies de doos ruimer te maken. Dat advies was
    # fout: de doos was goed, de ronde was half. Niet af is daarom None, niet
    # gemeten, en geen getal dat op nul lijkt. Met voortgang telt de hele
    # cyclus mee, ook de postcodes die eerdere runs zagen.
    leeg = sorted(pc for pc in pcs if pc not in per_postcode)
    leeg_nijmegen = [pc for pc in leeg if pc.startswith("65")]
    _gemeten = bool(stand.get("ronde_af"))
    uit = {
        "postcodes_gedaan": len(per_postcode),
        "postcodes_totaal": len(pcs),
        "postcodes_nijmegen": sum(1 for pc in pcs if pc.startswith("65")),
        "postcodes_leeg": len(leeg) if _gemeten else None,
        "postcodes_leeg_nijmegen": len(leeg_nijmegen) if _gemeten else None,
        "postcodes_buiten_nijmegen": (len(leeg) - len(leeg_nijmegen)
                                      if _gemeten else None),
        "postcodes_leeg_voorbeeld": ((leeg_nijmegen[:12] or leeg[:6])
                                     if _gemeten else []),
        "adressen_nieuw": tel["nieuw"],
        "adressen_bijgewerkt": tel["bijgewerkt"],
        "adressen_onveranderd": tel["onveranderd"],
        "adressen_verwijderd": verwijderd,
        "van_soort_gewisseld": tel["van_soort_gewisseld"],
        "woningen_gezien": tel["woningen"],
        "niet_woonfunctie": tel["overig"],
        "niet_woningen_bewaard": len(anders),
        "buiten_de_ring": tel["buiten_de_ring"],
        # Objecten die buiten de focusbuurten liggen en toch bewaard zijn,
        # omdat er een bekendmaking over dat adres is gepubliceerd. Zie
        # waarom_houden(). Dit getal hoort in de stand, want anders is niet te
        # zien of de ruimere zeef werkelijk iets oplevert.
        "om_een_signaal": tel["om_een_signaal"],
        "met_punt": tel["met_punt"],
        "zonder_punt": tel["zonder_punt"],
        "punt_behouden": tel["punt_behouden"],
        "pand_behouden": tel["pand_behouden"],
        # Hoeveel objecten deze run op de open lijst kwamen, en hoeveel van
        # eerdere runs er nu een pand kregen. pand_open_totaal is wat er na
        # deze run nog openstaat.
        "pand_open": tel["pand_open"],
        "pand_opgelost": opgelost,
        "pand_open_totaal": len(open_panden) if open_panden is not None
        else None,
        "historie_overgeslagen": tel["weg"],
        # NOG GEVORMD, NIET IN GEBRUIK. In de eerste ronde 2.238 objecten,
        # ruim een tiende van de voorraad. Die status betekent dat het object
        # in de registratie is gevormd maar nog niet als in gebruik is
        # gemeld. Ze worden meegeteld, want tien procent eruit gooien op een
        # vermoeden is een grotere ingreep dan ze laten staan, en de status
        # staat per record bewaard zodat het later te zeven is. Het getal
        # staat hier zodat de vraag open blijft in plaats van stil beslist.
        "nog_gevormd": tel["gevormd"],
        # Hoe vaak een verblijfsobject in meer dan een pand ligt. Tot 11
        # oktober hielden we er een over en konden we dit niet meten.
        "objecten_in_meer_panden": tel["meerdere_panden"],
        # DE PIJPLIJN, APART GETELD EN APART GEMELD. nog_gevormd hierboven
        # telt elk object met die status, ook de niet-woningen; deze drie gaan
        # over de woningen en over wat er met ze gebeurde.
        "pijplijn_bewaard": len(pijplijn),
        "pijplijn_gezien": tel["in_de_pijplijn"],
        "opgeleverd": tel["opgeleverd"],
        "opgeleverde_adressen": sorted(opgeleverd)[:40],
        "terug_in_de_pijplijn": tel["terug_in_de_pijplijn"],
        "zonder_adres": tel["zonder_adres"],
        "zonder_vbo": tel["zonder_vbo"],
        "opnieuw_gezien": tel["opnieuw_gezien"],
        # ALLE OBJECTEN EN NIET ALLEEN DE WONINGEN, want de teller
        # wordt ook voor winkels verhoogd. Heette dit woningen_met_pand, dan
        # deelde het gezondheidsrapport door het verkeerde getal en kwam er
        # een percentage boven honderd uit.
        "objecten_met_pand": tel["met_pand"],
        "zonder_pandsleutel": tel["zonder_pandsleutel"],
        "statussen": dict(sorted(statussen.items(), key=lambda x: -x[1])[:8]),
        "fouten": 1 if stand["fout"] else 0,
        "laatste_fout": stand["fout"],
    }
    uit.update({f"ronde_{k}": v for k, v in stand.items() if k != "fout"})
    return uit


def haal_label(rec):
    """
    Het energielabel van één adres, uit EP-Online. Geeft (uit, fout, klaar).

    DEZE FUNCTIE WAS STUK, EN HET ZAG ERUIT ALS EEN FEIT. Hij vroeg alleen op
    postcode en las alleen het veld "labelLetter". Op 10 oktober kwamen zo 803
    van 818 adressen terug als "geen label bekend" en 15 als HTTP 400: nul
    labels, terwijl de pandgeschiedenis er met de werkende aanroep 1.384 kent.
    Die 803 waren geen antwoord maar een veldnaam die niet bestond. De API gaf
    HTTP 200, de lus vond geen "labelLetter", en dat werd opgeschreven als een
    eigenschap van de woningvoorraad.

    Twee dingen die er nu bij komen. De route op verblijfsobject-id, die exact
    is en die de twee andere aanroepers altijd al gebruikten; elk record in de
    voorraad heeft dat id al, want het is de sleutel van het bestand. En het
    derde element klaar: of opnieuw vragen zin heeft. Zonder dat bleven de 15
    adressen met HTTP 400 elke ronde vooraan in de wachtrij staan, want
    label_gezien werd bij een fout niet gezet.
    """
    nr, letter, toev = _epo.uit_adres(rec.get("adres") or "")
    return _epo.energielabel(rec.get("vbo") or None,
                             rec.get("postcode") or "", nr, letter, toev)


def fase_labels(voorraad, minuten):
    """Fase 2: EP-Online voor de woningen zonder label, tot de tijd om is."""
    if not EP_API_KEY:
        print("Geen EP_API_KEY; fase labels overgeslagen", file=sys.stderr)
        return {"overgeslagen": "geen sleutel"}

    vandaag = dt.date.today().isoformat()
    adressen = voorraad.setdefault("adressen", {})

    # Welke adressen nog aan de beurt zijn. Nooit gevraagd gaat voor. Daarna
    # de adressen waar EP-Online geen label van kende en waar dat lang genoeg
    # geleden is: een label wordt pas geregistreerd bij een verkoop of een
    # verbouwing, dus een adres dat vandaag geen label heeft kan er volgend
    # jaar wel een hebben. Zonder die hernieuwing zou één antwoord "niet
    # bekend" een blinde vlek worden die nooit meer dichtgaat.
    opnieuw = (dt.date.today() - dt.timedelta(days=LABEL_OPNIEUW_DAGEN)
               ).isoformat()
    nooit, verlopen, zonder_methode, stuk_gevraagd = [], [], [], []
    for s, r in adressen.items():
        if r.get("label"):
            # EEN LABEL ZONDER REKENMETHODE WORDT EEN KEER INGEHAALD. De
            # methode wordt sinds 12 oktober bewaard; de 67 labels die er
            # toen al stonden hebben hem niet, en een gevonden label komt
            # anders pas aan de beurt als het verloopt. Dat is een jaar of
            # langer met een letter waarvan de grondslag niet te zien is.
            #
            # DE GRENS IS DE DATUM EN NIET HET VELD. Zou hier staan "vraag
            # opnieuw zolang de methode ontbreekt", dan blijft een adres
            # waarvan EP-Online geen Berekeningstype geeft elke ronde terug
            # komen, voor altijd. Met label_gezien voor de grens vraagt hij
            # het precies een keer: daarna staat de datum van vandaag erin.
            # Dezelfde vorm als GRONDSLAG_VANAF in splitsing_voltooid.py.
            if (r.get("label_nta8800") is None
                    and (r.get("label_gezien") or "") < METHODE_VANAF):
                zonder_methode.append(s)
            continue
        gezien = r.get("label_gezien")
        if not gezien:
            nooit.append(s)
        elif _stuk_gevraagd(r):
            stuk_gevraagd.append(s)
        elif gezien < opnieuw:
            verlopen.append(s)
    # DE INHAALSLAG GAAT VOOROP, EN DAT IS GEEN SMAAKKWESTIE. Hij stond
    # achteraan, achter de 17.321 adressen die nog nooit zijn gevraagd. Bij
    # ongeveer 900 aanroepen per ronde komt hij dan pas over negentien rondes
    # aan de beurt, en tot die tijd staat er bij 698 labels geen grondslag.
    # Een wachtrij met een lange staart vooraan betekent dat alles wat
    # erachter staat nooit draait.
    #
    # Dat kan omdat de inhaalslag begrensd is en zichzelf opheft: 698 stuks,
    # een kwartier, en na die ene ronde is de rij leeg omdat elk gevraagd
    # adres de datum van vandaag krijgt. Het kost dus een kwartier van een
    # ronde, een keer, en daarna niets meer. Een inhaalslag die niet eindigt
    # zou hier niet vooraan mogen staan.
    #
    # De stuk gevraagde adressen staan om dezelfde reden vooraan: 1.097
    # stuks, begrensd door een datum, en daarna leeg.
    nog = (sorted(zonder_methode, key=lambda s: adressen[s].get("adres", ""))
           + sorted(stuk_gevraagd, key=lambda s: adressen[s].get("adres", ""))
           + sorted(nooit, key=lambda s: adressen[s].get("adres", ""))
           + sorted(verlopen, key=lambda s: adressen[s].get("label_gezien", "")))

    begin = time.time()
    einde = begin + minuten * 60
    gevraagd = met_label = zonder = fouten = prive = 0
    inhaal, methode_erbij, methode_blijft_weg = set(zonder_methode), 0, 0
    herhaal, herhaald_met_label, herhaald_zonder = set(stuk_gevraagd), 0, 0
    laatste_fout = ""
    for sleutel in nog:
        if time.time() > einde:
            break
        rec = adressen[sleutel]
        uit, fout, klaar = haal_label(rec)
        time.sleep(TEMPO)
        gevraagd += 1
        if uit is None:
            fouten += 1
            laatste_fout = f"{rec.get('adres')}: {fout}"
            # EEN DEFINITIEVE WEIGERING IS EEN ANTWOORD OVER DIT ADRES.
            # HTTP 400 en 404 op alle routes betekenen dat deze vraag nooit
            # gaat lukken. Zonder dit op te schrijven blijft het adres
            # vooraan in de wachtrij staan en kost het elke ronde opnieuw een
            # aanroep: op 10 oktober waren dat 15 van de 818. Een
            # netwerkstoring of een 429 is iets van ons en niet van het
            # adres, en die wordt dus wel opnieuw geprobeerd.
            if klaar:
                rec["label_gezien"] = vandaag
                rec["label_fout"] = fout
            elif "429" in fout or "401" in fout or "403" in fout:
                break
            continue
        rec["label_gezien"] = vandaag
        rec.pop("label_fout", None)
        if uit.get("label"):
            rec["label"] = uit["label"]
            rec["label_datum"] = uit.get("registratiedatum") or ""
            # DE GRONDSLAG ERBIJ, EN NIET DE HELE TEKST. EP-Online geeft de
            # rekenmethode als lange zin mee, en in pand 0268100000026050
            # staan twee labels volgens de Rekenmethodiek van 2014 naast drie
            # volgens NTA 8800. Een D van 2017 is dan geen slechter huis dan
            # een C van 2026 maar een andere methode, en de eis zegt dat een
            # getal nooit met een getal op een andere grondslag wordt
            # vergeleken.
            #
            # Alleen de ja-of-nee gaat mee en niet de zin zelf: die is zo'n
            # zeventig tekens, en bij ruim twintigduizend adressen zou dat
            # anderhalve megabyte aan hetzelfde zinnetje in een bestand van
            # vijf zijn. De volle tekst staat in eponline_antwoordvorm.json.
            if uit.get("nta8800") is not None:
                rec["label_nta8800"] = uit["nta8800"]
            # EEN INGEHAALD LABEL IS GEEN NIEUW LABEL. Zou dit bij
            # label_gevonden worden geteld, dan loopt die teller op zonder
            # dat er een woning bij is gekomen, en dat is dezelfde soort
            # misleiding als de 46 "fouten" die antwoorden waren.
            if sleutel in herhaal:
                # Apart geteld: dit label bestond al, wij hadden het verkeerd
                # gelezen. Bij label_gevonden zou het lijken alsof er die
                # ronde woningen een label hebben gekregen.
                herhaald_met_label += 1
            elif sleutel not in inhaal:
                met_label += 1
            elif rec.get("label_nta8800") is None:
                methode_blijft_weg += 1
            else:
                methode_erbij += 1
        elif uit.get("prive"):
            # Er IS een label, het is alleen niet openbaar. Dat als "niet
            # bekend" opschrijven betekent dat we het volgend jaar opnieuw
            # vragen en hetzelfde krijgen.
            rec["label_prive"] = True
            prive += 1
        elif sleutel in inhaal:
            # Dit adres HEEFT een label; de inhaalvraag leverde alleen niets
            # op. Als "geen label bekend" tellen zou de teller laten oplopen
            # bij een record dat gewoon een label heeft.
            methode_blijft_weg += 1
        elif sleutel in herhaal:
            herhaald_zonder += 1
        else:
            zonder += 1

    resterend = sum(1 for r in adressen.values()
                    if not r.get("label") and not r.get("label_gezien"))
    # DE GRONDSLAG IN DE STAND, EN NIET ALLEEN IN DE RECORDS. Een veld dat
    # per woning wordt opgeschreven en nergens wordt geteld, ziet niemand.
    # Gemeten op 11 oktober: van de 698 labels zijn er 221 bepaald met de
    # methode van 2014 en 410 met NTA 8800, en 67 hebben geen methode omdat
    # ze zijn opgehaald voordat dat veld werd bewaard. Die verhouding hoort
    # in de stand, want zij bepaalt of twee labels naast elkaar mogen staan.
    alle = [r for r in adressen.values() if r.get("label")]
    # HET GEMETEN TEMPO, zodat niemand het hoeft te schatten. Hoeveel rondes
    # er nog nodig zijn voor de 16.518 adressen die nooit zijn gevraagd, is
    # dit getal gedeeld op dat aantal. Een geschat tempo zou hier een vals
    # getal zijn: de ene ronde loopt tegen een trage API aan en de andere
    # niet, en het budget is een bovengrens en geen duur.
    duur = max(time.time() - begin, 0.001)
    return {"gevraagd": gevraagd, "label_gevonden": met_label,
            "seconden": round(duur, 1),
            "aanroepen_per_minuut": round(gevraagd / (duur / 60), 1),
            "geen_label_bekend": zonder, "label_prive": prive,
            "nog_nooit_gevraagd": resterend,
            "opnieuw_aan_de_beurt": len(verlopen),
            "methode_ingehaald": methode_erbij,
            # Hoeveel van de stuk gevraagde adressen bij de tweede vraag wel
            # een label bleken te hebben, en hoeveel er nog in de rij staan;
            # die laatste geteld zoals de wachtrij telt.
            "herhaald_label_gevonden": herhaald_met_label,
            "herhaald_geen_label": herhaald_zonder,
            "herhaald_nog_te_vragen": sum(
                1 for r in adressen.values() if _stuk_gevraagd(r)),
            "methode_blijft_onbekend": methode_blijft_weg,
            # Op dezelfde manier geteld als de wachtrij zelf, en niet uit
            # een aftreksom: zo kan dit getal niet uit elkaar lopen met wat
            # de volgende ronde werkelijk gaat vragen.
            "methode_nog_in_te_halen": sum(
                1 for r in adressen.values()
                if r.get("label") and r.get("label_nta8800") is None
                and (r.get("label_gezien") or "") < METHODE_VANAF),
            "labels_nta8800": sum(1 for r in alle
                                  if r.get("label_nta8800") is True),
            "labels_methode_2014": sum(1 for r in alle
                                       if r.get("label_nta8800") is False),
            "labels_zonder_methode": sum(1 for r in alle
                                         if r.get("label_nta8800") is None),
            "fouten": fouten, "laatste_fout": laatste_fout}


# De kenmerken hieronder zijn overgenomen uit wat PDOK op 10 oktober
# werkelijk teruggaf, inclusief het veld pand.href, het enkelvoudige
# gebruiksdoel met komma's erin en de statussen uit de historie. Verzonnen
# vormen hebben vandaag twee keer een stille fout opgeleverd: gebruiksdoelen
# bleek een lijst waar een string stond, en energielabel een dict waar een
# tekst stond. Daarom hier de echte vorm.
def tekst_pijplijn(pad=UIT):
    """
    Een blok voor de bijlage: wat er aan woningen onderweg is naar de ring.

    DIT IS GEEN RUIS DIE WE WEGGOOIEN. De pijplijn hoort niet in de voorraad,
    want die woningen zijn er nog niet. Maar 2.168 woningen die naar zes
    buurten komen is precies het soort cijfer waar deze brief voor bestaat, en
    het staat per straat in onze eigen gegevens. Stadscentrum krijgt er 24
    procent bovenop wat er nu staat.

    Wat dit NIET zegt: wanneer. De BAG kent de status gevormd en de
    gereedmelding, maar geen opleverdatum, dus hier staat geen jaartal. En het
    zegt niet of het nieuwbouw of transformatie is: dat hangt aan de status
    van het PAND en die slaan wij niet op.
    """
    try:
        with open(pad, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return ""
    pl = d.get("pijplijn") or {}
    ad = d.get("adressen") or {}
    if not pl:
        return ""
    per_buurt, per_straat, in_buurt = {}, {}, {}
    for rec in pl.values():
        for b in rec.get("buurten") or []:
            per_buurt[b] = per_buurt.get(b, 0) + 1
        m = re.match(r"^(.+?)\s+\d", rec.get("adres") or "")
        if m:
            per_straat[m.group(1)] = per_straat.get(m.group(1), 0) + 1
    for rec in ad.values():
        for b in rec.get("buurten") or []:
            in_buurt[b] = in_buurt.get(b, 0) + 1

    r = ["## Woningen onderweg naar de ring", ""]
    # WAT HIER OVER HET PAND STAAT, EN WAT NIET. Hier stond eerst "het pand
    # heeft vergunning of de bouw is gestart". Dat is de definitie van het
    # CBS, en die gaat over de status van het PAND. Wij meten de status van
    # het verblijfsOBJECT: een pandidentificatie slaan we op, een pandstatus
    # tot 11 oktober niet. Dus beweerde die zin iets wat niet gemeten was,
    # precies de fout die deze brief steeds inhaalt. De pandfase schrijft die
    # status nu wel op, dus zodra er een ronde over is geweest kan dit scherper.
    met_pandstatus = sum(1 for rec in pl.values() if rec.get("pand_status"))
    r.append(f"_{len(pl)} woningen in de ringbuurten hebben in de BAG de "
             f"status 'gevormd': het verblijfsobject is geregistreerd maar "
             f"nog niet als in gebruik gemeld. Het CBS rekent zulke objecten "
             f"tot de pijplijn en niet tot de woonvoorraad, en wij nu ook. Ze "
             f"komen in de voorraad op het moment dat ze in gebruik worden "
             f"gemeld, en dat moment melden wij dan ook. De BAG kent geen "
             f"opleverdatum, dus hier staat niet wanneer._")
    if met_pandstatus:
        soorten = {}
        for rec in pl.values():
            st = rec.get("pand_status") or ""
            if st:
                soorten[st] = soorten.get(st, 0) + 1
        r.append("")
        r.append("_De status van het pand erbij, want die scheidt nieuwbouw "
                 "van transformatie: "
                 + ", ".join(f"{st} ({n})" for st, n
                             in sorted(soorten.items(), key=lambda x: -x[1]))
                 + "._")
        # DE GROEP DIE DE PANDSTATUS NIET SPLITST. Een object dat gevormd is
        # in een pand dat AL IN GEBRUIK is, is twee dingen die niets met
        # elkaar te maken hebben: een splitsing van bestaande voorraad, of
        # nieuwbouw die net is opgeleverd terwijl de objecten nog niet in
        # gebruik zijn gemeld. Op 11 oktober waren dat 697 van de 2.168, dus
        # bijna een derde, en samengevoegd zeggen ze niets. Het bouwjaar van
        # het pand beslist het, en dat halen we sinds 12 oktober op.
        in_gebruik = [rec for rec in pl.values()
                      if (rec.get("pand_status") or "") == "Pand in gebruik"]
        if in_gebruik:
            met_jaar = [rec for rec in in_gebruik if rec.get("pand_bouwjaar")]
            r.append("")
            if not met_jaar:
                r.append(f"_Van die groep zitten er {len(in_gebruik)} in een "
                         f"pand dat al in gebruik is. Dat is of een splitsing "
                         f"van bestaande voorraad of nieuwbouw die net is "
                         f"opgeleverd, en zonder het bouwjaar van het pand is "
                         f"dat niet te scheiden. Dat bouwjaar wordt sinds 12 "
                         f"oktober opgehaald en staat er nog niet bij: dit is "
                         f"dus nog niet gekeken en niet niets gevonden._")
            else:
                grens = dt.date.today().year - 5
                oud = [rec for rec in met_jaar
                       if rec["pand_bouwjaar"] < grens]
                nieuw = [rec for rec in met_jaar
                         if rec["pand_bouwjaar"] >= grens]
                zonder = len(in_gebruik) - len(met_jaar)
                r.append(f"_Van die groep zitten er {len(in_gebruik)} in een "
                         f"pand dat al in gebruik is. Met het bouwjaar van "
                         f"het pand erbij: {len(oud)} in een pand van voor "
                         f"{grens}, dus nieuwe woningen in bestaande "
                         f"voorraad, en {len(nieuw)} in een pand van "
                         f"{grens} of later, dus nieuwbouw waarvan het pand "
                         f"al klaar is en de woningen nog niet in gebruik "
                         f"gemeld."
                         + (f" Van {zonder} is het bouwjaar niet bekend."
                            if zonder else "")
                         + " De grens van vijf jaar is een keuze en geen"
                           " definitie van het CBS._")
    r.append("")
    r.append("| buurt | onderweg | staat er nu | erbij |")
    r.append("|---|---:|---:|---:|")
    for b, n in sorted(per_buurt.items(), key=lambda x: -x[1]):
        nu = in_buurt.get(b, 0)
        deel = f"+{n / nu * 100:.0f}%" if nu else "onbekend"
        r.append(f"| {b} | {n} | {nu} | {deel} |")
    r.append("")
    top = sorted(per_straat.items(), key=lambda x: -x[1])[:8]
    if top:
        r.append("De straten waar het zit: "
                 + ", ".join(f"{s} ({n})" for s, n in top)
                 + f". In totaal {len(per_straat)} straten.")
        r.append("")
    if not met_pandstatus:
        r.append("_Of dit nieuwbouw of transformatie van een bestaand pand "
                 "is, staat hier nog niet: dat hangt aan de status van het "
                 "PAND, en die hebben we pas sinds 11 oktober en nog niet "
                 "over een hele ronde. Wat we wel zien: van de panden met een "
                 "object in de pijplijn hebben de meeste ook woningen die al "
                 "in gebruik zijn, dus een deel is transformatie en dat "
                 "rekent het CBS juist niet tot de pijplijn._")
    return "\n".join(r)


PROEF_KENMERKEN = [
    # 1. Gewone woning in onze postcode, pand bekend in de kaart.
    {"id": "v1", "properties": {
        "postcode": "6521AB", "status": "Verblijfsobject in gebruik",
        "gebruiksdoel": "woonfunctie", "oppervlakte": 72,
        "openbare_ruimte_naam": "Bottelstraat", "huisnummer": 12,
        "huisletter": None, "toevoeging": None, "identificatie": "0268010000000001",
        "pand.href": ["https://api.pdok.nl/kadaster/bag/ogc/v2/collections/"
                      "pand/items/uuid-een"]}},
    # 2. Ingetrokken object in onze postcode: historie, moet eruit.
    {"id": "v2", "properties": {
        "postcode": "6521AB", "status": "Verblijfsobject ingetrokken",
        "gebruiksdoel": "woonfunctie", "oppervlakte": 65,
        "openbare_ruimte_naam": "Bottelstraat", "huisnummer": 14,
        "identificatie": "0268010000000002", "pand.href": []}},
    # 3. Nooit gebouwd: ook historie.
    {"id": "v3", "properties": {
        "postcode": "6521AB", "status": "Niet gerealiseerd verblijfsobject",
        "gebruiksdoel": "woonfunctie", "oppervlakte": 80,
        "openbare_ruimte_naam": "Bottelstraat", "huisnummer": 16,
        "identificatie": "0268010000000003", "pand.href": []}},
    # 4. Winkel in de plint: geen woning, wel bewaren.
    {"id": "v4", "properties": {
        "postcode": "6511AA", "status": "Verblijfsobject in gebruik",
        "gebruiksdoel": "winkelfunctie", "oppervlakte": 180,
        "openbare_ruimte_naam": "Broerstraat", "huisnummer": 3,
        "identificatie": "0268010000000004",
        "pand.href": ["https://api.pdok.nl/kadaster/bag/ogc/v2/collections/"
                      "pand/items/uuid-twee"]}},
    # 5. Gemengd gebruik: de komma's zijn echt, dit moet een woning zijn.
    {"id": "v5", "properties": {
        "postcode": "6511AA", "status": "Verblijfsobject in gebruik",
        "gebruiksdoel": "winkelfunctie,woonfunctie", "oppervlakte": 140,
        "openbare_ruimte_naam": "Broerstraat", "huisnummer": 5,
        "identificatie": "0268010000000005",
        "pand.href": ["https://api.pdok.nl/kadaster/bag/ogc/v2/collections/"
                      "pand/items/uuid-twee"]}},
    # 6. Buiten de ring: moet geteld maar niet bewaard worden.
    {"id": "v6", "properties": {
        "postcode": "6551ZE", "status": "Verblijfsobject in gebruik",
        "gebruiksdoel": "woonfunctie", "oppervlakte": 144,
        "openbare_ruimte_naam": "Bonenkampstraat", "huisnummer": 4,
        "identificatie": "0268010000000006", "pand.href": []}},
    # 7. Geen huisnummer: niet te sleutelen.
    {"id": "v7", "properties": {
        "postcode": "6521AB", "status": "Verblijfsobject in gebruik",
        "gebruiksdoel": "woonfunctie", "oppervlakte": 50,
        "openbare_ruimte_naam": "Bottelstraat", "huisnummer": None,
        "identificatie": "0268010000000007", "pand.href": []}},
    # 8. Pand niet in de kaart: pand blijft leeg en wordt geteld.
    {"id": "v8", "properties": {
        "postcode": "6521AB", "status": "Verblijfsobject in gebruik",
        "gebruiksdoel": "woonfunctie", "oppervlakte": 90,
        "openbare_ruimte_naam": "Bottelstraat", "huisnummer": 18,
        "identificatie": "0268010000000008",
        "pand.href": ["https://api.pdok.nl/kadaster/bag/ogc/v2/collections/"
                      "pand/items/uuid-onbekend"]}},
    # 9. Gevormd: geregistreerd maar nog niet gereedgemeld. Dit is een woning
    #    in de pijplijn en geen woning in de voorraad; het CBS rekent hem ook
    #    niet mee. Op 11 oktober stonden er 2.168 van in adressen, bijna 11
    #    procent van de ring.
    {"id": "v9", "properties": {
        "postcode": "6521AB", "status": "Verblijfsobject gevormd",
        "gebruiksdoel": "woonfunctie", "oppervlakte": 68,
        "openbare_ruimte_naam": "Bottelstraat", "huisnummer": 20,
        "identificatie": "0268010000000009", "pand.href": []}},
    # 10. Een tweede gevormd object op hetzelfde huisnummer als 1. Dit is de
    #     vorm die 134 huisnummers liet lijken alsof ze uit meer woningen
    #     bestaan dan er in gebruik zijn, en daar hangt de insluitingstoets
    #     voor kamerverhuur aan.
    {"id": "v10", "properties": {
        "postcode": "6521AB", "status": "Verblijfsobject gevormd",
        "gebruiksdoel": "woonfunctie", "oppervlakte": 44,
        "openbare_ruimte_naam": "Bottelstraat", "huisnummer": 12,
        "huisletter": "A",
        "identificatie": "0268010000000010", "pand.href": []}},
    # 12. Een woning die in TWEE panden ligt. De Waarderingskamer: "In de BAG
    #     ligt bij elk verblijfsobject vast in welk pand (of panden) het
    #     verblijfsobject is gelegen." Hier stond een break op de eerste
    #     sleutel die oploste, en de rest ging weg; welk pand je dan te pakken
    #     had, hing af van de volgorde in het antwoord.
    {"id": "v12", "properties": {
        "postcode": "6521AB", "status": "Verblijfsobject in gebruik",
        "gebruiksdoel": "woonfunctie", "oppervlakte": 210,
        "openbare_ruimte_naam": "Bottelstraat", "huisnummer": 22,
        "identificatie": "0268010000000012",
        "pand.href": ["https://api.pdok.nl/kadaster/bag/ogc/v2/collections/"
                      "pand/items/uuid-een",
                      "https://api.pdok.nl/kadaster/bag/ogc/v2/collections/"
                      "pand/items/uuid-twee"]}},
    # 11. Gevormd zonder woonfunctie: hoort bij de niet-woningen en niet bij
    #     de pijplijn, want die gaat over woningen. Op 11 oktober waren dit
    #     de 70 die het verschil waren tussen 2.238 en 2.168.
    {"id": "v11", "properties": {
        "postcode": "6511AA", "status": "Verblijfsobject gevormd",
        "gebruiksdoel": "winkelfunctie", "oppervlakte": 95,
        "openbare_ruimte_naam": "Broerstraat", "huisnummer": 7,
        "identificatie": "0268010000000011", "pand.href": []}},
]


def proef_tegels():
    """
    De tegelindeling en het delen nameten, zonder netwerk.

    Dit is de code die op 10 oktober nieuw was omdat PDOK in één doos een
    eigen timeout gaf. Wat hier misgaat is niet te zien aan een foutmelding
    maar aan een gat in de dekking: een tegel die wordt overgeslagen of een
    strook tussen twee tegels waar niemand kijkt.
    """
    global _pagina
    afw = []

    # 1. HET RASTER DEKT DE DOOS PRECIES. Geen gaten en geen overlap.
    tegels = _raster(DOOS, TEGELS)
    if len(tegels) != TEGELS * TEGELS:
        afw.append(f"{len(tegels)} tegels in plaats van {TEGELS ** 2}")
    x1, y1, x2, y2 = [float(v) for v in DOOS.split(",")]
    oppervlak = sum((float(t.split(",")[2]) - float(t.split(",")[0]))
                    * (float(t.split(",")[3]) - float(t.split(",")[1]))
                    for t in tegels)
    if abs(oppervlak - (x2 - x1) * (y2 - y1)) > 1e-9:
        afw.append(f"de tegels dekken {oppervlak} en de doos "
                   f"{(x2 - x1) * (y2 - y1)}; dan zit er een gat of overlap "
                   f"in en vallen er adressen buiten elke tegel")
    hoeken = [[float(v) for v in t.split(",")] for t in tegels]
    if (abs(min(h[0] for h in hoeken) - x1) > 1e-9
            or abs(max(h[2] for h in hoeken) - x2) > 1e-9
            or abs(min(h[1] for h in hoeken) - y1) > 1e-9
            or abs(max(h[3] for h in hoeken) - y2) > 1e-9):
        afw.append("de buitenrand van het raster is niet die van de doos")

    # 2. DELEN DEKT DE OUDERTEGEL PRECIES.
    ouder = "5.0,51.0,6.0,52.0"
    vier = _deel(ouder)
    if len(vier) != 4:
        afw.append(f"_deel gaf {len(vier)} dozen")
    opp4 = sum((float(t.split(",")[2]) - float(t.split(",")[0]))
               * (float(t.split(",")[3]) - float(t.split(",")[1]))
               for t in vier)
    if abs(opp4 - 1.0) > 1e-9:
        afw.append(f"vier delen dekken {opp4} in plaats van 1,0")

    echt_pagina = _pagina
    stuk = {"doos": tegels[5]}

    def nep_pagina(url, params):
        """Elke tegel levert één object, behalve één tegel die PDOK's
        eigen timeout geeft zolang hij zo groot is."""
        doos = (params or {}).get("bbox") or ""
        if doos == stuk["doos"]:
            return {}, ("HTTP 500: Internal Server Error failed to retrieve "
                        "feature collection verblijfsobject: querying the "
                        "features took too long (timeout encountered)")
        return {"features": [{"id": doos, "properties": {}}], "links": []}, ""

    try:
        _pagina = nep_pagina
        gezien = []
        stand = doorloop("verblijfsobject", 30,
                         lambda ks: gezien.extend(ks))
    finally:
        _pagina = echt_pagina

    # 3. EEN MISLUKTE TEGEL WORDT GEDEELD EN DE RONDE KOMT ALSNOG ROND.
    if not stand["ronde_af"]:
        afw.append(f"de ronde kwam niet rond terwijl alleen één tegel "
                   f"haperde: {stand['fout']}")
    if stand["tegels_gedeeld"] != 1:
        afw.append(f"{stand['tegels_gedeeld']} delingen in plaats van 1")
    if stand["tegels"] != TEGELS * TEGELS - 1 + 4:
        afw.append(f"{stand['tegels']} tegels gelukt in plaats van "
                   f"{TEGELS ** 2 + 3}")
    # De vier kleintjes samen moeten precies de mislukte tegel dekken, dus
    # geen enkel adres in die tegel mag ongezien blijven.
    if len(gezien) != TEGELS * TEGELS - 1 + 4:
        afw.append(f"{len(gezien)} objecten gezien in plaats van "
                   f"{TEGELS ** 2 + 3}")

    # 4. EEN TEGEL DIE MISLUKT NA AL PAGINA'S TE HEBBEN AFGELEVERD. Dit is
    # wat op 10 oktober werkelijk gebeurde: pagina 123 van 165, dus ná
    # aflevering. De tegel wordt gedeeld en de al afgeleverde objecten komen
    # in de kleintjes nog een keer voorbij, dus hier hangt aan of de dedup op
    # de juiste plek staat. Stond hij verderop, dan liepen de statussen, de
    # historie en nog_gevormd dubbel op, en nog_gevormd gedeeld door
    # woningen_gezien is een drempel in het gezondheidsrapport.
    laat = {"doos": tegels[5], "pagina": 0}
    # De kinderen van de mislukte tegel leveren hetzelfde object als de ouder
    # al had afgeleverd. Zo gaat het in het echt ook: een kindtegel ligt in de
    # ouder, dus de objecten die de ouder al gaf komen opnieuw voorbij. Stond
    # hier een nieuw object per kind, dan meette deze proef de dedup niet, en
    # dat was de eerste versie ervan.
    kinderen = set(_deel(tegels[5]))

    def nep_laat(url, params):
        doos = (params or {}).get("bbox") or ""
        if doos in kinderen:
            return {"features": [{"id": doos, "properties": {
                "identificatie": "vbo-in-de-stukke-tegel",
                "postcode": "6521AB",
                "status": "Verblijfsobject in gebruik",
                "gebruiksdoel": "woonfunctie", "oppervlakte": 60,
                "openbare_ruimte_naam": "Bottelstraat", "huisnummer": 99,
                "pand.href": []}}], "links": []}, ""
        if doos == laat["doos"]:
            laat["pagina"] += 1
            if laat["pagina"] == 1:
                # Eén object afleveren, met een next-link zodat er een tweede
                # pagina komt.
                return {"features": [{"id": doos, "properties": {
                    "identificatie": "vbo-in-de-stukke-tegel",
                    "postcode": "6521AB", "status": "Verblijfsobject in "
                    "gebruik", "gebruiksdoel": "woonfunctie",
                    "oppervlakte": 60, "openbare_ruimte_naam": "Bottelstraat",
                    "huisnummer": 99, "pand.href": []}}],
                        "links": [{"rel": "next", "href": "verder"}]}, ""
            return {}, ("HTTP 500: querying the features took too long "
                        "(timeout encountered)")
        if url == "verder":
            return {}, "HTTP 500: querying the features took too long"
        return {"features": [{"id": doos, "properties": {
            "identificatie": f"vbo-{doos}", "postcode": "6521AB",
            "status": "Verblijfsobject in gebruik",
            "gebruiksdoel": "woonfunctie", "oppervlakte": 70,
            "openbare_ruimte_naam": "Bottelstraat", "huisnummer": 1,
            "pand.href": []}}], "links": []}, ""

    try:
        _pagina = nep_laat
        voorraad_laat = {}
        uit_laat = fase_bag(voorraad_laat, {"6521AB": ("Bottendaal",)}, 30, {},
                            signalen=set())
    finally:
        _pagina = echt_pagina
    if not uit_laat.get("ronde_ronde_af"):
        afw.append(f"een tegel die laat mislukt bracht de ronde niet rond: "
                   f"{uit_laat.get('laatste_fout')}")
    # De vier kinderen leveren alle vier het object dat de ouder al had
    # afgeleverd, dus dat hoort vier keer als opnieuw_gezien te worden
    # overgeslagen en één keer te zijn geteld.
    if uit_laat.get("opnieuw_gezien") != 4:
        afw.append(f"opnieuw_gezien is {uit_laat.get('opnieuw_gezien')} in "
                   f"plaats van 4; dan meet deze proef de dedup niet of staat "
                   f"de dedup op de verkeerde plek")
    if uit_laat.get("woningen_gezien") != 16:
        afw.append(f"woningen_gezien is {uit_laat.get('woningen_gezien')} in "
                   f"plaats van 16; elk object hoort één keer te tellen, ook "
                   f"na een deling")
    # En de tellers die vóór de dedup stonden mogen ook niet dubbel lopen.
    if (uit_laat.get("statussen") or {}).get(
            "Verblijfsobject in gebruik") != 16:
        afw.append(f"de statustelling is "
                   f"{(uit_laat.get('statussen') or {}).get('Verblijfsobject in gebruik')} "
                   f"in plaats van 16; dan staat de dedup achter de "
                   f"statustelling en loopt die dubbel bij een deling")

    # 5. EEN TEGEL DIE BLIJFT MISLUKKEN STOPT DE RONDE MET EEN REDEN.
    def altijd_stuk(url, params):
        return {}, "HTTP 500: querying the features took too long"

    try:
        _pagina = altijd_stuk
        hard = doorloop("verblijfsobject", 30, lambda ks: None)
    finally:
        _pagina = echt_pagina
    if hard["ronde_af"]:
        afw.append("een tegel die altijd mislukt leverde toch een afgeronde "
                   "ronde op; dan wordt er verwijderd op een halve meting")
    if "delingen" not in (hard["fout"] or ""):
        afw.append(f"de reden noemt het delen niet: {hard['fout']!r}")

    return afw


def proef_labels():
    """
    De wachtrij van de labelfase nameten, zonder één aanroep.

    WAAROM JUIST DEZE. De labelfase vroeg op 10 oktober 818 adressen op en
    vond nul labels, en dat zag eruit als een eigenschap van de
    woningvoorraad in plaats van als een kapotte aanroep. Die aanroep staat
    nu in eponline.py met zijn eigen proef. Wat hier wordt gemeten is het
    stuk dat daar niet zit: welk adres opnieuw aan de beurt komt.

    Dat is de helft die geld kost. Een fout die niet wordt opgeschreven laat
    het adres vooraan in de wachtrij staan, en dan kost het elke ronde
    opnieuw een aanroep. Vijftien van de 818 deden dat, elke run.
    """
    # EP_API_KEY wordt bij import gelezen en niet bij aanroep, dus de
    # omgevingsvariabele zetten helpt hier niet: de modulewaarde moet om.
    # Dat die constante bij import wordt vastgelegd is zelf een val, want
    # een sleutel die later in de omgeving komt wordt niet meer gezien. Hier
    # alleen omgezet voor de duur van de proef.
    global haal_label, EP_API_KEY
    afw = []

    def plek_van(rij, naam):
        return rij.index(naam) if naam in rij else 99
    echte_haler, echte_sleutel = haal_label, EP_API_KEY
    EP_API_KEY = "proef"
    antwoorden = {}

    gevraagde = []

    def nep(rec):
        gevraagde.append(rec.get("adres"))
        return antwoorden.get(rec.get("adres"), ({}, "", True))

    def voorraadje():
        return {"adressen": {
            "v1": {"adres": "Gevonden 1", "postcode": "6500AA", "vbo": "v1"},
            "v2": {"adres": "Prive 2", "postcode": "6500AA", "vbo": "v2"},
            "v3": {"adres": "Definitief 3", "postcode": "6500AA", "vbo": "v3"},
            "v4": {"adres": "Tijdelijk 4", "postcode": "6500AA", "vbo": "v4"},
            "v5": {"adres": "Oude methode 5", "postcode": "6500AA",
                   "vbo": "v5"},
            # AL EEN LABEL, GEEN METHODE, GEZIEN VOOR DE GRENS. Die komt een
            # keer opnieuw aan de beurt. v7 is hetzelfde geval maar EP-Online
            # geeft daar geen Berekeningstype: die moet NA die ene vraag
            # ophouden met terugkomen, anders vraagt hij hem voor altijd.
            "v6": {"adres": "Inhalen 6", "postcode": "6500AA", "vbo": "v6",
                   "label": "E", "label_gezien": "2026-10-01"},
            "v7": {"adres": "Blijft onbekend 7", "postcode": "6500AA",
                   "vbo": "v7", "label": "F", "label_gezien": "2026-10-01"},
            # GEEN LABEL, GEVRAAGD MET DE KAPOTTE AANROEP. v8 komt een keer
            # terug; v9 kreeg "geen label" na de reparatie en blijft liggen.
            "v8": {"adres": "Stuk gevraagd 8", "postcode": "6500AA",
                   "vbo": "v8", "label_gezien": "2026-10-10"},
            "v9": {"adres": "Goed gevraagd 9", "postcode": "6500AA",
                   "vbo": "v9", "label_gezien": "2026-10-13"},
        }}

    try:
        haal_label = nep
        antwoorden = {
            "Gevonden 1": ({"label": "C", "prive": False,
                            "registratiedatum": "2025-03-04",
                            "nta8800": True}, "", True),
            "Prive 2": ({"label": None, "prive": True}, "", True),
            "Inhalen 6": ({"label": "E", "prive": False,
                           "registratiedatum": "2019-06-01",
                           "nta8800": False}, "", True),
            # Een antwoord zonder rekenmethode: nta8800 is None en niet False.
            "Blijft onbekend 7": ({"label": "F", "prive": False,
                                   "registratiedatum": "2019-06-01",
                                   "nta8800": None}, "", True),
            "Oude methode 5": ({"label": "D", "prive": False,
                                "registratiedatum": "2017-03-15",
                                "nta8800": False}, "", True),
            "Definitief 3": (None, "HTTP 400", True),
            "Tijdelijk 4": (None, "netwerk: verbinding weg", False),
            "Stuk gevraagd 8": ({"label": "B", "prive": False,
                                 "registratiedatum": "2021-05-01",
                                 "nta8800": True}, "", True),
        }
        v = voorraadje()
        uit = fase_labels(v, 5)
        ad = v["adressen"]
        if uit.get("gevraagd") != 8:
            afw.append(f"labelfase vroeg {uit.get('gevraagd')} adressen op in "
                       f"plaats van 8")
        # "GEEN LABEL" VAN DE KAPOTTE AANROEP WORDT EEN KEER OVERGEVRAAGD, en
        # "geen label" van na de reparatie niet. Op 14 oktober stonden er
        # 1.097 van de eerste soort een jaar lang vast.
        if "Stuk gevraagd 8" not in gevraagde:
            afw.append("een adres dat 'geen label' kreeg van de kapotte "
                       "aanroep wordt niet opnieuw gevraagd")
        if "Goed gevraagd 9" in gevraagde:
            afw.append("een adres dat na de reparatie 'geen label' kreeg wordt "
                       "toch opnieuw gevraagd; dan is de grens geen grens")
        if ad["v8"].get("label") != "B":
            afw.append(f"het overgevraagde label is niet bewaard: "
                       f"{ad['v8'].get('label')!r}")
        if uit.get("herhaald_label_gevonden") != 1:
            afw.append(f"de stand meldt {uit.get('herhaald_label_gevonden')} "
                       f"overgevraagde labels in plaats van 1")
        if "Stuk gevraagd 8" in gevraagde and plek_van(gevraagde, "Stuk gevraagd 8") \
                > plek_van(gevraagde, "Gevonden 1"):
            afw.append("de stuk gevraagde adressen staan achter de nieuwe in "
                       "de wachtrij; dan draait de inhaalslag pas als de staart "
                       "leeg is")
        # EN DE INHAALSLAG GAAT VOOROP. Stond hij achteraan, dan kwam hij
        # pas aan de beurt als de 17.321 nooit gevraagde adressen klaar
        # waren: negentien rondes. Een begrensde inhaalslag achter een lange
        # staart draait nooit.
        plek = {a: i for i, a in enumerate(gevraagde)}
        laatste_inhaal = max(plek.get("Inhalen 6", -1),
                             plek.get("Blijft onbekend 7", -1))
        eerste_nieuw = min(plek.get("Gevonden 1", 99),
                           plek.get("Definitief 3", 99))
        if laatste_inhaal > eerste_nieuw:
            afw.append(f"de inhaalslag staat achter de nieuwe adressen in de "
                       f"wachtrij ({gevraagde}); dan draait hij pas als de "
                       f"staart leeg is")

        # DE INHAALSLAG OP DE REKENMETHODE. Een label zonder methode komt
        # anders pas aan de beurt als het verloopt, en dat is een jaar met
        # een letter waarvan de grondslag niet te zien is.
        if ad["v6"].get("label_nta8800") is not False:
            afw.append(f"de methode is niet ingehaald: "
                       f"{ad['v6'].get('label_nta8800')!r}")
        # HET GEMETEN TEMPO HOORT IN DE STAND, want daarmee is uit te rekenen
        # hoeveel rondes de rest nog kost zonder iets te schatten.
        if not uit.get("aanroepen_per_minuut"):
            afw.append("de stand meldt geen gemeten tempo; dan is het aantal "
                       "rondes dat nog nodig is alleen te schatten")
        elif uit["aanroepen_per_minuut"] <= 0:
            afw.append(f"het gemeten tempo is {uit['aanroepen_per_minuut']}")
        if uit.get("methode_ingehaald") != 1:
            afw.append(f"de stand meldt {uit.get('methode_ingehaald')} "
                       f"ingehaalde methodes in plaats van 1")
        if uit.get("methode_blijft_onbekend") != 1:
            afw.append(f"de stand meldt {uit.get('methode_blijft_onbekend')} "
                       f"keer dat de methode wegblijft in plaats van 1")
        # EEN INGEHAALD LABEL IS GEEN NIEUW LABEL. Anders loopt die teller op
        # zonder dat er een woning bij komt.
        if uit.get("label_gevonden") != 2:
            afw.append(f"label_gevonden is {uit.get('label_gevonden')} in "
                       f"plaats van 2; een ingehaald label telt mee als nieuw")
        if uit.get("geen_label_bekend") != 0:
            afw.append(f"geen_label_bekend is {uit.get('geen_label_bekend')} "
                       f"in plaats van 0; een inhaalvraag die niets oplevert "
                       f"telt mee als een adres zonder label")
        if ad["v1"].get("label") != "C":
            afw.append(f"gevonden label niet bewaard: {ad['v1'].get('label')!r}")
        if ad["v1"].get("label_datum") != "2025-03-04":
            afw.append(f"registratiedatum niet bewaard: "
                       f"{ad['v1'].get('label_datum')!r}")
        # DE GRONDSLAG ONDER DE LETTER. Twee labels in hetzelfde pand kunnen
        # met twee rekenmethodes zijn bepaald; zonder dit veld vergelijkt de
        # brief een D van 2017 met een C van 2026 alsof dat hetzelfde is.
        if ad["v1"].get("label_nta8800") is not True:
            afw.append(f"de rekenmethode wordt niet bewaard: "
                       f"{ad['v1'].get('label_nta8800')!r}")
        if ad["v5"].get("label_nta8800") is not False:
            afw.append(f"een label volgens de oude methode wordt niet als "
                       f"zodanig bewaard: {ad['v5'].get('label_nta8800')!r}")
        # Een privelabel is een antwoord: er IS een label, het is niet
        # openbaar. Als "niet bekend" opschrijven betekent volgend jaar
        # dezelfde vraag en hetzelfde antwoord.
        if not ad["v2"].get("label_prive"):
            afw.append("een privelabel wordt niet als prive opgeschreven")
        if uit.get("label_prive") != 1:
            afw.append(f"de stand telt {uit.get('label_prive')} prive in "
                       f"plaats van 1")
        if uit.get("geen_label_bekend") != 0:
            afw.append(f"een privelabel telt mee als 'geen label bekend' "
                       f"({uit.get('geen_label_bekend')})")
        # Een definitieve weigering is een antwoord over dit adres.
        if not ad["v3"].get("label_gezien"):
            afw.append("een definitieve fout wordt niet opgeschreven, dus dit "
                       "adres komt elke ronde opnieuw vooraan")
        if ad["v3"].get("label_fout") != "HTTP 400":
            afw.append("de reden van een definitieve fout wordt niet bewaard")
        # Een tijdelijke fout is van ons en niet van het adres.
        if ad["v4"].get("label_gezien"):
            afw.append("een tijdelijke fout wordt opgeschreven als gevraagd, "
                       "en dan wordt dit adres een jaar lang niet opnieuw "
                       "geprobeerd")

        # De tweede ronde: alleen de tijdelijke fout hoort terug te komen.
        tweede = fase_labels(v, 5)
        if tweede.get("gevraagd") != 1:
            afw.append(f"tweede ronde vraagt {tweede.get('gevraagd')} adressen "
                       f"in plaats van alleen het adres met de tijdelijke fout")
        # EN DE INHAALSLAG EINDIGT. Dit is de controle die het verschil maakt
        # tussen een eenmalige inhaalslag en een adres dat elke ronde opnieuw
        # een aanroep kost. v7 heeft nog steeds geen methode, maar is vandaag
        # gezien, en de grens is de datum en niet het veld.
        if tweede.get("methode_ingehaald") or tweede.get(
                "methode_blijft_onbekend"):
            afw.append("de inhaalslag op de rekenmethode komt in de tweede "
                       "ronde terug; dan vraagt hij dat adres voor altijd")
        if tweede.get("herhaald_nog_te_vragen") != 0:
            afw.append(f"na de inhaalslag staan er nog "
                       f"{tweede.get('herhaald_nog_te_vragen')} stuk gevraagde "
                       f"adressen in de rij")
        if tweede.get("methode_nog_in_te_halen") != 0:
            afw.append(f"na de inhaalslag staan er nog "
                       f"{tweede.get('methode_nog_in_te_halen')} in de rij")

        # Een geweigerde sleutel of een 429 hoort de ronde af te breken, want
        # doorgaan kost alleen quotum.
        for fout in ("HTTP 429", "HTTP 401"):
            # ALLE ADRESSEN, OOK DE NIEUWE. Deze rij stond met vier namen
            # erin, en toen er twee records bij kwamen gaven die het
            # standaardantwoord in plaats van de fout. Dan werden er drie
            # adressen gevraagd en leek het of de fase niet stopte. Een
            # proefrij met namen erin veroudert net zo stil als een lijstje
            # velden in de code, en dat is dezelfde fout als vannacht.
            antwoorden = {r["adres"]: (None, fout, False)
                          for r in voorraadje()["adressen"].values()}
            v2 = voorraadje()
            u2 = fase_labels(v2, 5)
            if u2.get("gevraagd") != 1:
                afw.append(f"bij {fout} vroeg de fase {u2.get('gevraagd')} "
                           f"adressen op; hij hoort na de eerste te stoppen")

        # Zonder sleutel gebeurt er niets, en dat hoort het te zeggen.
        EP_API_KEY = ""
        u3 = fase_labels(voorraadje(), 5)
        if not u3.get("overgeslagen"):
            afw.append("zonder EP_API_KEY meldt de fase niet dat hij is "
                       "overgeslagen")
    finally:
        haal_label = echte_haler
        EP_API_KEY = echte_sleutel
    return afw


def proef():
    """
    De zeef nameten op de echte vorm van een PDOK-antwoord, zonder netwerk.

    Wat hier wordt getoetst is precies wat vandaag vier keer stil misging: dat
    een aanname over de vorm van een veld een lege voorraad oplevert zonder
    dat er iets faalt.
    """
    global doorloop
    echt = doorloop

    def nep(collectie, budget, per_pagina):
        per_pagina(PROEF_KENMERKEN)
        return {"paginas": 1, "objecten": len(PROEF_KENMERKEN),
                "seconden": 0.0, "ronde_af": True, "fout": ""}

    def nep_panden(collectie, budget, per_pagina):
        per_pagina([
            # Met status, want die scheidt nieuwbouw van transformatie en die
            # werd hier weggegooid. Twee verschillende, zodat een object in
            # beide panden aantoonbaar twee statussen heeft.
            # Met bouwjaar, want dat veld stond in velden_in_antwoord en
            # werd weggegooid. Twee verschillende jaren, zodat bij een object
            # in beide panden aantoonbaar het OUDSTE wordt gekozen.
            {"id": "uuid-een", "properties": {
                "identificatie": "0268100000000011",
                "status": "Pand in gebruik", "bouwjaar": 1912}},
            {"id": "uuid-twee", "properties": {
                "identificatie": "0268100000000022",
                "status": "Bouw gestart", "bouwjaar": 2025}},
            # Zonder identificatie: mag de kaart niet vervuilen.
            {"id": "uuid-drie", "properties": {}},
        ])
        return {"paginas": 1, "objecten": 3, "seconden": 0.0,
                "ronde_af": True, "fout": ""}

    doorloop = nep
    try:
        voorraad = {}
        pcs = {"6521AB": ("Bottendaal",),
               "6511AA": ("Benedenstad", "Stadscentrum")}
        # EERST DE PANDFASE, ZOALS MAIN DAT OOK DOET, en de kaarten uit
        # fase_panden zelf halen. Hier stonden de pandstatussen als een eigen
        # lijstje in de proef, en dan toetst de proef zijn eigen aanname in
        # plaats van wat fase_panden werkelijk teruggeeft. Precies de fout
        # waarvan deze week drie keer bleek hoe stil hij is.
        doorloop = nep_panden
        pandkaart, pandstand = fase_panden(1)
        pandstatussen = pandstand.pop("_status_per_pand", {})
        pandbouwjaren = pandstand.pop("_bouwjaar_per_pand", {})
        doorloop = nep
        kaart = dict(pandkaart)
        # signalen=set() EN NIET WEGLATEN. Laat je dit leeg, dan leest
        # fase_bag de echte pandgeschiedenis.json en hangen de tellingen in
        # deze proef aan gegevens van vandaag. Het signaalgeval heeft zijn
        # eigen blok hieronder, met zijn eigen verzameling.
        uit = fase_bag(voorraad, pcs, 1, kaart, pandstatussen,
                       pandbouwjaren, signalen=set())
        # WAT FASE 2 HEEFT OPGESCHREVEN, MOET EEN OBJECTRONDE OVERLEVEN.
        # Dit is de fout van vannacht: de objectronde bouwt elk record
        # opnieuw op en nam uit het oude record alleen label, label_datum en
        # label_gezien over. label_nta8800 was op 12 oktober toegevoegd en
        # niet aan dat lijstje, dus de ronde gooide de rekenmethode van alle
        # 698 bestaande labels weg, en ook label_prive en label_fout. Het
        # bestand zag er daarna normaal uit: 698 labels zonder grondslag.
        for _s, _r in (voorraad.get("adressen") or {}).items():
            _r["label"] = "C"
            _r["label_datum"] = "2025-03-04"
            _r["label_gezien"] = "2026-10-11"
            _r["label_nta8800"] = True
            _r["label_prive"] = False
            _r["label_fout"] = ""
            break

        # TWEEDE RONDE OP DEZELFDE GEGEVENS. Hieraan hangt of het bestand van
        # ruim vijf megabyte elke dag ongewijzigd blijft of elke dag helemaal
        # verandert. Dat verschil is in de uitkomst niet te zien en alleen
        # hier te meten.
        voorraad_na = json.loads(json.dumps(voorraad))
        tweede = fase_bag(voorraad_na, pcs, 1, kaart,
                          pandstatussen, pandbouwjaren, signalen=set())

        # DERDE RONDE WAARIN DINGEN VERDWIJNEN EN VAN SOORT WISSELEN. Hier
        # hangt aan of het aantal in de brief langzaam te hoog oploopt.
        voorraad_weg = json.loads(json.dumps(voorraad))
        korter = [k for k in PROEF_KENMERKEN if k["id"] != "v5"]
        # En de winkel op Broerstraat 3 wordt een woning.
        werd_woning = json.loads(json.dumps(
            [k for k in PROEF_KENMERKEN if k["id"] == "v4"][0]))
        werd_woning["properties"]["gebruiksdoel"] = "woonfunctie"
        korter = [k for k in korter if k["id"] != "v4"] + [werd_woning]

        def nep_korter(collectie, budget, per_pagina):
            per_pagina(korter)
            return {"paginas": 1, "objecten": len(korter), "seconden": 0.0,
                    "ronde_af": True, "fout": ""}

        doorloop = nep_korter
        derde = fase_bag(voorraad_weg, pcs, 1, kaart, signalen=set())

        # VIERDE RONDE DIE HALVERWEGE AFBREEKT: dan mag er niets verdwijnen.
        voorraad_half = json.loads(json.dumps(voorraad))

        def nep_half(collectie, budget, per_pagina):
            per_pagina(korter)
            return {"paginas": 1, "objecten": len(korter), "seconden": 0.0,
                    "ronde_af": False, "fout": "tijdbudget om"}

        doorloop = nep_half
        vierde = fase_bag(voorraad_half, pcs, 1, kaart, signalen=set())

    finally:
        doorloop = echt

    adressen = voorraad.get("adressen") or {}
    anders = voorraad.get("niet_woningen") or {}
    pijplijn = voorraad.get("pijplijn") or {}
    verwacht = {
        "woningen_gezien": 4,          # 1, 5, 8 en 12
        "niet_woonfunctie": 2,         # 4 en 11 (gevormde winkel)
        "historie_overgeslagen": 2,    # 2 en 3
        "buiten_de_ring": 1,           # 6
        "zonder_adres": 1,             # 7
        "zonder_pandsleutel": 1,       # 8
        "objecten_met_pand": 4,        # 1, 4, 5 en 12
        "postcodes_gedaan": 2,
        "postcodes_totaal": 2,
        "postcodes_nijmegen": 2,
        "postcodes_leeg": 0,
        "postcodes_leeg_nijmegen": 0,
        "adressen_nieuw": 4,
        "adressen_verwijderd": 0,
        "van_soort_gewisseld": 0,
        "niet_woningen_bewaard": 2,
        # DE PIJPLIJN APART. 9 en 10 zijn woningen met status gevormd: die
        # horen hier en niet bij woningen_gezien, want het CBS rekent ze tot
        # de pijplijn en niet tot de voorraad. 11 is een gevormde winkel en
        # hoort bij de niet-woningen, want de pijplijn gaat over woningen.
        "pijplijn_bewaard": 2,         # 9 en 10
        "pijplijn_gezien": 2,
        "opgeleverd": 0,
        "terug_in_de_pijplijn": 0,
    }
    afwijkingen = []
    for veld, moet in verwacht.items():
        if uit.get(veld) != moet:
            afwijkingen.append(f"{veld}: {uit.get(veld)} in plaats van {moet}")

    # EN DE LABELVELDEN NA DE TWEEDE RONDE. Alles wat fase 2 schrijft heet
    # label-iets en moet er na een objectronde nog staan, met dezelfde
    # waarde. Het gaat niet om deze vier namen maar om de regel: een nieuw
    # labelveld hoort deze controle automatisch te halen.
    na = (voorraad_na.get("adressen") or {})
    bewaard = [r for r in na.values() if r.get("label")]
    if not bewaard:
        afwijkingen.append("na een tweede objectronde staat er geen enkel "
                           "label meer; fase 2 schrijft dan voor niets")
    else:
        was = {"label": "C", "label_datum": "2025-03-04",
               "label_gezien": "2026-10-11", "label_nta8800": True,
               "label_prive": False, "label_fout": ""}
        for veld, moet in was.items():
            if bewaard[0].get(veld) != moet:
                afwijkingen.append(
                    f"een objectronde gooit {veld} weg: "
                    f"{bewaard[0].get(veld)!r} in plaats van {moet!r}")

    # EEN OBJECT IN TWEE PANDEN HOUDT ZE BEIDE. Hier stond een break op de
    # eerste sleutel die oploste; welk pand je te pakken had, hing af van de
    # volgorde in het antwoord. Dat raakt alles wat op pand joint, en sinds
    # vandaag ook de pandstatus die nieuwbouw van transformatie scheidt.
    tweepands = adressen.get("0268010000000012") or {}
    if tweepands.get("panden") != ["0268100000000011", "0268100000000022"]:
        afwijkingen.append(f"een object in twee panden houdt "
                           f"{tweepands.get('panden')} over")
    if tweepands.get("pand") != "0268100000000011":
        afwijkingen.append(f"het veld pand is {tweepands.get('pand')!r} en "
                           f"niet de eerste; dan breekt elke bestaande lezer")
    if uit.get("objecten_in_meer_panden") != 1:
        afwijkingen.append(f"de ronde telt "
                           f"{uit.get('objecten_in_meer_panden')} objecten in "
                           f"meer panden in plaats van 1")
    # HET BOUWJAAR VAN HET PAND, EN BIJ TWEE PANDEN HET OUDSTE. Dit veld
    # stond al in het antwoord van PDOK en werd weggegooid. Het beslist de
    # groep die de pandstatus niet splitst: een gevormd object in een pand
    # dat al in gebruik is, is een splitsing van bestaande voorraad bij een
    # pand van 1912 en bijna opgeleverde nieuwbouw bij een pand van 2025.
    if tweepands.get("pand_bouwjaar") != 1912:
        afwijkingen.append(f"bij twee panden wordt niet het oudste bouwjaar "
                           f"genomen: {tweepands.get('pand_bouwjaar')!r} in "
                           f"plaats van 1912")
    if tweepands.get("pand_bouwjaren") != [1912, 2025]:
        afwijkingen.append(f"beide bouwjaren staan niet in het record: "
                           f"{tweepands.get('pand_bouwjaren')!r}")
    een_pand = adressen.get("0268010000000001") or {}
    if een_pand.get("pand_bouwjaar") != 1912:
        afwijkingen.append(f"het bouwjaar van het pand wordt niet bewaard: "
                           f"{een_pand.get('pand_bouwjaar')!r}")
    if "pand_bouwjaren" in een_pand:
        afwijkingen.append("bij een object in een pand staat pand_bouwjaren "
                           "er toch bij; dat veld hoort alleen bij verschil")
    if pandstand.get("met_bouwjaar") != 2:
        afwijkingen.append(f"de pandfase meldt {pandstand.get('met_bouwjaar')}"
                           f" panden met een bouwjaar in plaats van 2")
    # Twee panden met een verschillende status: dan is "de" pandstatus geen
    # enkel getal, en dat hoort in het record te staan in plaats van
    # weggewerkt te worden.
    if tweepands.get("pand_status") != "Pand in gebruik":
        afwijkingen.append(f"pand_status is {tweepands.get('pand_status')!r}")
    if tweepands.get("pand_statussen") != ["Pand in gebruik", "Bouw gestart"]:
        afwijkingen.append(f"pand_statussen is "
                           f"{tweepands.get('pand_statussen')!r}; bij twee "
                           f"verschillende statussen horen ze er beide te "
                           f"staan")
    # En een object in EEN pand hoort geen lijst te krijgen: dat zou bij
    # 22.000 records een megabyte aan niets zijn.
    een = adressen.get("0268010000000001") or {}
    if "panden" in een:
        afwijkingen.append("een object in een pand krijgt toch een lijst")
    if "pand_statussen" in een:
        afwijkingen.append("een object in een pand krijgt toch een "
                           "statuslijst")

    if set(pijplijn) != {"0268010000000009", "0268010000000010"}:
        afwijkingen.append(f"de pijplijn houdt de verkeerde objecten: "
                           f"{sorted(pijplijn)}")
    if set(adressen) & set(pijplijn):
        afwijkingen.append("een object staat in de voorraad EN in de "
                           "pijplijn; dan telt die woning twee keer")

    # DE OPLEVERING. Dit is het enige moment waarop de voorraad werkelijk
    # groeit, en daarom het stuk dat gemeten moet worden: het object verhuist
    # van de pijplijn naar de voorraad, het oude record blijft niet staan, en
    # de ronde meldt het. Zonder deze controle zou een oplevering een nieuw
    # record lijken naast het oude, en stond dezelfde woning twee keer in de
    # ring.
    klaar = [dict(k, properties=dict(k["properties"])) for k in PROEF_KENMERKEN]
    for k in klaar:
        if k["id"] == "v9":
            k["properties"]["status"] = "Verblijfsobject in gebruik"

    def nep_klaar(collectie, budget, per_pagina):
        per_pagina(klaar)
        return {"paginas": 1, "objecten": len(klaar), "seconden": 0.0,
                "ronde_af": True, "fout": ""}

    # OP EEN KOPIE EN NIET OP DE GEDEELDE VOORRAAD. Een eerste versie draaide
    # deze ronde op hetzelfde dict dat de controles hieronder lezen, en toen
    # meldde de proef dat de sleutels fout waren en dat twee gelijke rondes
    # een ander bestand opleveren. Beide waren niet waar: mijn eigen test had
    # de staat vervuild. Een controle die de gegevens verandert die de
    # volgende controle leest, meet de vorige controle.
    import copy as _copy
    voorraad_klaar = _copy.deepcopy(voorraad)
    echt2, globals()["doorloop"] = doorloop, nep_klaar
    try:
        na = fase_bag(voorraad_klaar, pcs, 1, kaart,
                      pandstatussen, signalen=set())
    finally:
        globals()["doorloop"] = echt2
    pijplijn_na = voorraad_klaar.get("pijplijn") or {}
    adressen_na = voorraad_klaar.get("adressen") or {}
    if na.get("opgeleverd") != 1:
        afwijkingen.append(f"een gereedmelding levert {na.get('opgeleverd')} "
                           f"opleveringen op in plaats van 1")
    if na.get("opgeleverde_adressen") != ["Bottelstraat 20"]:
        afwijkingen.append(f"de opgeleverde adressen zijn "
                           f"{na.get('opgeleverde_adressen')}")
    if "0268010000000009" in pijplijn_na:
        afwijkingen.append("het opgeleverde object staat nog in de pijplijn, "
                           "dus die woning telt twee keer")
    if "0268010000000009" not in adressen_na:
        afwijkingen.append("het opgeleverde object staat niet in de voorraad")
    if na.get("woningen_gezien") != 5:
        afwijkingen.append(f"na de oplevering telt de ronde "
                           f"{na.get('woningen_gezien')} woningen in plaats "
                           f"van 5")
    if na.get("pijplijn_bewaard") != 1:
        afwijkingen.append(f"na de oplevering houdt de pijplijn "
                           f"{na.get('pijplijn_bewaard')} over in plaats van 1")
    if na.get("van_soort_gewisseld"):
        afwijkingen.append("een oplevering wordt geteld als van soort "
                           "gewisseld; dan is in het rapport niet te zien dat "
                           "er een woning is opgeleverd")

    # DE SLEUTEL IS DE VBO-IDENTIFICATIE. Met de adressleutel botsten in de
    # echte ring 93 van de 22.096 objecten op elkaar.
    if set(adressen) != {"0268010000000001", "0268010000000005",
                         "0268010000000008", "0268010000000012"}:
        afwijkingen.append(f"adressen zijn niet op vbo gesleuteld: "
                           f"{sorted(adressen)}")
    # En een botsende adressleutel mag geen record meer opslokken.
    bots = [
        {"id": "b1", "properties": {
            "postcode": "6521AB", "status": "Verblijfsobject in gebruik",
            "gebruiksdoel": "woonfunctie", "oppervlakte": 40,
            "openbare_ruimte_naam": "Bottelstraat", "huisnummer": 1,
            "toevoeging": "2", "identificatie": "0268010000000101",
            "pand.href": []}},
        {"id": "b2", "properties": {
            "postcode": "6521AB", "status": "Verblijfsobject in gebruik",
            "gebruiksdoel": "woonfunctie", "oppervlakte": 90,
            "openbare_ruimte_naam": "Bottelstraat", "huisnummer": 12,
            "identificatie": "0268010000000102", "pand.href": []}},
    ]
    # HET VELD SLEUTEL IS DE SLEUTEL VAN DE REST VAN DE REPO. Echte adressen
    # uit de voorraad van 14 oktober, een per soort afwijking die de eigen
    # functie toen gaf: een punt, een titel, een accent en een lidwoord.
    for straat, nr, letter in (("St. Annastraat", 1, "D"),
                               ("Professor Schrijnenstraat", 11, ""),
                               ("Mariënburgsestraat", 10, ""),
                               ("de Ruyterstraat", 105, "")):
        eigen = adressleutel(straat, nr, letter, "")
        repo = _psl.sleutel(f"{straat} {nr}{letter}")
        if eigen != repo:
            afwijkingen.append(f"het veld sleutel wijkt af van pandsleutel: "
                               f"{eigen!r} tegen {repo!r}")
    if adressleutel("Bottelstraat", 1, "", "2") != adressleutel(
            "Bottelstraat", 12, "", ""):
        afwijkingen.append("de proef op de botsing meet niets, want deze twee "
                           "adressen botsen niet meer")
    bewaar = doorloop

    def nep_bots(collectie, budget, per_pagina):
        per_pagina(bots)
        return {"paginas": 1, "objecten": 2, "seconden": 0.0,
                "ronde_af": True, "fout": ""}

    doorloop = nep_bots
    try:
        vb = {}
        botsuit = fase_bag(vb, {"6521AB": ("Bottendaal",)}, 1, {},
                           signalen=set())
    finally:
        doorloop = bewaar
    if len(vb.get("adressen") or {}) != 2:
        afwijkingen.append(
            f"twee objecten met een botsende adressleutel leverden "
            f"{len(vb.get('adressen') or {})} records in plaats van 2; dan "
            f"slokt de sleutel nog woningen op")
    if botsuit.get("woningen_gezien") != 2:
        afwijkingen.append("de botsproef zag geen twee woningen")

    # De pandsleutel moet de BAG-identificatie zijn en niet PDOK's uuid.
    bottel12 = adressen.get("0268010000000001") or {}
    if bottel12.get("pand") != "0268100000000011":
        afwijkingen.append(f"pand van Bottelstraat 12: "
                           f"{bottel12.get('pand')!r} in plaats van de "
                           f"BAG-identificatie")
    bottel18 = adressen.get("0268010000000008") or {}
    if bottel18.get("pand") != "":
        afwijkingen.append("een onbekend pand moet leeg blijven en geen uuid "
                           f"krijgen, maar werd {bottel18.get('pand')!r}")
    # Gemengd gebruik hoort bij de woningen en niet bij de winkels.
    if "0268010000000005" not in adressen:
        afwijkingen.append("winkelfunctie,woonfunctie werd niet als woning "
                           "gezien; dan is de komma-splitsing stuk")
    if "0268010000000004" not in anders:
        afwijkingen.append("de winkel staat niet onder niet_woningen")
    if "0268010000000006" in adressen:
        afwijkingen.append("een adres buiten de ring is toch bewaard")

    # BEIDE BUURTEN BEWAARD. Koos dit de eerste op alfabet, dan verloor
    # Stadscentrum 24 van zijn 471 postcodes uit de plinttelling.
    winkel = anders.get("0268010000000004") or {}
    if winkel.get("buurten") != ["Benedenstad", "Stadscentrum"]:
        afwijkingen.append(f"een postcode in twee buurten levert "
                           f"{winkel.get('buurten')!r} in plaats van beide")

    # WAT ER NIET MEER IS, MOET ERUIT.
    if derde.get("adressen_verwijderd") != 1:
        afwijkingen.append(
            f"een verdwenen object leverde "
            f"{derde.get('adressen_verwijderd')} verwijderingen in plaats "
            f"van 1; dan loopt het aantal in de brief op")
    if "0268010000000005" in (voorraad_weg.get("adressen") or {}):
        afwijkingen.append("een object dat de BAG niet meer teruggeeft staat "
                           "er nog in")
    if derde.get("van_soort_gewisseld") != 1:
        afwijkingen.append(
            f"een winkel die woning werd gaf "
            f"{derde.get('van_soort_gewisseld')} wisselingen in plaats van 1")
    dubbel = (set(voorraad_weg.get("adressen") or {})
              & set(voorraad_weg.get("niet_woningen") or {}))
    if dubbel:
        afwijkingen.append(f"{len(dubbel)} objecten staan in beide lijsten en "
                           f"worden dus dubbel geteld: {sorted(dubbel)}")

    # EEN HALVE RONDE MAG NIETS WEGGOOIEN.
    if vierde.get("adressen_verwijderd") != 0:
        afwijkingen.append(
            f"een afgebroken ronde verwijderde "
            f"{vierde.get('adressen_verwijderd')} records; dan gooit een "
            f"haperende dienst de halve ring weg")
    if not vierde.get("fouten"):
        afwijkingen.append("een afgebroken ronde meldt geen fout")

    # DE PANDFASE OP DE ECHTE VORM.
    if pandkaart != {"uuid-een": "0268100000000011",
                     "uuid-twee": "0268100000000022"}:
        afwijkingen.append(f"fase_panden gaf {pandkaart!r}")
    if pandstand.get("omzettingen") != 2:
        afwijkingen.append(f"fase_panden meldt "
                           f"{pandstand.get('omzettingen')} omzettingen")
    if pandstand.get("fout"):
        afwijkingen.append(f"fase_panden meldde een fout: {pandstand['fout']}")

    for status, moet in (("Verblijfsobject in gebruik", True),
                         ("Verblijfsobject buiten gebruik", True),
                         ("Verbouwing verblijfsobject", True),
                         ("Verblijfsobject ingetrokken", False),
                         ("Niet gerealiseerd verblijfsobject", False),
                         ("Verblijfsobject ten onrechte opgevoerd", False)):
        if _bestaat(status) != moet:
            afwijkingen.append(f"_bestaat({status!r}) gaf "
                               f"{_bestaat(status)}")

    if _pand_uuids({"pand.href": ["https://x/items/abc"]}) != ["abc"]:
        afwijkingen.append("pand.href wordt niet goed uitgelezen")
    if _pand_uuids({}) != []:
        afwijkingen.append("een object zonder pand moet een lege lijst geven")

    # De tweede ronde op dezelfde gegevens mag niets veranderen.
    if tweede.get("adressen_onveranderd") != 4:
        afwijkingen.append(
            f"tweede ronde meldt {tweede.get('adressen_onveranderd')} "
            f"onveranderd in plaats van 3; dan verandert het hele bestand "
            f"elke ronde")
    if tweede.get("adressen_nieuw") or tweede.get("adressen_bijgewerkt"):
        afwijkingen.append(
            f"tweede ronde meldt {tweede.get('adressen_nieuw')} nieuw en "
            f"{tweede.get('adressen_bijgewerkt')} bijgewerkt, terwijl er "
            f"niets veranderd is")
    if json.dumps(voorraad, sort_keys=True) != json.dumps(voorraad_na,
                                                          sort_keys=True):
        afwijkingen.append("twee rondes op dezelfde gegevens leveren een "
                           "ander bestand op; dan groeit de repo per run "
                           "met het hele bestand")

    afwijkingen.extend(proef_tegels())
    afwijkingen.extend(proef_labels())

    # DE LUS STAAT ONDERAAN, BIJ HET SLOT. Hij stond hier, halverwege, en
    # alles wat eronder werd toegevoegd telde wel mee in het aantal maar werd
    # nooit getoond. Dat kostte vandaag twee keer tijd: een proef die "1
    # afwijking" meldt zonder te zeggen welke, is net zo stil als geen proef.
    # GEEN AANTAL CONTROLES MEER. Dat getal stond er eerst bij en was fout,
    # en een fout getal in een proefverslag is erger dan geen getal: het wekt
    # vertrouwen dat het niet verdient. Wat de proef dekt staat er wel.
    # HET BLOK DAT PA LEEST, EN NIET ALLEEN DE RECORDS. Een veld dat goed in
    # het bestand staat en verkeerd in de tekst komt, is voor de lezer
    # hetzelfde als een verkeerd veld. Daarom hier de twee zinnen die het
    # bouwjaar van het pand gebruiken, op een pijplijn die met de hand is
    # gemaakt: twee woningen in een pand uit 1912 en een in een pand uit dit
    # jaar.
    nu_jaar = dt.date.today().year
    nep_voorraad = {
        "adressen": {"a1": {"adres": "Bottelstraat 1", "buurten": ["Bottendaal"],
                            "postcode": "6521AB"}},
        "pijplijn": {
            "p1": {"adres": "Oudestraat 1", "buurten": ["Bottendaal"],
                   "pand_status": "Pand in gebruik", "pand_bouwjaar": 1912},
            "p2": {"adres": "Oudestraat 3", "buurten": ["Bottendaal"],
                   "pand_status": "Pand in gebruik", "pand_bouwjaar": 1912},
            "p3": {"adres": "Nieuwstraat 1", "buurten": ["Bottendaal"],
                   "pand_status": "Pand in gebruik",
                   "pand_bouwjaar": nu_jaar},
            "p4": {"adres": "Nieuwstraat 3", "buurten": ["Bottendaal"],
                   "pand_status": "Bouw gestart", "pand_bouwjaar": nu_jaar},
        }}
    import tempfile
    with tempfile.TemporaryDirectory() as map_:
        pad = os.path.join(map_, "voorraad.json")
        with open(pad, "w", encoding="utf-8") as f:
            json.dump(nep_voorraad, f)
        blok = tekst_pijplijn(pad)
    if "2 in een pand van voor" not in blok:
        afwijkingen.append("de pijplijntekst splitst de groep in een pand "
                           "dat al in gebruik is niet op bouwjaar")
    if "1 in een pand van" not in blok:
        afwijkingen.append("de pijplijntekst noemt de bijna opgeleverde "
                           "nieuwbouw niet apart")
    # En zonder bouwjaar hoort er "nog niet gekeken" te staan en geen nul.
    for r in nep_voorraad["pijplijn"].values():
        r.pop("pand_bouwjaar", None)
    with tempfile.TemporaryDirectory() as map_:
        pad = os.path.join(map_, "voorraad.json")
        with open(pad, "w", encoding="utf-8") as f:
            json.dump(nep_voorraad, f)
        kaal = tekst_pijplijn(pad)
    if "nog niet gekeken" not in kaal:
        afwijkingen.append("zonder bouwjaar zegt de pijplijntekst niet dat "
                           "het nog niet gekeken is, en dan leest het als "
                           "gekeken en niets gevonden")

    # EEN PAND WAAR EEN BEKENDMAKING OVER GING, BLIJFT STAAN. Het echte geval
    # van 14 oktober: Berg en Dalseweg 11 en 11A, postcode 6521JB, buurt
    # Hunnerberg. Die postcode staat niet in de zeef, dus viel het object weg,
    # terwijl de brief er diezelfde ochtend een kernsignaal over had. De
    # buurman op 15 staat erbij om te toetsen dat de zeef niet alsnog de hele
    # postcode binnenlaat.
    def _vbo(nr, letter, ident, doel="woonfunctie", opp=116, punt=True):
        kenmerk = {"id": f"s{ident}", "properties": {
            "postcode": "6521JB", "status": "Verblijfsobject in gebruik",
            "gebruiksdoel": doel, "oppervlakte": opp,
            "openbare_ruimte_naam": "Berg en Dalseweg", "huisnummer": nr,
            "huisletter": letter, "toevoeging": None,
            "identificatie": ident}}
        if punt is True:
            # Berg en Dalseweg, ruwweg. Lengtegraad eerst, zoals CRS84.
            kenmerk["geometry"] = {"type": "Point",
                                   "coordinates": [5.8742, 51.8452]}
        elif punt == "omgekeerd":
            kenmerk["geometry"] = {"type": "Point",
                                   "coordinates": [51.8452, 5.8742]}
        return kenmerk

    signaalkenmerken = [
        _vbo(11, None, "0268010000009911"),
        # 11A zonder geometrie: dat mag geen geraden punt opleveren.
        _vbo(11, "A", "0268010000009912", opp=74, punt=False),
        # De tandartspraktijk op de begane grond: geen woonfunctie, dus die
        # hoort bij niet_woningen en niet bij de woningvoorraad.
        _vbo(11, None, "0268010000009913", doel="gezondheidszorgfunctie",
             opp=92),
        # De buurman, zonder signaal.
        _vbo(15, None, "0268010000009915"),
        # EEN NAAMGENOOT IN EEN ANDERE GEMEENTE, met hetzelfde adres. Het id
        # begint met een andere gemeentecode, zoals de 29 van 14 oktober.
        _vbo(11, None, "0241010000009911"),
    ]

    def nep_signaal(collectie, budget, per_pagina):
        per_pagina(signaalkenmerken)
        return {"paginas": 1, "objecten": len(signaalkenmerken),
                "seconden": 0.0, "ronde_af": True, "fout": ""}

    echt3, globals()["doorloop"] = doorloop, nep_signaal
    try:
        vs = {}
        sig_uit = fase_bag(vs, {"6521AB": ("Bottendaal",)}, 1, {},
                           signalen={"bergendalseweg11"})
        vs_leeg = {}
        leeg_uit = fase_bag(vs_leeg, {"6521AB": ("Bottendaal",)}, 1, {},
                            signalen=set())
    finally:
        globals()["doorloop"] = echt3

    adressen_sig = vs.get("adressen") or {}
    anders_sig = vs.get("niet_woningen") or {}
    if set(adressen_sig) != {"0268010000009911", "0268010000009912"}:
        afwijkingen.append(
            f"een pand met een bekendmaking buiten de focusbuurten wordt niet "
            f"bewaard: woningen {sorted(adressen_sig)}")
    if set(anders_sig) != {"0268010000009913"}:
        afwijkingen.append(
            f"de niet-woonfunctie op hetzelfde adres wordt niet apart "
            f"bewaard: {sorted(anders_sig)}")
    if "0241010000009911" in adressen_sig or "0241010000009911" in anders_sig:
        afwijkingen.append("een object met hetzelfde adres in een andere "
                           "gemeente komt mee als signaal; het adres is niet "
                           "uniek, het id wel")
    if "0268010000009915" in adressen_sig or "0268010000009915" in anders_sig:
        afwijkingen.append("de buurman zonder signaal komt mee; dan laat de "
                           "zeef de hele postcode binnen")
    for sleutel, rec in adressen_sig.items():
        if rec.get("herkomst") != "bekendmaking":
            afwijkingen.append(f"{sleutel} krijgt herkomst "
                               f"{rec.get('herkomst')!r} in plaats van "
                               f"'bekendmaking'; dan is na het opslaan niet "
                               f"meer te zien dat dit geen buurtpand is")
        if rec.get("buurten"):
            afwijkingen.append(f"{sleutel} krijgt buurten {rec['buurten']}, "
                               f"terwijl het buiten de focusbuurten ligt")
    if "6521JB" in (vs.get("postcodes") or {}):
        afwijkingen.append("een postcode buiten de ring wordt als afgewerkte "
                           "ringpostcode opgeschreven; dan klopt de telling "
                           "van lege Nijmeegse postcodes niet meer")
    # EN HET AANTAL NAGEKEKEN POSTCODES OOK NIET. Dit is de meting die de
    # opruiming aan het eind van fase_bag niet maskeert: die haalt
    # niet-ringpostcodes na een afgemaakte ronde alsnog uit de kaart, dus
    # bleef de regel hierboven stil toen ik de bewaking bij het schrijven
    # wegnam. postcodes_gedaan komt uit per_postcode en wordt niet opgeruimd.
    if sig_uit.get("postcodes_gedaan") != 0:
        afwijkingen.append(
            f"{sig_uit.get('postcodes_gedaan')} postcodes gelden als "
            f"nagekeken terwijl er alleen om een signaal is bewaard; dan "
            f"telt een postcode buiten de ring mee als afgewerkt ringwerk")
    # HET PUNT BIJ HET PAND, EN GEEN GERADEN PUNT.
    _p11 = adressen_sig.get("0268010000009911") or {}
    _p11a = adressen_sig.get("0268010000009912") or {}
    if _p11.get("punt") != [5.8742, 51.8452]:
        afwijkingen.append(f"het punt van het verblijfsobject wordt niet "
                           f"bewaard: {_p11.get('punt')!r}")
    if "punt" in _p11a:
        afwijkingen.append(f"een object zonder geometrie krijgt toch een "
                           f"punt: {_p11a.get('punt')!r}")
    # TWEE MET EN EEN ZONDER, EN NIET DRIE EN EEN. Er gaan vier objecten in,
    # maar nummer 15 valt al weg op de zeef, vóór de puntteller. Dat is goed:
    # een teller die ook objecten buiten onze ring meerekent, zegt niets over
    # de dekking van ons eigen bestand. Ik rekende eerst op drie en de proef
    # wees me terecht.
    if sig_uit.get("met_punt") != 2 or sig_uit.get("zonder_punt") != 1:
        afwijkingen.append(
            f"de punten worden verkeerd geteld: {sig_uit.get('met_punt')} met "
            f"en {sig_uit.get('zonder_punt')} zonder, verwacht 2 en 1")
    # EEN OMGEKEERD COORDINAAT IS GEEN PUNT. Lengte- en breedtegraad omwisselen
    # legt Nijmegen in de Indische Oceaan, en een zone die daar gevonden wordt
    # bestaat niet. Maar een punt dat net in de verkeerde zone ligt, levert een
    # parkeernorm die klopt zolang niemand hem nameet. Dus liever niets.
    if punt_uit({"geometry": {"type": "Point",
                              "coordinates": [51.8452, 5.8742]}}) is not None:
        afwijkingen.append("een omgekeerd coordinaat wordt als punt "
                           "geaccepteerd")
    _vlak = {"geometry": {"type": "Polygon", "coordinates": [
        [[5.8740, 51.8450], [5.8745, 51.8450], [5.8745, 51.8455],
         [5.8740, 51.8455], [5.8740, 51.8450]]]}}
    if punt_uit(_vlak) is not None:
        afwijkingen.append(f"een vlak wordt als punt gelezen: "
                           f"{punt_uit(_vlak)!r}")
    if punt_uit({}) is not None:
        afwijkingen.append("een kenmerk zonder geometrie levert toch een punt")

    # EN EEN PUNT DAT WE AL HADDEN, OVERLEEFT EEN RONDE ZONDER GEOMETRIE. Dit
    # is de fout die op 12 oktober de rekenmethode van 698 labels wiste.
    _zonder_geo = [_vbo(11, None, "0268010000009911", punt=False)]

    def nep_zonder_geo(collectie, budget, per_pagina):
        per_pagina(_zonder_geo)
        return {"paginas": 1, "objecten": 1, "seconden": 0.0,
                "ronde_af": True, "fout": ""}

    echt4, globals()["doorloop"] = doorloop, nep_zonder_geo
    try:
        tweede_uit = fase_bag(vs, {"6521AB": ("Bottendaal",)}, 1, {},
                              signalen={"bergendalseweg11"})
    finally:
        globals()["doorloop"] = echt4
    _na = (vs.get("adressen") or {}).get("0268010000009911") or {}
    if _na.get("punt") != [5.8742, 51.8452]:
        afwijkingen.append(f"een ronde zonder geometrie gooit het punt weg "
                           f"dat we al hadden: {_na.get('punt')!r}")
    if tweede_uit.get("punt_behouden") != 1:
        afwijkingen.append(f"het behouden punt wordt niet geteld: "
                           f"{tweede_uit.get('punt_behouden')}")

    # EN EEN PAND DAT WE AL HADDEN, OVERLEEFT EEN AFGEBROKEN PANDFASE. Op 7
    # november verloren 7.503 woningen zo hun pand. Drie rondes op hetzelfde
    # object: de eerste kent het pand, de tweede mist de sleutel in de
    # omzetting (budget op), de derde kent de sleutel wel maar zonder pand.
    # De derde moet het pand WEL leegmaken, anders is de regel "houd altijd
    # het oude" en ziet de voorraad nooit meer een echte wijziging.
    _metpand = _vbo(17, None, "0268010000009917")
    _metpand["properties"]["pand.href"] = [
        "https://api.pdok.nl/x/collections/pand/items/uuid-17"]

    def nep_pand(collectie, budget, per_pagina):
        per_pagina([_metpand])
        return {"paginas": 1, "objecten": 1, "seconden": 0.0,
                "ronde_af": True, "fout": ""}

    vp = {}
    echt5, globals()["doorloop"] = doorloop, nep_pand
    try:
        fase_bag(vp, {"6521AB": ("Bottendaal",)}, 1,
                 {"uuid-17": "0268100000009917"},
                 pandstatus={"0268100000009917": "Pand in gebruik"},
                 pandbouwjaar={"0268100000009917": 1912},
                 signalen={"bergendalseweg17"})
        afgebroken = fase_bag(vp, {"6521AB": ("Bottendaal",)}, 1, {},
                              signalen={"bergendalseweg17"})
        _na_afbr = dict((vp.get("adressen") or {}).get("0268010000009917")
                        or {})
        fase_bag(vp, {"6521AB": ("Bottendaal",)}, 1, {"uuid-17": ""},
                 signalen={"bergendalseweg17"})
        _na_leeg = (vp.get("adressen") or {}).get("0268010000009917") or {}
    finally:
        globals()["doorloop"] = echt5
    if (_na_afbr.get("pand") != "0268100000009917"
            or _na_afbr.get("pand_status") != "Pand in gebruik"
            or _na_afbr.get("pand_bouwjaar") != 1912):
        afwijkingen.append(
            f"een afgebroken pandfase wist het pand dat we al hadden: "
            f"{_na_afbr.get('pand')!r}, {_na_afbr.get('pand_status')!r}, "
            f"{_na_afbr.get('pand_bouwjaar')!r}")
    if afgebroken.get("pand_behouden") != 1:
        afwijkingen.append(f"het behouden pand wordt niet geteld: "
                           f"{afgebroken.get('pand_behouden')}")
    if _na_leeg.get("pand") != "" or "pand_status" in _na_leeg:
        afwijkingen.append(
            f"een pandfase die de sleutel wel kende maar zonder pand, laat "
            f"toch het oude pand staan: {_na_leeg.get('pand')!r}")

    # HERVATTEN OVER RUNS. Sinds 3 november kwam geen ronde meer rond in tien
    # minuten. Met voortgang gaat elke run verder waar de vorige stopte.
    # Nagebootst met een _tegel die per aanroep van doorloop maar vijf tegels
    # haalt en dan op het budget stuit.
    echt_tegel = globals()["_tegel"]
    gelopen = []

    def maak_tegel(per_run):
        teller = {"n": 0}

        def nep_tegel(collectie, doos, per_pagina, stoppen):
            if teller["n"] >= per_run:
                return False, 0, 0, "tijdbudget om"
            teller["n"] += 1
            gelopen.append(doos)
            return True, 1, 10, ""
        return nep_tegel

    vg_h = {}
    runs_h = []
    try:
        for _ in range(4):
            globals()["_tegel"] = maak_tegel(5)
            runs_h.append(doorloop("pand", 600, lambda ks: None, vg_h))
    finally:
        globals()["_tegel"] = echt_tegel
    _af = [r["ronde_af"] for r in runs_h]
    if _af != [False, False, False, True]:
        afwijkingen.append(f"hervatten: ronde_af per run {_af}, verwacht "
                           f"drie keer niet af en dan af (16 tegels, 5 per "
                           f"run)")
    if sorted(gelopen) != sorted(_raster(DOOS, TEGELS)):
        afwijkingen.append(f"hervatten: {len(gelopen)} tegels gelopen over "
                           f"vier runs, {len(set(gelopen))} verschillende; "
                           f"verwacht elk van de {TEGELS * TEGELS} precies een "
                           f"keer")
    if vg_h:
        afwijkingen.append(f"na een afgemaakte cyclus staat er nog voortgang: "
                           f"{sorted(vg_h)}")
    if runs_h[-1].get("cyclus_runs") != 4:
        afwijkingen.append(f"de cyclus telt {runs_h[-1].get('cyclus_runs')} "
                           f"runs in plaats van 4")
    if runs_h[0].get("hervat") or not runs_h[1].get("hervat"):
        afwijkingen.append("hervat staat verkeerd: de eerste run begint, de "
                           "tweede hervat")
    if [r.get("tegels_deze_run") for r in runs_h] != [5, 5, 5, 1]:
        afwijkingen.append(f"tegels_deze_run per run "
                           f"{[r.get('tegels_deze_run') for r in runs_h]}, "
                           f"verwacht [5, 5, 5, 1]")

    # EEN TEGEL DIE LANGER DUURT DAN HET HELE BUDGET. Elke tegel op diepte 0
    # geeft een pagina en stuit dan op het budget; pas de kinderen komen
    # rond. Ging zo'n tegel heel terug in de rij, dan stond de cyclus voor
    # altijd stil.
    def lange_tegel(collectie, doos, per_pagina, stoppen):
        if doos in _raster(DOOS, TEGELS):
            return False, 1, 10, "tijdbudget om"
        return True, 1, 10, ""

    vg_l, runs_l = {}, []
    try:
        globals()["_tegel"] = lange_tegel
        for _ in range(TEGELS * TEGELS + 2):
            runs_l.append(doorloop("pand", 600, lambda ks: None, vg_l))
            if runs_l[-1]["ronde_af"]:
                break
    finally:
        globals()["_tegel"] = echt_tegel
    if not runs_l[-1]["ronde_af"]:
        afwijkingen.append(f"een tegel die langer duurt dan het budget houdt "
                           f"de cyclus na {len(runs_l)} runs nog tegen")

    # Zonder voortgang het oude gedrag: elke aanroep begint opnieuw.
    gelopen.clear()
    try:
        globals()["_tegel"] = maak_tegel(5)
        doorloop("pand", 600, lambda ks: None)
        globals()["_tegel"] = maak_tegel(5)
        doorloop("pand", 600, lambda ks: None)
    finally:
        globals()["_tegel"] = echt_tegel
    if len(set(gelopen)) != 5:
        afwijkingen.append(f"zonder voortgang liepen twee aanroepen "
                           f"{len(set(gelopen))} verschillende tegels; "
                           f"verwacht twee keer dezelfde vijf")

    # VERWIJDEREN PAS NA DE HELE CYCLUS, MET WAT DE EERSTE RUN ZAG. Drie
    # woningen in de voorraad. Run 1 ziet 21, run 2 ziet 23 en maakt de
    # cyclus af. 22 is weg en moet eruit; 21 moet blijven, ook al zag de
    # laatste run hem niet.
    vc = {"adressen": {}}
    for _nr in (21, 22, 23):
        _id = f"02680100000099{_nr}"
        vc["adressen"][_id] = {"adres": f"Berg en Dalseweg {_nr}",
                               "postcode": "6521JB", "pand": "",
                               "status": "Verblijfsobject in gebruik"}
    _per_run = [[_vbo(21, None, "0268010000009921")],
                [_vbo(23, None, "0268010000009923")]]

    def nep_cyclus(collectie, budget, per_pagina, voortgang):
        kenm = _per_run.pop(0)
        per_pagina(kenm)
        laatste = not _per_run
        voortgang.clear()
        if not laatste:
            voortgang["wacht"] = [["5.8,51.8,5.9,51.9", 0]]
        return {"paginas": 1, "objecten": 1, "seconden": 0.0,
                "ronde_af": laatste, "fout": ""}

    vg_c = {}
    echt6, globals()["doorloop"] = doorloop, nep_cyclus
    try:
        c1 = fase_bag(vc, {"6521JB": ("Bottendaal",)}, 1, {},
                      signalen={"bergendalseweg21", "bergendalseweg23"},
                      voortgang=vg_c)
        _na_c1 = sorted(vc["adressen"])
        c2 = fase_bag(vc, {"6521JB": ("Bottendaal",)}, 1, {},
                      signalen={"bergendalseweg21", "bergendalseweg23"},
                      voortgang=vg_c)
    finally:
        globals()["doorloop"] = echt6
    if c1.get("adressen_verwijderd") or len(_na_c1) != 3:
        afwijkingen.append(f"een run midden in de cyclus verwijderde "
                           f"{c1.get('adressen_verwijderd')}")
    _blijft = sorted(vc["adressen"])
    if _blijft != ["0268010000009921", "0268010000009923"]:
        afwijkingen.append(f"na de cyclus staan er {_blijft}; verwacht 21 en "
                           f"23, en 22 weg. Staat 21 er niet, dan vergat de "
                           f"laatste run wat de eerste zag")
    if vg_c:
        afwijkingen.append(f"na de cyclus staat er nog voortgang voor de "
                           f"objecten: {sorted(vg_c)}")
    if c1.get("postcodes_leeg_nijmegen") is not None:
        afwijkingen.append(f"midden in de cyclus meldt de ronde "
                           f"{c1.get('postcodes_leeg_nijmegen')} lege "
                           f"postcodes; dat is niet gekeken, niet leeg")
    if c2.get("postcodes_leeg") != 0:
        afwijkingen.append(f"na de cyclus {c2.get('postcodes_leeg')!r} lege "
                           f"postcodes in plaats van 0")

    # DE OPEN LIJST. Een nieuw object waarvan de pandfase de sleutel nog niet
    # zag, komt erop; een latere run waarin de pandfase hem wel ziet, geeft
    # het pand, ook als de objectronde dit object die run niet bezoekt.
    _nieuw = _vbo(19, None, "0268010000009919")
    _nieuw["properties"]["pand.href"] = [
        "https://api.pdok.nl/x/collections/pand/items/uuid-19"]

    def nep_een(collectie, budget, per_pagina):
        per_pagina([_nieuw])
        return {"paginas": 1, "objecten": 1, "seconden": 0.0,
                "ronde_af": True, "fout": ""}

    def nep_niets(collectie, budget, per_pagina):
        return {"paginas": 0, "objecten": 0, "seconden": 0.0,
                "ronde_af": False, "fout": "tijdbudget om"}

    vo, open_ = {}, {}
    echt7 = doorloop
    try:
        globals()["doorloop"] = nep_een
        o1 = fase_bag(vo, {"6521AB": ("Bottendaal",)}, 1, {},
                      signalen={"bergendalseweg19"}, open_panden=open_)
        _open_na_1 = dict(open_)
        globals()["doorloop"] = nep_niets
        o2 = fase_bag(vo, {"6521AB": ("Bottendaal",)}, 1,
                      {"uuid-19": "0268100000009919"},
                      pandstatus={"0268100000009919": "Pand in gebruik"},
                      pandbouwjaar={"0268100000009919": 1931},
                      signalen={"bergendalseweg19"}, open_panden=open_)
    finally:
        globals()["doorloop"] = echt7
    _r19 = (vo.get("adressen") or {}).get("0268010000009919") or {}
    if _open_na_1 != {"0268010000009919": ["uuid-19"]}:
        afwijkingen.append(f"een nieuw object zonder opgezochte pandsleutel "
                           f"staat niet op de open lijst: {_open_na_1}")
    if (_r19.get("pand") != "0268100000009919"
            or _r19.get("pand_bouwjaar") != 1931
            or _r19.get("pand_status") != "Pand in gebruik"):
        afwijkingen.append(f"de open lijst gaf het pand niet in een latere "
                           f"run: {_r19.get('pand')!r}, "
                           f"{_r19.get('pand_bouwjaar')!r}")
    if open_ or o2.get("pand_opgelost") != 1 or o1.get("pand_open") != 1:
        afwijkingen.append(f"de open lijst telt verkeerd: na afloop {open_}, "
                           f"opgelost {o2.get('pand_opgelost')}, open "
                           f"{o1.get('pand_open')}")

    if sig_uit.get("om_een_signaal") != 3:
        afwijkingen.append(f"er worden {sig_uit.get('om_een_signaal')} "
                           f"objecten om een signaal bewaard in plaats van 3")
    # ZONDER SIGNALEN HET OUDE GEDRAG. Anders zou deze zeef alles binnenlaten
    # en is de melding over 54% blinde signalen geen meting meer.
    if (leeg_uit.get("om_een_signaal") or 0) != 0 or (vs_leeg.get("adressen")
                                                      or {}):
        afwijkingen.append("zonder signalen blijft er toch iets buiten de "
                           "ring staan")

    for a in afwijkingen:
        print(f"AFWIJKING: {a}", file=sys.stderr)

    print(f"Proef: {len(afwijkingen)} afwijkingen. Gedekt: de vorm van het "
          f"antwoord, de komma in gebruiksdoel, de historiezeef, de "
          f"vbo-sleutel en de botsing die hij vervangt, de omzetting van de "
          f"pandsleutel, beide buurten bij een dubbele postcode, verwijderen "
          f"na een afgemaakte ronde, niets verwijderen na een afgebroken "
          f"ronde, wisselen tussen woning en niet-woning, en twee gelijke "
          f"rondes die hetzelfde bestand opleveren, het raster met "
          f"het delen van een tegel die PDOK niet aankan, het bouwjaar van "
          f"het pand en het oudste daarvan bij twee panden, de "
          f"pijplijntekst die de groep in een pand dat al in gebruik is op "
          f"bouwjaar splitst, dat een objectronde de labelvelden van fase 2 "
          f"niet weggooit, de eenmalige inhaalslag op de rekenmethode die na "
          f"een ronde ophoudt, en de wachtrij van de labelfase: wat opnieuw "
          f"aan de beurt komt na een gevonden "
          f"label, een privelabel, een definitieve weigering en een "
          f"tijdelijke storing.", file=sys.stderr)
    return 1 if afwijkingen else 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--uit", default=UIT)
    p.add_argument("--pijplijn-uit", default="",
                   help="Alleen het blok over de pijplijn schrijven en "
                        "verder niets ophalen. Leest voorraad.json.")
    # Gemeten op 10 oktober met tegels: de objectronde 248,4 seconden over 201
    # pagina's en 22 tegels, de pandronde 247,0 seconden over 228 pagina's en
    # 19 tegels. Tien minuten is dus ruim twee keer de gemeten duur: genoeg
    # voor een trage dag en voor een paar delingen, en kort genoeg om niet een
    # half uur te blijven hangen als de dienst hapert.
    p.add_argument("--bag-minuten", type=float, default=10)
    p.add_argument("--panden-minuten", type=float, default=10)
    p.add_argument("--labels-minuten", type=float, default=45)
    p.add_argument("--alleen", choices=("bag", "labels"))
    p.add_argument("--buurt", action="append")
    p.add_argument("--proef", action="store_true",
                   help="de zeef nameten zonder netwerk")
    args = p.parse_args()

    if args.proef:
        return proef()

    # ALLEEN HET BLOK SCHRIJVEN, ZONDER OP TE HALEN. Dit leest voorraad.json
    # en doet geen enkele aanroep, zodat de briefworkflow het blok kan maken
    # zonder de voorraadronde te hoeven draaien. Die twee staan los van
    # elkaar, en dat is sinds 10 oktober met opzet zo.
    if args.pijplijn_uit:
        blok = tekst_pijplijn(args.uit)
        if blok:
            with open(args.pijplijn_uit, "w", encoding="utf-8") as f:
                f.write(blok)
            print(f"Pijplijn: blok naar {args.pijplijn_uit}", file=sys.stderr)
        else:
            print("Pijplijn: niets te melden; staat er al een ronde in "
                  "voorraad.json met objecten met status gevormd?",
                  file=sys.stderr)
        return 0

    voorraad = _lees(args.uit, {})
    pcs = postcodes_uit_inventaris(args.buurt)
    if not pcs and args.alleen != "labels":
        return 1

    # DE DIAGNOSE VAN DE ANDERE FASE NIET WISSEN. De workflow doet twee aparte
    # aanroepen: eerst --alleen bag, daarna --alleen labels. Begon dit met een
    # lege dict, dan schreef de labelronde een stand zonder de sleutels bag en
    # panden, en waren postcodes_leeg, ronde_af en de hele pandronde weg
    # voordat het gezondheidsrapport ernaar keek. Alle vier de controles die
    # erop staan vuurden dan nooit, en de voorraad kon stil te laag zijn
    # terwijl het rapport OK meldde. Precies de fout die dit standsbestand
    # moest voorkomen, nu in het bestand zelf. Daarom opbouwen op wat er al
    # staat.
    #
    # Elke fase stempelt haar eigen datum, zodat een fase die vandaag niet
    # draaide niet als vers wordt gelezen.
    uit = dict(_lees(STAND, {}).get("ronde") or {})
    uit["bijgewerkt"] = dt.date.today().isoformat()
    if args.alleen != "labels":
        # EERST DE PANDEN, DAN DE OBJECTEN. De omzetting van PDOK's pandsleutel
        # naar de BAG-pandidentificatie moet klaar zijn voordat de objecten
        # worden weggeschreven, anders staat er een sleutel in voorraad.json
        # die nergens op aansluit. Mislukt deze ronde, dan blijft het veld pand
        # leeg en gaat de rest door; de reden staat in de stand.
        # DE VOORTGANG ALLEEN BIJ EEN RONDE OVER DE HELE RING. Een proefdraai
        # met --buurt heeft een kleinere zeef; nam die de rij en de verzameling
        # gezien over, dan zou de cyclus daarna verwijderen op grond van een
        # halve ring. Precies de fout uit fase_bag waar een buurtproef 22.096
        # woningen op 1.700 zette.
        if args.buurt:
            vg = {"pand": None, "verblijfsobject": None, "open_panden": None}
        else:
            vg = voorraad.setdefault("voortgang", {})
            for sleutel in ("pand", "verblijfsobject", "open_panden"):
                vg.setdefault(sleutel, {})
        panden, uit["panden"] = fase_panden(args.panden_minuten * 60,
                                            vg["pand"])
        # De statuskaart eruit halen: die hoort bij de ronde en niet in het
        # standsbestand, want het zijn duizenden regels.
        pandstatus = uit["panden"].pop("_status_per_pand", {})
        pandbouwjaar = uit["panden"].pop("_bouwjaar_per_pand", {})
        uit["panden"]["datum"] = dt.date.today().isoformat()
        print("Panden: " + json.dumps(uit["panden"], ensure_ascii=False),
              file=sys.stderr)
        uit["bag"] = fase_bag(voorraad, pcs, args.bag_minuten, panden,
                              pandstatus, pandbouwjaar,
                              voortgang=vg["verblijfsobject"],
                              open_panden=vg["open_panden"])
        uit["bag"]["datum"] = dt.date.today().isoformat()
        print("BAG: " + json.dumps(uit["bag"], ensure_ascii=False),
              file=sys.stderr)
    if args.alleen != "bag":
        uit["labels"] = fase_labels(voorraad, args.labels_minuten)
        uit["labels"]["datum"] = dt.date.today().isoformat()
        print("Labels: " + json.dumps(uit["labels"], ensure_ascii=False),
              file=sys.stderr)

    adressen = voorraad.get("adressen") or {}
    met_opp = sum(1 for r in adressen.values() if r.get("oppervlakte"))
    met_label = sum(1 for r in adressen.values() if r.get("label"))
    uit["stand"] = {
        "woningen": len(adressen),
        "met_oppervlakte": met_opp,
        "met_label": met_label,
        "postcodes_gedaan": len(voorraad.get("postcodes") or {}),
    }
    voorraad["laatste_ronde"] = uit

    # DE DIAGNOSE ALTIJD WEGSCHRIJVEN, OOK ALS ER NIETS IS OPGEHAALD. Op 10
    # oktober liep de BAG-fase 35 minuten met een geldige sleutel en kwam er
    # niets uit. Het gezondheidsrapport kon alleen melden "voorraad nog leeg",
    # want deze functie gaf exitcode 1 en schreef niets, dus de teller met
    # fouten en de laatste foutmelding gingen mee de prullenbak in. Daarmee was
    # niet te zien of de BAG de vraag weigerde, of hij wel antwoordde maar niets
    # als woning werd herkend, of dat er echt niets stond.
    #
    # Dat is dezelfde fout als de rest: de melding die vertelt wat er mis is,
    # verdwijnt juist wanneer er iets mis is. Daarom een eigen standsbestand
    # dat altijd wordt overschreven, los van de gegevens.
    _schrijf(STAND, {"datum": dt.date.today().isoformat(), "ronde": uit})

    if not adressen and not anders_aantal(voorraad):
        print("Geen enkel adres opgehaald; bestand niet overschreven. "
              f"Zie {STAND} voor de fouten.", file=sys.stderr)
        return 1
    if not adressen:
        # Wel niet-woningen, geen woningen. Dat kan betekenen dat het veld
        # gebruiksdoelen anders heet of anders is opgebouwd dan _is_woning()
        # aanneemt, en dan is het zonde om die records weg te gooien.
        print(f"Geen woningen maar wel {anders_aantal(voorraad)} andere "
              f"adressen opgehaald; wel bewaard.", file=sys.stderr)
    if not _schrijf(args.uit, voorraad):
        return 1

    s = uit["stand"]
    print(f"\nStand: {s['woningen']} woningen, {s['met_oppervlakte']} met "
          f"oppervlakte, {s['met_label']} met label, "
          f"{s['postcodes_gedaan']} postcodes nagekeken.", file=sys.stderr)
    print(f"Weggeschreven naar {args.uit}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
