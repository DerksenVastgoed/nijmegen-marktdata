#!/usr/bin/env python3
"""
Wat een bekendmaking zegt over de uitkomst, en tot wanneer de stukken open staan.

WAAROM DIT BESTAAT. Wij volgen aanvragen en besluiten al, maar bewaren er
alleen datum, titel, soort en url van. De tekst van de publicatie zegt veel
meer, en die tekst halen wij al op.

DRIE DINGEN DIE ERIN STAAN EN DIE WIJ NIET GEBRUIKTEN:

  1. DE UITKOMST. De titel zegt alleen "Besluit voor het splitsen van ...".
     Van 37 besluiten noemde er twee het woord verleend. De tekst zegt het
     wel, in de eerste zin: "Gemeente Nijmegen verleende een
     omgevingsvergunning." Zonder die uitkomst valt er niets te leren van
     onze eigen voorspellingen, want dan weten wij nooit of we het goed
     zagen.

  2. HET ZAAKNUMMER. De aanvraag zegt "geregistreerd onder kenmerk
     Z2026-00005538", het besluit zegt "voor de aanvraag met zaaknummer
     Z2025-00011358". Daarmee horen aanvraag en besluit bij elkaar zonder
     dat wij op adres of datum hoeven te gissen. Nu koppelen wij op de
     pandsleutel, en dan hoort een tweede aanvraag voor hetzelfde pand bij
     het verkeerde besluit.

  3. TOT WANNEER DE STUKKEN TE ZIEN ZIJN. Het besluit zegt: "U kunt de
     gemeente tot 13 november 2026 laten weten dat u het niet eens bent met
     het besluit... In deze periode kunt u de documenten met informatie over
     het besluit bekijken via de link op deze pagina." De stukken staan dus
     open tijdens de bezwaartermijn en daarna niet meer. Dat verklaart
     waarom Mark zei dat het maar een paar weken kan.

WAT DIT NIET DOET. Het haalt die stukken niet op. De link waarmee dat zou
moeten staat niet in de broncode van de pagina; hij wordt door de browser
ingeladen en wij hebben hem niet kunnen vinden. Zie bijlagen.py. Wat deze
module wel kan is zeggen welke dossiers nu open staan en tot welke dag, zodat
het klikwerk een korte lijst met een deadline is in plaats van een zoektocht.
"""

import argparse
import json
import re
import sys

# De zinnen zoals ze er werkelijk staan. Afgelezen van drie besluiten en twee
# aanvragen van gemeente Nijmegen, niet bedacht. Een patroon bouwen tegen een
# zin die niemand schrijft, vangt niets.
RE_ZAAK = re.compile(r"\b(Z\d{4}-\d{6,})\b")
# TWEE BRONNEN DIE ANDERS SCHRIJVEN OVER HETZELFDE BESLUIT.
#
# De bekendmaking op overheid.nl zegt: "Gemeente Nijmegen verleende een
# omgevingsvergunning. De gemeente geeft hiermee toestemming voor ..."
# De brief aan de aanvrager zegt het anders: "Wij besloten over uw aanvraag.
# U krijgt een omgevingsvergunning. U ontvangt een omgevingsvergunning."
#
# Ik had alleen de eerste gelezen en de patronen daarop gebouwd. Op het
# besluit van Hatertseweg 338 gaf dat geen enkele treffer, en daar is het
# misgegaan. Beide vormen staan er nu in, allebei afgelezen van een echt
# stuk.
RE_VERLEEND = re.compile(
    r"(verleende een omgevingsvergunning"
    r"|geeft hiermee toestemming"
    r"|U krijgt een omgevingsvergunning"
    r"|U ontvangt een omgevingsvergunning)", re.I)
RE_BESLUITDATUM = re.compile(
    r"Dit besluit namen wij op (\d{1,2} \w+ \d{4})", re.I)
RE_BEZWAAR_TOT = re.compile(
    r"laten weten dat u het niet eens bent[^.]*?tot (\d{1,2} \w+ \d{4})", re.I)
RE_BEZWAAR_TOT2 = re.compile(r"tot (\d{1,2} \w+ \d{4}) laten weten dat u het "
                             r"niet eens bent", re.I)
# HET HARDE SIGNAAL, UIT DE METADATA VAN DE PAGINA ZELF.
# In de broncode van een publicatie met stukken staat:
#   <meta name="OVERHEIDop.datumEindeReactietermijn" content="2026-11-13" />
# Dat is machineleesbaar en het staat er alleen als er werkelijk iets ter
# inzage ligt. Daarmee is "heeft deze publicatie stukken" geen gok meer maar
# een veld, en hoeven wij niet op zinnen in de lopende tekst te vertrouwen.
RE_META_EINDE = re.compile(
    r'name="OVERHEIDop\.datumEindeReactietermijn"\s+content="(\d{4}-\d{2}-\d{2})"',
    re.I)

RE_ONTVANGEN = re.compile(r"ontving de aanvraag op (\d{1,2} \w+ \d{4})", re.I)
RE_VERWACHT = re.compile(
    r"neemt daarover waarschijnlijk (\d{1,2} \w+ \d{4})", re.I)

# WOORDEN DIE OP EEN ANDERE AFLOOP KUNNEN WIJZEN, EN WAAROM ZIJ NIET
# BESLISSEN.
#
# Ik heb geen enkele weigering gezien, dus ik ken de woorden niet waarmee een
# weigering wordt opgeschreven. Eerst lieten deze woorden de uitkomst op
# "anders" springen. Dat ging meteen mis op het besluit van Hatertseweg 338:
# daar staat in de standaardtekst "Maakt u binnen een jaar geen gebruik van
# de vergunning, dan kan deze worden ingetrokken". Een voorwaarde over de
# toekomst, geen afloop. Een verleende vergunning werd zo als "anders"
# geteld, en dat is precies de fout die een lerend model niet zelf kan
# herstellen.
#
# Dus beslissen zij niets meer. Zij worden gemeld als signaal naast de
# uitkomst, zodat de eerste echte weigering opvalt en wij het patroon uit dat
# geval kunnen halen in plaats van uit mijn fantasie.
ANDERS = ("weigerde", "geweigerd", "wijzen wij af", "afgewezen",
          "buiten behandeling", "ingetrokken", "van rechtswege")

MAANDEN = {"januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5,
           "juni": 6, "juli": 7, "augustus": 8, "september": 9,
           "oktober": 10, "november": 11, "december": 12}


def datum(tekst):
    """"13 november 2026" wordt 2026-11-13. Onbekend blijft leeg."""
    m = re.match(r"\s*(\d{1,2})\s+(\w+)\s+(\d{4})\s*$", tekst or "")
    if not m:
        return ""
    maand = MAANDEN.get(m.group(2).lower())
    if not maand:
        return ""
    return f"{int(m.group(3)):04d}-{maand:02d}-{int(m.group(1)):02d}"


def einde_reactietermijn(broncode):
    """
    De einddatum uit de metadata van de pagina, of leeg.

    Dit is een ander soort bewijs dan de lopende tekst: het staat er alleen
    als er werkelijk stukken ter inzage liggen. Een publicatie zonder dit
    veld heeft niets liggen, en dat is iets anders dan een publicatie waarvan
    wij de zin niet herkenden.
    """
    m = RE_META_EINDE.search(broncode or "")
    return m.group(1) if m else ""


def velden_uit(tekst):
    """
    De velden die in een publicatie staan. Wat ontbreekt blijft leeg.

    Nooit een aanname: staat er geen uitkomst in, dan is de uitkomst
    onbekend en niet "verleend". Een besluit dat wij verkeerd als verleend
    tellen, maakt onze voorspelling beter dan zij is, en dat is de enige
    fout die een lerend model niet zelf kan herstellen.
    """
    t = re.sub(r"\s+", " ", tekst or "")
    zaak = RE_ZAAK.search(t)
    uit = {
        "zaaknummer": zaak.group(1) if zaak else "",
        "uitkomst": "",
        "uitkomst_reden": "",
        "signalen": "",
        "besluitdatum": "",
        "bezwaar_tot": "",
        "ontvangen": "",
        "verwacht_besluit": "",
    }
    anders = [w for w in ANDERS if w in t.lower()]
    if RE_VERLEEND.search(t):
        uit["uitkomst"] = "verleend"
    elif anders:
        # GEEN OORDEEL ZONDER BEWIJS. Wij kennen de woorden van een
        # weigering niet, dus zeggen wij "onbekend" en melden wat er stond.
        # Een gok die toevallig goed uitpakt leert ons niets; een gok die
        # fout uitpakt bederft de hele reeks.
        uit["uitkomst"] = "onbekend"
    if anders:
        uit["signalen"] = ", ".join(anders)
    for sleutel, patroon in (("besluitdatum", RE_BESLUITDATUM),
                             ("ontvangen", RE_ONTVANGEN),
                             ("verwacht_besluit", RE_VERWACHT)):
        m = patroon.search(t)
        if m:
            uit[sleutel] = datum(m.group(1))
    for patroon in (RE_BEZWAAR_TOT, RE_BEZWAAR_TOT2):
        m = patroon.search(t)
        if m:
            uit["bezwaar_tot"] = datum(m.group(1))
            break
    return uit


def open_dossiers(rijen, vandaag):
    """
    Welke dossiers nu nog in hun bezwaartermijn zitten, aflopend op deadline.

    Dit is de lijst die het klikwerk kort maakt: alleen deze dossiers hebben
    hun stukken nog open staan. Een dossier zonder bezwaardatum staat er niet
    in, en dat is iets anders dan een dossier dat gesloten is; daarom telt de
    oproeper die apart.
    """
    uit = []
    for r in rijen:
        tot = r.get("bezwaar_tot") or ""
        if not tot:
            continue
        if tot >= vandaag:
            uit.append(r)
    return sorted(uit, key=lambda r: r["bezwaar_tot"])


def koppel(aanvragen, besluiten):
    """
    Aanvraag en besluit aan elkaar via het zaaknummer.

    WAAROM NIET OP PAND. Eerder koppelden wij op de pandsleutel en op datum:
    het eerste besluit na een aanvraag. Bij twee aanvragen voor hetzelfde pand
    hoort de tweede dan bij het besluit van de eerste. Het zaaknummer staat
    in beide publicaties en laat geen ruimte.

    MAAR HET ZAAKNUMMER IS NIET ALTIJD HETZELFDE. Zie koppel_op_adres() voor
    de 64 besluiten waarbij het zaaknummer van de aanvraag een ander is, en
    voor de strikte regel die 47 daarvan alsnog verbindt zonder de fout te
    maken die hierboven staat.
    """
    # EEN PUBLICATIE ZONDER ZAAKNUMMER VERDWEEN HIER. Beide lussen sloegen
    # een record zonder zaaknummer over, zonder else en zonder teller. Van de
    # 93 besluiten in het archief dragen 53 geen zaaknummer, en die kwamen dus
    # in geen van de drie uitkomsten terug: niet als paar, niet als los
    # besluit, nergens. Daarmee kon koppel_op_adres() ze ook nooit zien, en
    # was de uitkomst van deze functie stil te laag.
    per = {}
    zonder_nummer_a, zonder_nummer_b = [], []
    for a in aanvragen:
        if a.get("zaaknummer"):
            per.setdefault(a["zaaknummer"], {})["aanvraag"] = a
        else:
            zonder_nummer_a.append(a)
    for b in besluiten:
        if b.get("zaaknummer"):
            per.setdefault(b["zaaknummer"], {})["besluit"] = b
        else:
            zonder_nummer_b.append(b)
    paren, alleen_a, alleen_b = [], [], []
    for nummer, d in per.items():
        if "aanvraag" in d and "besluit" in d:
            paren.append((nummer, d["aanvraag"], d["besluit"]))
        elif "aanvraag" in d:
            alleen_a.append((nummer, d["aanvraag"]))
        else:
            alleen_b.append((nummer, d["besluit"]))
    # De publicaties zonder zaaknummer horen bij de losse: er is niets om op
    # te koppelen, maar ze bestaan wel en koppel_op_adres() kan ze proberen.
    alleen_a.extend(("", a) for a in zonder_nummer_a)
    alleen_b.extend(("", b) for b in zonder_nummer_b)
    return paren, alleen_a, alleen_b


def kern_van(titel):
    """
    De omschrijving zonder de vaste kop en zonder het adres.

    "Aanvraag omgevingsvergunning voor het splitsen van een woning, aan
    Pontanusstraat 42, 6524EP Nijmegen" wordt "splitsen van een woning". Zo
    zijn een aanvraag en een besluit over dezelfde zaak te vergelijken.
    """
    t = (titel or "").lower().strip()
    for kop in ("aanvraag omgevingsvergunning voor het ",
                "aanvraag omgevingsvergunning voor de ",
                "aanvraag omgevingsvergunning voor ",
                "besluit (met bopa) voor het ", "besluit (met bopa) voor ",
                "besluit voor het ", "besluit voor de ", "besluit voor ",
                "aanvraag ", "besluit "):
        if t.startswith(kop):
            t = t[len(kop):]
            break
    return re.sub(r",?\s*aan (?:de )?[a-z].*$", "", t).strip()


def gelijkenis(a, b):
    """Hoeveel twee omschrijvingen op elkaar lijken, tussen 0 en 1."""
    import difflib
    return round(difflib.SequenceMatcher(None, a or "", b or "").ratio(), 2)


def koppel_op_adres(alleen_a, alleen_b, sleutel_van=None):
    """
    Een besluit aan een aanvraag verbinden als het zaaknummer verschilt.

    WAT HIER AAN DE HAND IS. Op 14 oktober bleken 64 besluiten geen aanvraag
    te hebben op zaaknummer. Bij Pontanusstraat 42 staan beide publicaties
    gewoon in ons archief: de aanvraag op 20 januari 2026 om de woning in twee
    appartementen te splitsen, het besluit op 18 mei 2026 om de woning in 2
    zelfstandige appartementen te splitsen. Dezelfde zaak, 118 dagen ertussen,
    en twee verschillende zaaknummers: Z2026-00000134 en Z2025-00009314. Het
    zaaknummer van de gemeente is dus niet stabiel over de procedure heen.

    DE REGEL, EN WAAROM HIJ ZO STRENG IS. koppel() koos met opzet niet op
    adres, want bij twee aanvragen op een adres hoort de tweede dan bij het
    besluit van de eerste. Die fout wordt hier vermeden door alleen te
    verbinden als er PRECIES EEN kandidaat is: zelfde adres, aanvraag vóór
    het besluit, en een overlappend signaalsoort. Zijn er meer, dan gebeurt
    er niets.

    NAGEMETEN OP HET ECHTE ARCHIEF van 479 publicaties, 182 aanvragen en 93
    besluiten:
      53 van de 93 besluiten dragen GEEN zaaknummer, en 6 van de 182
         aanvragen. Die verdwenen tot vandaag in koppel(); zie daar.
      32 paren op zaaknummer
      61 losse besluiten blijven over
      44 daarvan hebben precies een kandidaat op adres  -> verbonden
       2 hebben meer dan een kandidaat                  -> niets
      15 hebben geen kandidaat                          -> niets
    Het aantal paren gaat daarmee van 32 naar 76. Van die 44 is de mediane
    tekstgelijkenis van de omschrijvingen 1,00 en de laagste 0,63, en dat
    laatste zijn formuleringsvarianten van hetzelfde
    ("omzettingsvergunning voor kamerverhuurvergunning" tegen
    "kamerverhuurvergunning"). Tussen de twee publicaties zit mediaan 92
    dagen, van 7 tot 247.

    MIJN EERSTE GETALLEN WAREN FOUT. Ik telde met een eigen script 64 losse
    besluiten en 47 koppelingen. Toen ik het door deze module zelf liet
    rekenen kwamen er 8 en 1 uit, en dat verschil was de 53 besluiten zonder
    zaaknummer die koppel() weggooide. Een getal uit een script naast de
    module is geen meting van de module.

    DIT IS GEEN DOORLOOPTIJD VAN DE GEMEENTE. De dagen hiertussen zijn de
    tijd tussen ONZE TWEE WAARNEMINGEN. De doorlooptijd van de gemeente loopt
    van ontvangst tot besluit en staat in de tekst van het besluit; die twee
    getallen mogen niet in een mediaan terechtkomen.

    Elk paar draagt hoe het is verbonden, want een afgeleid verband mag er
    niet uitzien als een hard verband.
    """
    sleutel_van = sleutel_van or (lambda r: r.get("adres") or "")
    aanvragen = [a for _, a in alleen_a] if alleen_a and isinstance(
        alleen_a[0], tuple) else list(alleen_a or [])
    besluiten = [b for _, b in alleen_b] if alleen_b and isinstance(
        alleen_b[0], tuple) else list(alleen_b or [])
    paren, meerdere, zonder = [], [], []
    for b in besluiten:
        adres = sleutel_van(b)
        if not adres:
            zonder.append(b)
            continue
        kandidaten = [
            a for a in aanvragen
            if sleutel_van(a) == adres
            and (a.get("datum") or "") < (b.get("datum") or "")
            and (set(a.get("soorten") or []) & set(b.get("soorten") or [])
                 or not (a.get("soorten") or b.get("soorten")))]
        if len(kandidaten) == 1:
            a = kandidaten[0]
            paren.append({
                "adres": adres, "aanvraag": a, "besluit": b,
                "gekoppeld_via": "adres",
                "gelijkenis": gelijkenis(kern_van(a.get("titel")),
                                         kern_van(b.get("titel"))),
                "dagen_tussen_waarnemingen": _dagen(a.get("datum"),
                                                    b.get("datum")),
            })
        elif len(kandidaten) > 1:
            meerdere.append(b)
        else:
            zonder.append(b)
    return paren, meerdere, zonder


def _dagen(van, tot):
    import datetime as _dt
    try:
        return (_dt.date.fromisoformat(tot) - _dt.date.fromisoformat(van)).days
    except Exception:
        return None


def proef():
    fouten = []

    def check(naam, echt, verwacht):
        if echt != verwacht:
            fouten.append(f"{naam}: {echt!r}, verwacht {verwacht!r}")

    # 1. EEN BESLUIT ZOALS HET ER WERKELIJK STAAT.
    # Dit is de tekst van het besluit over Hatertseweg 338, afgelezen van de
    # publicatie. Niet geparafraseerd: de patronen moeten tegen deze zinnen
    # werken en niet tegen zinnen die ik mooier vond.
    besluit = ("Besluit voor Het verbouwen en uitbreiden tot 6 zelfstandige "
               "woonruimtes, aan Hatertseweg 338, 6533GP Nijmegen Gemeente "
               "Nijmegen verleende een omgevingsvergunning. De gemeente geeft "
               "hiermee toestemming voor Het verbouwen en uitbreiden tot 6 "
               "zelfstandige woonruimtes aan Hatertseweg 338, 6533GP "
               "Nijmegen. Dit besluit namen wij op 14 september 2026 voor de "
               "aanvraag met zaaknummer Z2025-00011358. Bent u het niet eens "
               "met het besluit? U kunt de gemeente tot 13 november 2026 "
               "laten weten dat u het niet eens bent met het besluit. Dit "
               "heet bezwaar maken. In deze periode kunt u de documenten met "
               "informatie over het besluit bekijken via de link op deze "
               "pagina.")
    v = velden_uit(besluit)
    check("zaaknummer", v["zaaknummer"], "Z2025-00011358")
    check("uitkomst", v["uitkomst"], "verleend")
    check("besluitdatum", v["besluitdatum"], "2026-09-14")
    check("bezwaar tot", v["bezwaar_tot"], "2026-11-13")

    # 2. EEN AANVRAAG ZOALS ZIJ ER WERKELIJK STAAT.
    aanvraag = ("Gemeente Nijmegen ontving een aanvraag voor een "
                "omgevingsvergunning. De aanvraag is geregistreerd onder "
                "kenmerk Z2026-00005538. De gemeente ontving de aanvraag op "
                "22 september 2026. De gemeente neemt daarover waarschijnlijk "
                "17 november 2026 een besluit. U kunt nu nog niet reageren.")
    a = velden_uit(aanvraag)
    check("kenmerk van de aanvraag", a["zaaknummer"], "Z2026-00005538")
    check("ontvangen", a["ontvangen"], "2026-09-22")
    check("verwacht besluit", a["verwacht_besluit"], "2026-11-17")
    # EEN AANVRAAG HEEFT GEEN UITKOMST, en die mag er ook niet bij verzonnen
    # worden. Een aanvraag die als verleend wordt geteld maakt onze
    # voorspelling beter dan zij is.
    check("aanvraag zonder uitkomst", a["uitkomst"], "")
    check("aanvraag zonder bezwaartermijn", a["bezwaar_tot"], "")

    # 3. WAT ONTBREEKT BLIJFT LEEG.
    leeg = velden_uit("een tekst zonder enig veld")
    check("leeg zaaknummer", leeg["zaaknummer"], "")
    check("lege uitkomst", leeg["uitkomst"], "")
    check("niets", velden_uit(""), velden_uit(None))

    # 4. DE BRIEF AAN DE AANVRAGER SCHRIJFT HET ANDERS DAN DE BEKENDMAKING.
    # Dit is de zin zoals pdftotext hem uit het besluit van Hatertseweg 338
    # haalt, met de standaardtekst over intrekken erachteraan die er ook
    # echt in staat. Eerst stond hier mijn eigen getypte zin, en die kwam uit
    # de bekendmaking; de brief zegt het anders en gaf daarom geen treffer.
    brief = ("Wij besloten over uw aanvraag. In deze brief en de bijlagen "
             "leest u ons besluit en wat u nog moet doen. U krijgt een "
             "omgevingsvergunning U ontvangt een omgevingsvergunning. U "
             "vindt deze in de bijlage. Maakt u binnen een jaar geen gebruik "
             "van de vergunning, dan kan deze worden ingetrokken.")
    b = velden_uit(brief)
    check("de brief telt ook als verleend", b["uitkomst"], "verleend")
    # De standaardtekst over intrekken mag de uitkomst niet omgooien. Dat is
    # een voorwaarde over de toekomst en geen afloop, en op het echte besluit
    # van Hatertseweg 338 maakte dit van een verleende vergunning een
    # "anders".
    check("intrekken is een voorwaarde, geen afloop", b["uitkomst"],
          "verleend")
    check("het signaal wordt wel gemeld", b["signalen"], "ingetrokken")

    # 4b. ZONDER BEWIJS GEEN OORDEEL.
    # Wij hebben nog nooit een weigering gezien en kennen de woorden niet.
    # Dus geen gok: onbekend, met het aangetroffen woord erbij, zodat de
    # eerste echte weigering opvalt.
    w = velden_uit("De gemeente heeft de aanvraag geweigerd. Dit besluit "
                   "namen wij op 1 maart 2026 voor de aanvraag met "
                   "zaaknummer Z2026-00000001.")
    check("geen gok bij een onbekende afloop", w["uitkomst"], "onbekend")
    check("signaal erbij", w["signalen"], "geweigerd")
    check("zaaknummer blijft", w["zaaknummer"], "Z2026-00000001")

    # 5. EEN DATUM IN WOORDEN WORDT EEN DATUM OM MEE TE REKENEN.
    check("datum", datum("13 november 2026"), "2026-11-13")
    check("datum met een cijfer", datum("1 maart 2026"), "2026-03-01")
    check("onbekende maand", datum("13 smurf 2026"), "")
    check("geen datum", datum("binnenkort"), "")

    # 5b. DE EINDDATUM UIT DE METADATA IS HET HARDE SIGNAAL.
    # Zo staat het in de broncode van de publicatie over Hatertseweg 338.
    bron = ('<meta name="DC.type" content="publicatie" />'
            '<meta name="OVERHEIDop.datumEindeReactietermijn" '
            'content="2026-11-13" />'
            '<meta name="OVERHEID.authority" content="Nijmegen" />')
    check("einde uit de metadata", einde_reactietermijn(bron), "2026-11-13")
    # Geen veld betekent geen stukken, en dat is iets anders dan een zin die
    # wij niet herkenden.
    check("zonder het veld", einde_reactietermijn(
        '<meta name="DC.type" content="publicatie" />'), "")
    check("lege broncode", einde_reactietermijn(""), "")
    # Een ander veld met een datum mag niet meetellen.
    check("ander datumveld", einde_reactietermijn(
        '<meta name="OVERHEIDop.datumOndertekening" content="2026-09-14" />'),
        "")

    # 6. ALLEEN WAT NU NOG OPEN STAAT.
    rijen = [{"gmb": "a", "bezwaar_tot": "2026-11-13"},
             {"gmb": "b", "bezwaar_tot": "2026-10-01"},
             {"gmb": "c", "bezwaar_tot": "2026-10-13"},
             {"gmb": "d", "bezwaar_tot": ""}]
    op = open_dossiers(rijen, "2026-10-13")
    check("open dossiers", [r["gmb"] for r in op], ["c", "a"])

    # 7. KOPPELEN OP ZAAKNUMMER EN NIET OP PAND.
    # Twee aanvragen voor hetzelfde pand horen bij hun eigen besluit. Dit is
    # het geval waar de koppeling op pand en datum de mist in gaat.
    aanvr = [{"zaaknummer": "Z1", "pand": "x", "datum": "2026-01-01"},
             {"zaaknummer": "Z2", "pand": "x", "datum": "2026-02-01"}]
    besl = [{"zaaknummer": "Z2", "pand": "x", "datum": "2026-03-01"}]
    paren, alleen_a, alleen_b = koppel(aanvr, besl)
    check("aantal paren", len(paren), 1)
    check("het juiste paar", paren[0][0], "Z2")
    check("aanvraag zonder besluit", [n for n, _ in alleen_a], ["Z1"])
    check("besluit zonder aanvraag", alleen_b, [])
    # ZONDER ZAAKNUMMER GEEN PAAR, MAAR WEL IN DE UITKOMST. Hier stond
    # (0, 0, 0) met als uitleg "raden is erger dan overslaan". Dat haalde twee
    # dingen door elkaar: niet raden, en niet kwijtraken. Van de 93 besluiten
    # in het archief dragen 53 geen zaaknummer, en die verdwenen zo volledig,
    # waardoor koppel_op_adres() ze nooit zag. Niet raden blijft: er komt geen
    # paar uit. Maar ze staan nu wel bij de losse.
    paren2, a2, b2 = koppel([{"zaaknummer": ""}], [{"zaaknummer": ""}])
    check("zonder nummer geen paar", len(paren2), 0)
    check("zonder nummer wel bij de losse", (len(a2), len(b2)), (1, 1))

    # KOPPELEN OP ADRES, OP HET ECHTE GEVAL VAN PONTANUSSTRAAT 42. Twee
    # publicaties over dezelfde splitsing, 118 dagen ertussen, en twee
    # verschillende zaaknummers van de gemeente.
    _a = {"adres": "Pontanusstraat 42", "datum": "2026-01-20",
          "zaaknummer": "Z2026-00000134", "soorten": ["splitsing"],
          "titel": "Aanvraag omgevingsvergunning voor het splitsen van een "
                   "woning naar twee zelfstandige appartementen, aan "
                   "Pontanusstraat 42, 6524EP Nijmegen"}
    _b = {"adres": "Pontanusstraat 42", "datum": "2026-05-18",
          "zaaknummer": "Z2025-00009314", "soorten": ["splitsing"],
          "titel": "Besluit voor het splitsen van de woning in 2 "
                   "zelfstandige appartementen, aan Pontanusstraat 42, "
                   "6524EP Nijmegen"}
    _p, _meer, _zonder = koppel_op_adres([_a], [_b])
    check("op adres verbonden", len(_p), 1)
    if _p:
        check("de koppeling draagt haar herkomst", _p[0]["gekoppeld_via"],
              "adres")
        check("de dagen tussen onze waarnemingen",
              _p[0]["dagen_tussen_waarnemingen"], 118)
        if _p[0]["gelijkenis"] < 0.8:
            fouten.append(f"de omschrijvingen van hetzelfde dossier lijken "
                          f"te weinig op elkaar: {_p[0]['gelijkenis']}")
    # TWEE AANVRAGEN OP EEN ADRES: NIETS VERBINDEN. Dit is precies de fout
    # waarom koppel() met opzet niet op adres koos.
    _p2, _meer2, _ = koppel_op_adres([_a, dict(_a, datum="2026-02-20")], [_b])
    check("bij twee kandidaten geen koppeling", (len(_p2), len(_meer2)),
          (0, 1))
    # Een aanvraag NA het besluit hoort er niet bij.
    _p3, _, _z3 = koppel_op_adres([dict(_a, datum="2026-06-01")], [_b])
    check("een latere aanvraag wordt niet gekoppeld", (len(_p3), len(_z3)),
          (0, 1))
    # Een ander signaalsoort op hetzelfde adres hoort er ook niet bij: een
    # dakkapel is geen splitsing.
    _p4, _, _z4 = koppel_op_adres(
        [dict(_a, soorten=["verbouwing"],
              titel="Aanvraag omgevingsvergunning voor een dakkapel, aan "
                    "Pontanusstraat 42, 6524EP Nijmegen")], [_b])
    check("een ander soort wordt niet gekoppeld", (len(_p4), len(_z4)),
          (0, 1))
    # En de kern zonder kop en zonder adres.
    check("de kern van een aanvraagtitel", kern_van(_a["titel"]),
          "splitsen van een woning naar twee zelfstandige appartementen")
    check("de kern van een besluittitel", kern_van(_b["titel"]),
          "splitsen van de woning in 2 zelfstandige appartementen")

    print(f"Proef besluit: {len(fouten)} fouten", file=sys.stderr)
    for f in fouten:
        print(f"FOUT {f}", file=sys.stderr)
    return 1 if fouten else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proef", action="store_true")
    ap.add_argument("--uit", default="", help="waar de velden worden bewaard")
    args = ap.parse_args()
    if args.proef:
        return proef()
    print("Deze module leest teksten die bijlagen.py ophaalt; draai hem via "
          "de workflow.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    # sys.exit en niet main(): anders is de exitcode altijd 0 en is de poort
    # in de workflow een formaliteit.
    sys.exit(main())
