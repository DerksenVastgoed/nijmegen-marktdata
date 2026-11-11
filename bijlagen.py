#!/usr/bin/env python3
"""
De tekeningen bij een bekendmaking opsporen, zonder studiezaal en met de hand.

WAAROM DIT BESTAAT. Het dossier uit het Digitaal Gebouwen Archief blijft
handwerk: die downloadlink geeft 403 vanaf elk netwerk buiten Marks eigen
computer, zie de kop van dossiermail.py. Maar de tekeningen die wij nodig
hebben zijn er ook langs een andere weg. De gemeente publiceert bij een
aanvraag de stukken mee, geanonimiseerd, als externe bijlage bij de officiele
bekendmaking. Die bekendmakingen halen wij al elke ochtend op.

Dat is de route die zichzelf bijhoudt: geen aanvraag per pand, geen mail,
geen link van drie dagen. Elke aanvraag die langskomt brengt zijn eigen
tekeningen mee.

WAT DEZE ROUTE OPLEVERDE, EN WAAROM HIJ NIET DEUGT.

Op 13 oktober over alle 148 publicaties uit ons archief gedraaid. De uitkomst
is geen tekort maar een structureel antwoord:

  93 aanvragen   0 stukken
  48 besluiten   3 stukken, alle drie een "Afwijkvergunning"
   7 overig      0 stukken

Geen enkele tekening. En de drie stukken die er wel zijn, zijn geen
tekeningen maar het BOPA-besluit: dat bestaat alleen als een plan van het
omgevingsplan afwijkt, en dat verklaart waarom het er drie zijn en niet
achtenveertig. De bekendmaking draagt de tekeningen dus niet bij ongeluk
niet; zij draagt ze principieel niet. De stukken zijn alleen via inzage te
zien, en dat is de route die Mark met de hand heeft gelopen.

Deze module blijft staan omdat hij dat antwoord geeft en blijft geven: komt
er ooit wel een tekening bij een bekendmaking, dan ziet hij dat. Maar een
corpus bouwen langs deze weg gaat niet.

EN DE ZIN DIE ANDERS SUGGEREERT. In de bekendmaking van een aanvraag staat
letterlijk: "U kunt nu alvast de aanvraag bekijken en hierover vragen
stellen. Bekijken doet u via de link op deze pagina." Die link staat niet in
de broncode van de pagina. Nagekeken of hij wordt ingeladen: de pagina roept
inderdaad scripts aan die links nabezorgen, maar dat zijn
/Referendum/GetReferendumLinks, /BWB/GetBWBLinks en /CVDR/GetCVDRLinks, en
die gaan over wetgeving en niet over de stukken bij deze aanvraag.

Wat de bekendmaking wel geeft en wat wij niet gebruikten: het kenmerk van de
zaak bij de gemeente, zoals Z2026-00005538 voor Staringstraat 2 en
Z2025-00011390 voor Biezenstraat 110. Dat is het nummer waaronder de
gemeente het dossier kent, en het staat in elke aanvraagpublicatie.

WAT NOG NIET VASTSTAAT. Hoe die bijlagen in de SRU staan en welke url ze
hebben, weet ik niet, en van buiten een run is het niet te bevragen: de
proxy van de werkomgeving weigert repository.overheid.nl. Daarom probeert
deze module drie vormen in een ronde en meldt van alle drie wat ze opleveren.
Dat scheelt runs, net als bij de drie koppen in dossiermail.py.

TWEE GEVALLEN WAARVAN WIJ HET ANTWOORD AL KENNEN, en daarom bruikbaar als
toets in plaats van als verkenning:

  gmb-2026-463651  Staringstraat 2, verbouwen pand naar 3 appartementen
  gmb-2026-460303  Biezenstraat 110, splitsen woning met garage tot 2 woningen

Van beide staan de stukken op een computer waar wij ze hebben gezien, met
namen als "1038-04geb Staringstraat2 260922-geanonimiseerd.pdf". Vindt deze
module diezelfde namen, dan klopt de route van begin tot eind. Vindt hij er
geen, dan is dat geen "er zijn geen bijlagen" maar "wij kijken verkeerd".

WAT HET NIET DOET. Geen enkel bestand komt in de repo. De stukken gaan naar
een tijdelijke map en die wordt opgeruimd. Op de tekeningen rust auteursrecht
en deze repo is publiek. Wat wij eruit meten, bijvoorbeeld "op deze laag is
45,3 m2 woonfunctie en daarvan 42,8 m2 zelfstandige woning", is onze eigen
waarneming en mag wel.
"""

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

# EEN IMPLEMENTATIE PER AFSPRAAK. beschrijf_bestand meet van een bestand de
# omvang, de soort, het aantal bladzijden en of er een tekstlaag in zit. Tot
# 11 november stond die in dossiermail.py en leende deze module hem. Sinds de
# splitsing staat deze module in de openbare repo nijmegen-marktdata en
# dossiermail.py (die de mailbox leest) in de privé brief; een openbare module
# kan niet uit een privé module lenen. Dus staat hij nu hier, en leent
# dossiermail.py hem van deze module.


def beschrijf_bestand(pad):
    """Wat voor bestand is dit, en wat zit erin? Zonder de inhoud te tonen."""
    naam = os.path.basename(pad)
    bytes_ = os.path.getsize(pad)
    soort = (os.path.splitext(naam)[1] or "").lower().lstrip(".") or "zonder"
    uit = {"naam": naam, "bytes": bytes_, "soort": soort}
    if soort == "pdf":
        try:
            with open(pad, "rb") as f:
                ruw = f.read()
            uit["bladzijden"] = ruw.count(b"/Type /Page") + ruw.count(b"/Type/Page")
            # Staat er tekst in, of is het een scan? Dat bepaalt of wij maten
            # kunnen uitlezen of de tekening moeten bekijken.
            uit["heeft_tekstlaag"] = (b"/Font" in ruw)
        except Exception as e:
            uit["fout"] = f"{type(e).__name__}"
    return uit

SRU_URL = "https://repository.overheid.nl/sru"
REPO = "https://repository.overheid.nl"
ZOEK = "https://zoek.officielebekendmakingen.nl"

# De hosts waar wij een bijlage vandaan halen. Net als bij dossiermail.py een
# vergelijking op de host zelf en op echte subdomeinen, niet op "staat de naam
# erin": https://repository.overheid.nl.kwaad.nl zou daar doorheen glippen.
TOEGESTANE_HOSTS = ("repository.overheid.nl", "zoek.officielebekendmakingen.nl",
                    "repository.officiele-overheidspublicaties.nl")

MAX_BIJLAGE = 60 * 1024 * 1024
KOP = {"User-Agent": "derksenvastgoed-monitor"}

# DE NAAM BEPAALT DE VOLGORDE, DE INHOUD BEPAALT WAT HET IS.
#
# Eerst stond hier een toets op de bestandsnaam die zei of iets een
# plattegrond was. Nagemeten op de 60 namen die wij echt hebben gezien, uit
# zeven dossiers: 16 treffers, waarvan 6 geen plattegrond. "Erfafscheidingen
# aanzichten met bebouwing" kwam binnen omdat "bebouwing" het stuk "geb"
# bevat, en gevelaanzichten, een situatietekening en een muurdetail kwamen
# binnen op "nieuw". Andersom bleven "260928-5907-A1-gewenst" en
# "A1-vergund" buiten, terwijl dat juist de tekeningen van de oude en de
# nieuwe toestand zijn.
#
# Een naam die zo vaak miswijst, hoort geen oordeel te vellen. Hij bepaalt
# alleen welk bestand wij als eerste openen; wat het is, blijkt uit de tekst
# erin. Dat kunnen wij toch al lezen, want de tekeningen hebben een
# tekstlaag.
NAAM_BELOOFT_VEEL = ("plattegrond", "begane", "verdieping", "kelder",
                     "bouwkundig", "gewenst", "vergund", "nieuw", "bestaand")
NAAM_BELOOFT_WEINIG = ("bodemonderzoek", "flora", "fauna", "quickscan",
                       "berekening", "bouwbesluit", "brandveiligheid",
                       "motivering", "rapportage", "folder", "checklist",
                       "checlist", "isolatie", "besluit", "verzoekpdf",
                       "parkeerberekening", "foto", "detailboek", "waterberging")

# Waaraan een plattegrond in zijn eigen tekst te herkennen is: een laagnaam
# en iets dat op een ruimte of een maat lijkt. Een gevelaanzicht noemt wel de
# laag maar geen woonkamer, een bouwbesluittoets noemt wel m2 maar geen laag.
# Beide woorden zijn dus nodig, niet een van de twee.
LAAGWOORDEN = ("begane grond", "verdieping", "kelder", "souterrain", "zolder")
RUIMTEWOORDEN = ("woonkamer", "slaapkamer", "badkamer", "keuken", "overloop",
                 "berging", "hal", "entree", "toilet", "woonfunctie")


def host_van(url):
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def toegestaan(url):
    h = host_van(url)
    if not h or not (url or "").lower().startswith("https://"):
        return False
    return any(h == t or h.endswith("." + t) for t in TOEGESTANE_HOSTS)


def voorrang(naam):
    """
    In welke volgorde wij de bijlagen openen. Geen oordeel, een volgorde.

    0 belooft veel, 1 zegt niets, 2 belooft weinig. Zit een dossier vol, dan
    openen wij de nullen eerst; de tweeen gaan niet overboord, want een naam
    die weinig belooft kan er toch een zijn, en dat hebben wij gezien.

    WAT ER GEBEURT ALS EEN NAAM IN BEIDE LIJSTEN VALT. Dan geeft hij 1, net
    als een naam die niets zegt. Dat is geen compromis maar een meting: van
    de 60 namen die wij echt hebben gezien valt er geen enkele in beide
    lijsten. De volgorde van de twee toetsen maakt dus voor niets uit wat wij
    kennen, en ik heb geprobeerd die volgorde na te meten door hem om te
    draaien: er ging niets rood, want er was niets om rood van te worden.
    Een naam verzinnen waarop het wel uitmaakt en daar de regel op bouwen is
    precies hoe je een toets krijgt die nooit iets vangt. Dus kiest deze
    functie niet: zo'n naam spreekt zichzelf tegen en zegt daarmee niets.
    verken() telt ze, zodat de eerste echte in een issue opduikt en wij de
    regel dan kunnen afleiden uit het geval in plaats van uit een bedenksel.
    """
    n = (naam or "").lower()
    veel = any(w in n for w in NAAM_BELOOFT_VEEL)
    weinig = any(w in n for w in NAAM_BELOOFT_WEINIG)
    if veel and weinig:
        return 1
    if weinig:
        return 2
    if veel:
        return 0
    return 1


def telling_tegenspraak(namen):
    """Hoeveel namen in beide lijsten vallen. Zie voorrang() voor waarom."""
    n = 0
    for naam in namen:
        k = (naam or "").lower()
        if (any(w in k for w in NAAM_BELOOFT_VEEL)
                and any(w in k for w in NAAM_BELOOFT_WEINIG)):
            n += 1
    return n


def is_plattegrond(tekst):
    """Of de tekst in een bestand die van een plattegrond is. Zie de kop."""
    t = (tekst or "").lower()
    return (any(w in t for w in LAAGWOORDEN)
            and any(w in t for w in RUIMTEWOORDEN))


def tekst_van(pad):
    """De tekstlaag van een PDF, of een lege string. Zonder uitzondering."""
    try:
        import subprocess
        r = subprocess.run(["pdftotext", "-layout", "-q", pad, "-"],
                           capture_output=True, timeout=120)
        return (r.stdout or b"").decode("utf-8", "replace")
    except Exception:
        return ""


def kandidaten(gmb):
    """
    De drie vormen waarin de bijlagen kunnen staan, elk met een eigen vraag.

    Welke het is weet ik nog niet, en het is van buiten een run niet te
    bevragen. Daarom alle drie in een ronde, en de samenvatting zegt wat elk
    opleverde. Een vorm die niets geeft is een antwoord en geen storing.
    """
    jaar = gmb.split("-")[1] if gmb.count("-") >= 2 else ""
    return [
        ("html van de publicatie",
         f"{REPO}/frbr/officielepublicaties/gmb/{jaar}/{gmb}/1/html/{gmb}.html"),
        ("metadata van de publicatie",
         f"{REPO}/frbr/officielepublicaties/gmb/{jaar}/{gmb}/1/metadata/metadata.xml"),
        ("zoekpagina", f"{ZOEK}/{gmb}.html"),
    ]


def haal(url, binair=False):
    """Een pagina of bestand ophalen. Geeft (inhoud, fout) terug."""
    if not toegestaan(url):
        return None, "host niet toegestaan"
    try:
        verzoek = urllib.request.Request(url, headers=KOP)
        with urllib.request.urlopen(verzoek, timeout=90) as a:
            ruw = a.read(MAX_BIJLAGE + 1)
        if len(ruw) > MAX_BIJLAGE:
            return None, f"groter dan {MAX_BIJLAGE} bytes"
        return (ruw if binair else ruw.decode("utf-8", "replace")), ""
    except Exception as e:
        code = getattr(e, "code", None)
        # Alleen het soort fout en de code: de tekst bevat de url, en de
        # samenvatting komt in een issue in een publieke repo.
        return None, f"{type(e).__name__}" + (f" {code}" if code else "")


GMB = re.compile(r"(gmb-\d{4}-\d+)", re.I)
EXB = re.compile(r"(exb-\d{4}-\d+)", re.I)


def andere_publicatie(url, basis):
    """
    Of een link naar een ANDERE bekendmaking wijst, en dus geen bijlage is.

    WAT HIER GEBEURDE. De eerste ronde meldde bij beide publicaties een
    bijlage die in werkelijkheid gmb-2015-16426.pdf was: een link die op elke
    publicatiepagina staat, naar het besluit over de bekendmakingen zelf uit
    2015. Die telde mee, en dus leek een publicatie zonder bijlagen er een
    met een te hebben. Een valse vondst is erger dan geen vondst, want hij
    kost een download en zet de telling in het issue scheef.

    Het is geen uitzondering op nummer: elke link naar een gmb die niet DEZE
    gmb is, is een verwijzing en geen bijlage. Zo valt de volgende
    standaardlink er ook onder, ook als het nummer verandert.
    """
    # DE LAATSTE IN DE URL, NIET DE EERSTE.
    #
    # De link op de pagina is relatief: href="gmb-2015-16426.pdf". Die wordt
    # geplakt achter het pad van deze publicatie, en dan staat er
    #   /frbr/officielepublicaties/gmb/2026/gmb-2026-474906/1/html/gmb-2015-16426.pdf
    # Daar staan dus twee nummers in. Met de eerste vergelijken betekent deze
    # publicatie met zichzelf vergelijken, en dan glipt elke standaardlink
    # erdoor: in de ronde over 148 publicaties deed hij dat 133 keer.
    #
    # Mijn proef zag dat niet, want die gebruikte een absolute url met maar
    # een nummer erin. Een geval dat niet voorkomt op het web waar het over
    # gaat, toetst niets. Het geval hieronder is het pad zoals het er echt
    # uitkwam.
    hier = GMB.search(basis or "")
    allemaal = GMB.findall(url or "")
    if not allemaal:
        return False
    daar = allemaal[-1]
    return not hier or daar.lower() != hier.group(1).lower()


def exb_urls(iets):
    """
    De vormen waarin een externe bijlage kan staan, als lijst.

    WAAROM NIET GEWOON DE HREF. De eerste ronde haalde drie bijlagen op en
    kreeg 404, 404 en 400. De metadata geeft een waarde als
    "Afwijkvergunning|exb-2026-34477": een label en een nummer met een
    streep ertussen. Daar een url van maken door hem aan de basis te plakken
    levert onzin op.

    WAAROM EEN LIJST EN GEEN VORM. Ik weet niet welke vorm de goede is, en
    van buiten een run is het niet te bevragen. Een vorm kiezen op gevoel en
    hem dan als waarheid opschrijven is hoe je een module krijgt die het bij
    het eerste afwijkende geval begeeft. Dus probeert de verkenning ze alle
    vier in een ronde en meldt welke het werd. Zodra dat bekend is, kan deze
    lijst krimpen tot de vorm die werkt.
    """
    m = EXB.search(iets or "")
    if not m:
        return []
    nr = m.group(1).lower()
    b = "https://repository.officiele-overheidspublicaties.nl/externebijlagen"
    return [f"{b}/{nr}/1/bijlage/{nr}.pdf",
            f"{b}/{nr}/1/{nr}.pdf",
            f"{b}/{nr}/{nr}.pdf",
            f"{b}/{nr}.pdf"]


def alle_links(tekst, basis):
    """
    Elke link op de pagina, samengevat per host. Geen oordeel, een telling.

    WAAROM DIT ER IS. De bekendmaking zelf zegt dat de aanvraag "via de link
    op deze pagina" is in te zien, maar de pdf-versie laat niet zien waarheen
    die wijst. Zoeken op "exb-" zou een link naar een portaal van de gemeente
    missen, en dan zou de verkenning "geen bijlagen" melden terwijl ze er wel
    zijn. Dat is de stille leugen die wij juist niet willen.

    Van elke link blijven alleen de host en de vorm van het pad over, nooit
    de queryreeks: daar kan een sleutel in staan en deze samenvatting komt in
    een issue in een publieke repo.
    """
    per_host = {}
    for m in re.finditer(r'href="([^"]+)"', tekst or "", re.I):
        vol = urllib.parse.urljoin(basis, m.group(1))
        d = urllib.parse.urlparse(vol)
        if d.scheme not in ("http", "https"):
            continue
        h = (d.hostname or "").lower()
        stukken = [s for s in (d.path or "").split("/") if s]
        vorm = "/" + "/".join(stukken[:2]) + ("/..." if len(stukken) > 2 else "")
        p = per_host.setdefault(h, {"host": h, "aantal": 0, "vormen": set(),
                                    "pdf": 0})
        p["aantal"] += 1
        p["vormen"].add(vorm[:60])
        if (d.path or "").lower().endswith(".pdf"):
            p["pdf"] += 1
    # URL'S DIE IN DE LOPENDE TEKST STAAN EN GEEN HREF ZIJN.
    # De bekendmaking zegt dat de aanvraag "via de link op deze pagina" is in
    # te zien. Staat die als gewone tekst, dan vindt een zoektocht naar href
    # hem niet, en meldt de verkenning "geen bijlagen" terwijl er een portaal
    # is. Die kaal geschreven url's horen er dus bij.
    kaal = re.sub(r"<[^>]+>", " ", tekst or "")
    for m in re.finditer(r"(?:https?://|www\.)[\w.-]+(?:/[\w./%-]*)?", kaal):
        vol = m.group(0)
        if not vol.lower().startswith("http"):
            vol = "https://" + vol
        d = urllib.parse.urlparse(vol)
        h = (d.hostname or "").lower()
        if not h:
            continue
        stukken = [s for s in (d.path or "").split("/") if s]
        vorm = "/" + "/".join(stukken[:2]) + ("/..." if len(stukken) > 2 else "")
        p = per_host.setdefault(h, {"host": h, "aantal": 0, "vormen": set(),
                                    "pdf": 0, "in_tekst": 0})
        p["aantal"] += 1
        p.setdefault("in_tekst", 0)
        p["in_tekst"] += 1
        p["vormen"].add(vorm[:60])

    uit = []
    for p in per_host.values():
        p["vormen"] = sorted(p["vormen"])[:4]
        p.setdefault("in_tekst", 0)
        uit.append(p)
    return sorted(uit, key=lambda p: -p["aantal"])


def bijlagen_uit_html(tekst, basis):
    """
    De links naar externe bijlagen uit een publicatiepagina.

    Een bijlage bij een bekendmaking heet exb-<jaar>-<nummer>. De naam die de
    lezer ziet staat in de linktekst, en de bestandsnaam in de url. Beide
    worden meegenomen, want de linktekst zegt vaak waar de tekening over gaat
    en de bestandsnaam niet altijd.
    """
    uit = []
    if not tekst:
        return uit
    for m in re.finditer(r'href="([^"]+)"[^>]*>([^<]{0,160})</a>', tekst,
                         re.I):
        href, woorden = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
        if not re.search(r"(exb-|externebijlagen|\.pdf)", href, re.I):
            continue
        vol = urllib.parse.urljoin(basis, href)
        if not toegestaan(vol) or andere_publicatie(vol, basis):
            continue
        uit.append({"url": vol, "tekst": woorden,
                    "naam": urllib.parse.unquote(
                        os.path.basename(urllib.parse.urlparse(vol).path))})
    # Dubbele links komen voor als dezelfde bijlage twee keer op de pagina
    # staat. De eerste wint; de volgorde van de pagina blijft zo staan.
    gezien, net = set(), []
    for b in uit:
        if b["url"] in gezien:
            continue
        gezien.add(b["url"])
        net.append(b)
    return net


def bijlagen_uit_metadata(tekst, basis):
    """Hetzelfde, maar uit de metadata-xml: daar staan de bijlagen als item."""
    uit = []
    if not tekst:
        return uit
    try:
        wortel = ET.fromstring(tekst)
    except Exception:
        # Geen geldige xml is een antwoord: deze vorm bestaat dan niet.
        return uit
    for el in wortel.iter():
        for waarde in list(el.attrib.values()) + ([el.text] if el.text else []):
            if not isinstance(waarde, str):
                continue
            w = waarde.strip()
            if not re.search(r"(exb-|externebijlagen)", w, re.I):
                continue
            vol = urllib.parse.urljoin(basis, w) if not w.startswith("http") else w
            if toegestaan(vol):
                uit.append({"url": vol, "tekst": "",
                            "naam": urllib.parse.unquote(
                                os.path.basename(
                                    urllib.parse.urlparse(vol).path))})
    gezien, net = set(), []
    for b in uit:
        if b["url"] not in gezien:
            gezien.add(b["url"])
            net.append(b)
    return net


def verken(gmb, haal_bestanden=False):
    """Een publicatie langs de drie vormen, en wat elk oplevert."""
    vind = {"gmb": gmb, "vormen": [], "bijlagen": [], "bestanden": []}
    alle = []
    for naam, url in kandidaten(gmb):
        tekst, fout = haal(url)
        if fout:
            vind["vormen"].append({"vorm": naam, "uitkomst": fout, "aantal": 0})
            continue
        gevonden = (bijlagen_uit_metadata(tekst, url) if "metadata" in naam
                    else bijlagen_uit_html(tekst, url))
        vind["vormen"].append({"vorm": naam, "uitkomst": "gelezen",
                               "tekens": len(tekst), "aantal": len(gevonden),
                               # Alle links erbij, niet alleen de herkende.
                               # Anders leest "0 bijlagen" als "die zijn er
                               # niet", terwijl wij misschien de verkeerde
                               # vorm zoeken.
                               "hosts": alle_links(tekst, url)})
        alle.extend(gevonden)
    gezien = set()
    for b in alle:
        if b["url"] not in gezien:
            gezien.add(b["url"])
            vind["bijlagen"].append(b)
    # Namen die zichzelf tegenspreken: nul in alles wat wij hebben gezien.
    # Duikt er hier een op, dan hebben wij eindelijk een echt geval om de
    # regel op te bouwen. Zie voorrang().
    vind["tegenspraak"] = telling_tegenspraak(
        [b["naam"] + " " + b["tekst"] for b in vind["bijlagen"]])
    if not haal_bestanden:
        return vind
    map_ = tempfile.mkdtemp(prefix="bijlage-")
    try:
        volgorde = sorted(vind["bijlagen"],
                          key=lambda b: voorrang(b["naam"] + " " + b["tekst"]))
        for b in volgorde[:25]:
            # Eerst de link zelf, dan de opgebouwde vormen. De eerste ronde
            # gaf 404 op de link uit de metadata, want daar staat een label
            # met een nummer en geen url.
            pogingen = [("de link zelf", b["url"])]
            for i, u in enumerate(exb_urls(b["url"] + " " + b["naam"]
                                           + " " + b["tekst"]), 1):
                if u != b["url"]:
                    pogingen.append((f"vorm {i}", u))
            ruw, fout, welke = None, "", ""
            mislukt = []
            for naam_vorm, u in pogingen:
                ruw, fout = haal(u, binair=True)
                if not fout:
                    welke = naam_vorm
                    break
                mislukt.append(f"{naam_vorm}: {fout}")
            if fout:
                vind["bestanden"].append({"naam": b["naam"],
                                          "fout": "; ".join(mislukt[:4])})
                continue
            b["vorm_die_werkte"] = welke
            pad = os.path.join(map_, re.sub(r"[^\w.-]", "_", b["naam"])[:80]
                               or "bijlage.bin")
            with open(pad, "wb") as f:
                f.write(ruw)
            d = beschrijf_bestand(pad)
            d["tekst"] = b["tekst"][:70]
            d["vorm"] = welke
            d["voorrang"] = voorrang(b["naam"] + " " + b["tekst"])
            # De naam belooft, de inhoud beslist. Beide gaan mee, zodat wij
            # kunnen zien waar de naam miswijst in plaats van het te geloven.
            d["plattegrond"] = (is_plattegrond(tekst_van(pad))
                                if d.get("soort") == "pdf"
                                and d.get("heeft_tekstlaag") else False)
            vind["bestanden"].append(d)
    finally:
        shutil.rmtree(map_, ignore_errors=True)
    return vind


def samenvatting(bevindingen, vandaag=None, niet_gehaald=0):
    """
    Wat de verkenning opleverde, als markdown, zonder iets uit de stukken.

    Alleen bestandsnamen zoals de gemeente ze publiceert, omvang, soort,
    bladzijden en of er een tekstlaag in zit. Dat is metadata en niet het werk
    waarop auteursrecht rust, en het is het enige dat nodig is om te weten of
    deze route bruikbaar is.
    """
    import datetime as _dt
    nu = (vandaag or _dt.datetime.now(_dt.timezone.utc)).strftime(
        "%Y-%m-%d %H:%M UTC")
    r = [f"## Bijlagen bij bekendmakingen verkend op {nu}", ""]
    if not bevindingen:
        r.append("Geen enkele publicatie onderzocht. Dat is iets anders dan "
                 "een publicatie zonder bijlagen: er is niet gekeken.")
        return "\n".join(r) + "\n"

    # DE OPTELLING EERST. Bij een brede ronde is dit het getal dat telt:
    # hoeveel van de publicaties die wij volgen brengen werkelijk een stuk
    # mee. Staat dat onderaan achter 138 kopjes, dan leest niemand het.
    met = [b for b in bevindingen if b.get("bijlagen")]
    zonder = [b for b in bevindingen if not b.get("bijlagen")]
    stuk = sum(len(b.get("bijlagen") or []) for b in bevindingen)
    gelezen = [d for b in bevindingen for d in (b.get("bestanden") or [])
               if not d.get("fout")]
    plat = [d for d in gelezen if d.get("plattegrond")]
    r.append(f"**{len(bevindingen)} publicaties onderzocht.** "
             f"{len(met)} daarvan dragen samen {stuk} stuk(ken) mee, "
             f"{len(zonder)} dragen niets mee.")
    if niet_gehaald:
        # Half gekeken en helemaal gekeken mogen niet hetzelfde lezen.
        r.append("")
        r.append(f"**{niet_gehaald} publicaties zijn niet meer gehaald**: het "
                 f"tijdbudget was op. Die staan dus niet in de tellingen "
                 f"hierboven, en over hun bijlagen zegt deze ronde niets.")
    if gelezen:
        r.append("")
        r.append(f"Van de {len(gelezen)} stukken die wij hebben kunnen "
                 f"openen zijn er {len(plat)} een plattegrond: een blad met "
                 f"zowel een laagnaam als een ruimtenaam erop. Daar zijn de "
                 f"maten per laag uit te lezen.")
    r.append("")
    # Bij een brede ronde alleen de publicaties die iets opleverden. Een
    # publicatie zonder bijlagen staat in de optelling hierboven; haar
    # hostlijst erbij zetten maakt het issue onleesbaar en voegt niets toe.
    breed = len(bevindingen) > 5
    if breed and zonder:
        r.append(f"_De {len(zonder)} publicaties zonder bijlage staan "
                 f"hieronder niet uitgeschreven; zij zijn wel onderzocht._")
        r.append("")
        bevindingen = met

    for b in bevindingen:
        r.append(f"### {b['gmb']}")
        r.append("")
        for v in b.get("vormen", []):
            extra = (f", {v.get('tekens', 0)} tekens" if v.get("tekens")
                     else "")
            r.append(f"- {v['vorm']}: {v['uitkomst']}{extra}, "
                     f"{v.get('aantal', 0)} bijlage(n)")
            # Elke host waarheen de pagina linkt, ook de hosts die wij niet
            # herkennen. Zonder dit leest "0 bijlagen" als "die zijn er niet".
            # Bij een brede ronde valt deze lijst weg: 138 keer dezelfde
            # standaardhosts zegt niets en verdringt wat wel telt.
            for h in ([] if breed else (v.get("hosts") or [])[:8]):
                tekst_bij = (f", {h['in_tekst']} in de lopende tekst"
                             if h.get("in_tekst") else "")
                r.append(f"    - {h['host']}: {h['aantal']} link(s), "
                         f"{h['pdf']} pdf{tekst_bij}, "
                         f"vorm {', '.join(h['vormen'])}")
        if b.get("js"):
            r.append("")
            r.append("**Waar komt de ingeladen link vandaan:**")
            r.append("")
            r.append("```")
            for _x in b["js"][:25]:
                r.append(_x)
            r.append("```")
            r.append("")
        if b.get("metadata"):
            r.append("")
            r.append("<details><summary>de metadata van de publicatie</summary>")
            r.append("")
            r.append("```")
            r.append(b["metadata"])
            r.append("```")
            r.append("</details>")
            r.append("")
        if b.get("tekst"):
            r.append("")
            r.append("<details><summary>de tekst van de publicatie</summary>")
            r.append("")
            r.append("```")
            r.append(b["tekst"])
            r.append("```")
            r.append("</details>")
            r.append("")
        bij = b.get("bijlagen") or []
        r.append(f"- samen {len(bij)} unieke bijlage(n)")
        if b.get("tegenspraak"):
            r.append(f"- **{b['tegenspraak']} naam/namen spreken zichzelf "
                     f"tegen** (beloven veel en weinig tegelijk). Dat was "
                     f"nog nooit voorgekomen; hier is eindelijk een echt "
                     f"geval om de regel op te bouwen.")
        if bij and not b.get("bestanden"):
            r.append("")
            for x in bij[:25]:
                r.append(f"  - `{x['naam'][:70]}`"
                         + (f" . {x['tekst'][:60]}" if x["tekst"] else ""))
        if b.get("bestanden"):
            r.append("")
            r.append("| bestand | bytes | soort | bladzijden | tekstlaag | "
                     "plattegrond |")
            r.append("|---|---:|---|---:|---|---|")
            for d in b["bestanden"][:25]:
                if d.get("fout"):
                    r.append(f"| {d['naam'][:46]} | | niet gelukt: "
                             f"{d['fout']} | | | |")
                    continue
                r.append(f"| {d['naam'][:46]} | {d['bytes']} | {d['soort']} | "
                         f"{d.get('bladzijden', '')} | "
                         f"{'ja' if d.get('heeft_tekstlaag') else 'nee' if d.get('soort') == 'pdf' else ''} | "
                         f"{'ja' if d.get('plattegrond') else ''} |"
                         + (f" via {d['vorm']}" if d.get("vorm") else ""))
            pdfs = [d for d in b["bestanden"] if d.get("soort") == "pdf"]
            met = [d for d in pdfs if d.get("heeft_tekstlaag")]
            plat = [d for d in b["bestanden"] if d.get("plattegrond")]
            if pdfs:
                r.append("")
                r.append(f"Van {len(pdfs)} PDF's hebben {len(met)} een "
                         f"tekstlaag; {len(plat)} lijken op een plattegrond. "
                         f"Met een tekstlaag zijn de maten uit te lezen "
                         f"zonder de tekening te bekijken.")
        r.append("")
    r.append("_Geen enkel bestand staat in de repo: alles is in een "
             "tijdelijke map geopend en opgeruimd._")
    return "\n".join(r) + "\n"


def proef():
    """Nameten wat deze module belooft, zonder netwerk."""
    fouten = []

    def check(naam, echt, verwacht):
        if echt != verwacht:
            fouten.append(f"{naam}: {echt!r}, verwacht {verwacht!r}")

    # 1. DE HOSTCONTROLE KIJKT NAAR DE HOST EN NIET NAAR DE NAAM.
    gevallen = [
        ("https://repository.overheid.nl/frbr/x.html", True),
        ("https://zoek.officielebekendmakingen.nl/gmb-2026-1.html", True),
        ("https://repository.officiele-overheidspublicaties.nl/exb.pdf", True),
        ("https://repository.overheid.nl.kwaad.nl/exb.pdf", False),
        ("https://kwaad.nl/?x=repository.overheid.nl", False),
        ("http://repository.overheid.nl/x.html", False),
        ("https://overheid.nl/x.html", False),
        ("", False),
    ]
    for url, verwacht in gevallen:
        if toegestaan(url) != verwacht:
            fouten.append(f"toegestaan({url!r}) geeft {toegestaan(url)}, "
                          f"verwacht {verwacht}")

    # 2. DE DRIE VORMEN STAAN ER ALLE DRIE, met het jaar uit het nummer.
    k = kandidaten("gmb-2026-463651")
    check("aantal vormen", len(k), 3)
    if not any("/2026/" in u for _n, u in k):
        fouten.append(f"het jaar komt niet uit het nummer: {k}")

    # 3. BIJLAGEN UIT HTML, en niets anders dan bijlagen.
    html = ('<a href="/frbr/.../exb-2026-99/1/bijlage/'
            '1038-04geb%20Staringstraat2%20260922-geanonimiseerd.pdf">'
            'Bouwkundige tekening nieuw</a>'
            '<a href="https://kwaad.nl/exb-2026-1.pdf">kwaadaardig</a>'
            '<a href="/over-deze-site.html">Over deze site</a>')
    uit = bijlagen_uit_html(html, "https://repository.overheid.nl/frbr/x.html")
    check("aantal bijlagen uit html", len(uit), 1)
    if uit:
        check("naam ontkomt aan %20", uit[0]["naam"],
              "1038-04geb Staringstraat2 260922-geanonimiseerd.pdf")
        check("linktekst", uit[0]["tekst"], "Bouwkundige tekening nieuw")

    # 4. DE NAAM BEPAALT DE VOLGORDE EN VELT GEEN OORDEEL.
    # Alle namen hieronder zijn namen die wij echt hebben gezien, uit zeven
    # dossiers. Een patroon bouwen tegen een naam die niemand schrijft, vangt
    # niets.
    for naam in ("Plattegronden - Nieuwe situatie - Kelder en BG-Vloer.pdf",
                 "260914-BD70-DO-03 nieuw-geanonimiseerd.pdf",
                 "260928-5907-A1-vergund-geanonimiseerd.pdf"):
        check(f"voorrang {naam[:28]}", voorrang(naam), 0)
    for naam in ("Quickscan flora en fauna Biezenstraat 110.pdf",
                 "checlist-natuurinclusief-bouwen-geanonimiseerd.pdf",
                 "verzoekpdf-2026092201714-geanonimiseerd.pdf",
                 "1038-Parkeerberekening 260921-geanonimiseerd.pdf"):
        check(f"voorrang {naam[:28]}", voorrang(naam), 2)
    # Een naam die niets belooft hoort in het midden te vallen en niet
    # achteraan: "A3 (L)-trappenhuis" zegt niets, maar is wel een tekening.
    check("voorrang trappenhuis",
          voorrang("260928-5907-A3 (L)-trappenhuis-geanonimiseerd.pdf"), 1)
    # Een naam die zichzelf tegenspreekt zegt niets en krijgt daarom 1. Dit
    # is het enige geval hier dat niet van een echt bestand komt: van de 60
    # namen die wij hebben gezien valt er geen in beide lijsten. Daarom kiest
    # de functie niet en telt verken() ze, zodat de eerste echte opduikt.
    check("voorrang tegenspraak",
          voorrang("Berekening plattegronden-geanonimiseerd.pdf"), 1)
    if telling_tegenspraak(["Berekening plattegronden.pdf", "nieuw.pdf"]) != 1:
        fouten.append("een naam die zichzelf tegenspreekt wordt niet geteld")

    # 5. DE INHOUD BESLIST WAT HET IS.
    # De twee gevallen hieronder zijn afgelezen van twee echte stukken bij de
    # aanvraag voor Staringstraat 2: het blad met de plattegronden en het blad
    # met de bouwkundige details. Op het eerste staan laagnamen en
    # ruimtenamen, op het tweede geen van beide. Een gevelaanzicht noemt wel
    # de laag en geen ruimte; daarom moeten het er twee zijn en niet een.
    if not is_plattegrond("begane grond nieuw  woonkamer 20.9 m2  "
                          "slaapkamer 16.4 m2  entree"):
        fouten.append("een blad met laagnamen en ruimtenamen geldt niet als "
                      "plattegrond")
    for tekst, waarom in (
            ("detail dakrand houtvezelisolatie dampremmende laag", "details"),
            ("voorgevel achtergevel 1e verdieping 2e verdieping peil",
             "een gevelaanzicht noemt wel de laag maar geen ruimte"),
            ("gebruiksoppervlakte 58,31 m2 brandcompartiment",
             "een bouwbesluittoets noemt wel maten maar geen laag"),
            ("", "leeg")):
        if is_plattegrond(tekst):
            fouten.append(f"ten onrechte een plattegrond ({waarom})")

    # 4b. ELKE LINK WORDT GETELD, OOK NAAR EEN HOST DIE WIJ NIET KENNEN, EN
    # DE QUERYREEKS KOMT ER NOOIT IN. De bekendmaking zegt dat de stukken
    # "via de link op deze pagina" zijn in te zien; zoeken wij alleen op
    # "exb-", dan meldt de verkenning "geen bijlagen" terwijl ze er zijn.
    links = alle_links(
        '<a href="https://ander-portaal.nl/zaak/toon?sleutel=GEHEIM123">kijk</a>'
        '<a href="/frbr/x/exb-2026-1/bijlage/tek.pdf">tekening</a>'
        '<a href="/frbr/x/exb-2026-2/bijlage/tek2.pdf">tekening</a>',
        "https://repository.overheid.nl/frbr/a/b.html")
    check("aantal hosts", len(links), 2)
    bron = str(links)
    for verboden in ("GEHEIM123", "sleutel="):
        if verboden in bron:
            fouten.append(f"de hostsamenvatting bevat {verboden!r}")
    vreemd = [h for h in links if h["host"] == "ander-portaal.nl"]
    if not vreemd:
        fouten.append("een link naar een host die wij niet kennen wordt niet "
                      "geteld, en dan leest 'geen bijlagen' als 'die zijn er "
                      "niet'")
    eigen = [h for h in links if h["host"] == "repository.overheid.nl"]
    if eigen:
        check("pdf's geteld", eigen[0]["pdf"], 2)

    # 4c. EEN LINK NAAR EEN ANDERE BEKENDMAKING IS GEEN BIJLAGE.
    # De eerste echte ronde meldde bij beide publicaties een bijlage die
    # gmb-2015-16426.pdf bleek: een standaardlink die op elke publicatiepagina
    # staat. Daardoor leek een publicatie zonder bijlagen er een met een te
    # hebben, en dat kostte een download en een scheve telling.
    deze = ("https://repository.overheid.nl/frbr/officielepublicaties/gmb/"
            "2026/gmb-2026-463651/1/html/gmb-2026-463651.html")
    if not andere_publicatie(
            "https://zoek.officielebekendmakingen.nl/gmb-2015-16426.pdf", deze):
        fouten.append("de standaardlink naar gmb-2015-16426 telt nog mee als "
                      "bijlage")
    # HET PAD ZOALS HET ER ECHT UITKWAM. De link is relatief, dus na het
    # samenvoegen staan er twee nummers in de url. Het eerste is deze
    # publicatie zelf. Dit geval liet de ronde over 148 publicaties 133 keer
    # door, terwijl het geval hierboven keurig groen stond.
    if not andere_publicatie(
            "https://repository.overheid.nl/frbr/officielepublicaties/gmb/"
            "2026/gmb-2026-474906/1/html/gmb-2015-16426.pdf",
            "https://repository.overheid.nl/frbr/officielepublicaties/gmb/"
            "2026/gmb-2026-474906/1/html/gmb-2026-474906.html"):
        fouten.append("een relatieve standaardlink glipt erdoor: de url "
                      "bevat dan twee nummers en het eerste is deze "
                      "publicatie zelf")
    if andere_publicatie(
            "https://repository.overheid.nl/frbr/officielepublicaties/gmb/"
            "2026/gmb-2026-463651/1/pdf/gmb-2026-463651.pdf", deze):
        fouten.append("de publicatie zelf wordt aangezien voor een andere")
    if andere_publicatie(
            "https://repository.officiele-overheidspublicaties.nl/"
            "externebijlagen/exb-2026-34477/1/bijlage/x.pdf", deze):
        fouten.append("een echte externe bijlage wordt weggegooid")
    html2 = ('<a href="https://zoek.officielebekendmakingen.nl/'
             'gmb-2015-16426.pdf">Bekendmakingenbesluit</a>')
    check("standaardlink levert geen bijlage", bijlagen_uit_html(html2, deze),
          [])

    # 4d. UIT EEN ROMMELIGE WAARDE KOMT EEN BRUIKBARE URL.
    # De metadata geeft "Afwijkvergunning|exb-2026-34477": een label en een
    # nummer. Daar de basis voor plakken gaf 400 en 404.
    u = exb_urls("Afwijkvergunning|exb-2026-34477")
    if not u:
        fouten.append("uit 'Afwijkvergunning|exb-2026-34477' komt geen url")
    else:
        for x in u:
            # Hoofdletterongevoelig vergelijken. Eerst stond hier
            # "Afwijkvergunning" in x, en die controle ging niet af toen ik
            # het label er met opzet in liet lekken: de opgebouwde url wordt
            # lowercase gemaakt, dus het label stond er wel in maar anders
            # gespeld. Een controle die zijn eigen geval niet ziet.
            if "exb-2026-34477" not in x.lower() or "afwijk" in x.lower():
                fouten.append(f"de opgebouwde url klopt niet: {x}")
            if not x.startswith("https://repository.officiele-"):
                fouten.append(f"de opgebouwde url staat op een vreemde host: "
                              f"{x[:60]}")
        if len(set(u)) != len(u):
            fouten.append("dezelfde vorm staat er twee keer in")
    check("zonder nummer geen url", exb_urls("gewoon wat tekst"), [])

    # 4e. EEN URL IN DE LOPENDE TEKST TELT MEE.
    # De bekendmaking verwijst naar een link op de pagina; staat die als
    # gewone tekst, dan vindt een zoektocht naar href hem niet en meldt de
    # verkenning ten onrechte dat er niets is.
    in_tekst = alle_links("<p>De aanvraag is in te zien via "
                          "https://portaal.nijmegen.nl/zaak/toon</p>",
                          "https://repository.overheid.nl/a.html")
    poort = [h for h in in_tekst if h["host"] == "portaal.nijmegen.nl"]
    if not poort:
        fouten.append("een url die als gewone tekst in de bekendmaking staat "
                      "wordt niet gezien")
    elif not poort[0].get("in_tekst"):
        fouten.append("een url uit de lopende tekst wordt niet als zodanig "
                      "gemeld, en dan lijkt het een gewone link")

    # 4f. DE LIJST PUBLICATIES KOMT UIT HET ARCHIEF, NIET UIT EEN OPSOMMING.
    # Een lijst nummers die met de hand wordt bijgehouden, wordt niet
    # bijgehouden. Hier staat een klein archief in dezelfde vorm als het
    # echte, zodat de keuze meetbaar is zonder het bestand te hoeven lezen.
    nep = {
        "staringstraat2": [
            {"datum": "2026-10-05", "soorten": ["splitsing"],
             "titel": "Aanvraag voor het verbouwen naar 3 appartementen",
             "url": "https://repository.overheid.nl/a/gmb-2026-463651.html"}],
        "ergensstraat1": [
            {"datum": "2026-09-01", "soorten": ["brandveilig gebruik"],
             "titel": "Melding brandveilig gebruik",
             "url": "https://repository.overheid.nl/a/gmb-2026-1.html"},
            {"datum": "2026-10-10", "soorten": ["verbouwing", "kamerverhuur"],
             "titel": "Besluit verbouwing",
             "url": "https://repository.overheid.nl/a/gmb-2026-2.html"}],
        "dubbelstraat3": [
            {"datum": "2026-10-05", "soorten": ["splitsing"],
             "titel": "Dezelfde publicatie onder een tweede pand",
             "url": "https://repository.overheid.nl/a/gmb-2026-463651.html"}],
    }
    gevonden = uit_archief(archief=nep)
    check("aantal uit het archief", len(gevonden), 2)
    check("nieuwste eerst", gevonden[0]["gmb"], "gmb-2026-2")
    if any(g["gmb"] == "gmb-2026-1" for g in gevonden):
        fouten.append("een melding brandveilig gebruik komt mee, terwijl die "
                      "over gebruik gaat en niet over de indeling")
    # Dezelfde publicatie onder twee panden mag maar een keer worden
    # opgehaald; anders betalen wij hem twee keer en telt hij dubbel.
    if len([g for g in gevonden if g["gmb"] == "gmb-2026-463651"]) != 1:
        fouten.append("dezelfde publicatie onder twee panden komt dubbel mee")
    check("archief ontbreekt", uit_archief(pad="bestaat-niet.json"), [])

    # 4g. HALF GEKEKEN LEEST NIET ALS HELEMAAL GEKEKEN.
    # De job wordt na twintig minuten afgebroken, en bij zo'n afbreking
    # draait de stap die het issue schrijft niet meer, ook niet met always().
    # Dus stopt de module zelf eerder; dan moet er wel bij staan hoeveel hij
    # niet heeft gehaald, anders leest een ronde van 40 publicaties als een
    # volledige ronde over 148.
    half = samenvatting([{"gmb": "gmb-2026-1", "vormen": [], "bijlagen": []}],
                        niet_gehaald=108)
    if "108 publicaties zijn niet meer gehaald" not in half:
        fouten.append("een afgebroken ronde meldt niet hoeveel er niet is "
                      "gehaald, en leest dan als een volledige ronde")
    heel = samenvatting([{"gmb": "gmb-2026-1", "vormen": [], "bijlagen": []}])
    if "niet meer gehaald" in heel:
        fouten.append("een volledige ronde meldt ten onrechte dat er iets "
                      "niet is gehaald")

    # 5. GEEN GELDIGE XML IS EEN ANTWOORD EN GEEN VAL.
    check("rommel in plaats van xml", bijlagen_uit_metadata("<nietafgesloten",
                                                            REPO), [])
    check("lege metadata", bijlagen_uit_metadata("", REPO), [])

    # 6. DE SAMENVATTING IS LEESBAAR EN VERRAADT NIETS.
    leeg = samenvatting([])
    if "er is niet gekeken" not in leeg:
        fouten.append(f"een lege verkenning zegt niet dat er niet is gekeken: "
                      f"{leeg[:90]!r}")
    vol = samenvatting([{
        "gmb": "gmb-2026-463651",
        "vormen": [{"vorm": "html van de publicatie", "uitkomst": "gelezen",
                    "tekens": 12000, "aantal": 6},
                   {"vorm": "metadata van de publicatie",
                    "uitkomst": "HTTPError 404", "aantal": 0}],
        "bijlagen": [{"url": "https://repository.overheid.nl/x.pdf",
                      "naam": "1038-04geb Staringstraat2.pdf", "tekst": ""}],
        "bestanden": [{"naam": "1038-04geb Staringstraat2.pdf", "bytes": 3049275,
                       "soort": "pdf", "bladzijden": 6,
                       "heeft_tekstlaag": True, "plattegrond": True}]}])
    for nodig in ("gmb-2026-463651", "1038-04geb", "HTTPError 404",
                  "hebben 1 een tekstlaag"):
        if nodig not in vol:
            fouten.append(f"de samenvatting noemt {nodig!r} niet")
    # Een mislukte vorm moet erin blijven staan. Zonder dat leest een
    # samenvatting met een lege tabel als "deze publicatie heeft geen
    # bijlagen", terwijl er misschien verkeerd is gekeken.
    if "404" not in vol:
        fouten.append("een vorm die niets opleverde valt uit de samenvatting")

    print(f"Proef bijlagen: {len(fouten)} fouten", file=sys.stderr)
    for f in fouten:
        print(f"FOUT {f}", file=sys.stderr)
    return 1 if fouten else 0


ARCHIEF = "bekendmakingen_archief.json"

# De soorten publicatie waarbij een plattegrond iets zegt. De namen komen uit
# het veld "soorten" dat het archief al bijhoudt; ze worden hier niet opnieuw
# bedacht. "brandveilig gebruik" en "kamerverhuur" zitten er niet bij: daar
# gaat het om gebruik en niet om de indeling, en ze zijn samen groter dan al
# het andere bij elkaar.
SOORTEN = ("splitsing", "verbouwing", "transformatie", "samenvoeging")


def uit_archief(soorten=SOORTEN, pad=ARCHIEF, archief=None):
    """
    De publicaties uit ons eigen archief waarbij een plattegrond iets zegt.

    WAAROM UIT HET ARCHIEF EN NIET UIT EEN LIJST. Een lijst nummers die met de
    hand wordt bijgehouden, wordt niet bijgehouden. Het archief groeit elke
    ochtend vanzelf, dus elke nieuwe splitsingsaanvraag valt hier vanzelf
    onder. Dat is het hele punt van deze route.

    Nieuwste eerst, want een recente aanvraag heeft de meeste kans dat de
    stukken nog online staan.
    """
    if archief is None:
        try:
            with open(pad, encoding="utf-8") as f:
                archief = json.load(f)
        except Exception:
            return []
    uit = []
    for sleutel, lijst in (archief or {}).items():
        for r in lijst or []:
            if not isinstance(r, dict):
                continue
            # soorten=None betekent alles. Dat is er voor publicatievelden.py,
            # die van elke publicatie de uitkomst wil en niet alleen van de
            # soorten waarbij een plattegrond iets zegt.
            if soorten is not None and not (set(r.get("soorten") or [])
                                            & set(soorten)):
                continue
            m = GMB.search(r.get("url") or "")
            if not m:
                continue
            uit.append({"gmb": m.group(1).lower(), "datum": r.get("datum") or "",
                        "pand": sleutel, "titel": (r.get("titel") or "")[:70]})
    # Dezelfde publicatie kan onder twee panden staan. Eenmaal is genoeg.
    gezien, net = set(), []
    for r in sorted(uit, key=lambda x: x["datum"], reverse=True):
        if r["gmb"] in gezien:
            continue
        gezien.add(r["gmb"])
        net.append(r)
    return net


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gmb", default="",
                    help="publicatienummers, door komma's gescheiden")
    ap.add_argument("--uit-archief", action="store_true",
                    help="de publicaties uit bekendmakingen_archief.json "
                         "halen in plaats van uit --gmb")
    ap.add_argument("--max", type=int, default=0,
                    help="niet meer dan dit aantal publicaties, 0 is alles")
    ap.add_argument("--minuten", type=float, default=14,
                    help="eigen tijdbudget; hij stopt zelf en schrijft op wat "
                         "hij heeft")
    ap.add_argument("--haal", action="store_true",
                    help="de bijlagen ook binnenhalen en beschrijven")
    ap.add_argument("--proef", action="store_true")
    ap.add_argument("--js", action="store_true",
                    help="de scripts van de pagina volgen om te vinden welk "
                         "adres de links inlaadt die niet in de HTML staan")
    ap.add_argument("--tekst", action="store_true",
                    help="de lopende tekst van de publicatie meenemen in de "
                         "samenvatting; een bekendmaking is een openbaar stuk "
                         "en de enige manier om te zien waar zij naar verwijst")
    ap.add_argument("--samenvatting", default="",
                    help="pad waar de bevinding als markdown komt; zonder dit "
                         "staat de uitkomst alleen in het joblogboek, en dat "
                         "is van buiten de runner niet te lezen")
    args = ap.parse_args()
    if args.proef:
        return proef()

    if args.uit_archief:
        rijen = uit_archief()
        nummers = [r["gmb"] for r in rijen]
        print(f"Uit het archief: {len(nummers)} publicaties van soort "
              f"{', '.join(SOORTEN)}", file=sys.stderr)
    else:
        nummers = [g.strip() for g in args.gmb.split(",") if g.strip()]
    if args.max:
        nummers = nummers[:args.max]
    if not nummers:
        # Geen publicaties is iets anders dan geen bijlagen. Dat verschil
        # hoort in de samenvatting te staan en niet in een lege tabel.
        print("Geen publicaties om te onderzoeken.", file=sys.stderr)

    # EEN EIGEN TIJDBUDGET, RUIM ONDER DE JOBLIMIET.
    #
    # De workflow stopt de job na twintig minuten. Zo'n stop is geen nette
    # afsluiting: GitHub breekt de hele job af, en dan draait de stap die de
    # bevinding in een issue zet ook niet meer, ook niet met always(). Dan is
    # er niets te lezen, en dat is precies de fout die deze hele verkenning
    # moest oplossen. Dus stopt hij zelf eerder en schrijft op wat hij heeft,
    # met erbij hoeveel publicaties hij niet meer heeft gehaald. Half
    # gekeken en niet gekeken mogen niet hetzelfde lezen.
    import time
    einde = time.time() + args.minuten * 60
    niet_gehaald = 0

    bevindingen = []
    try:
        for n, gmb in enumerate(nummers):
            if time.time() > einde:
                niet_gehaald = len(nummers) - n
                print(f"Tijdbudget van {args.minuten} minuten op na {n} "
                      f"publicaties; {niet_gehaald} niet gehaald.",
                      file=sys.stderr)
                break
            print(f"\n== {gmb} ==", file=sys.stderr)
            v = verken(gmb, haal_bestanden=args.haal)
            if args.js:
                # DE LINK STAAT NIET IN DE HTML, HIJ WORDT INGELADEN.
                # De pagina roept GetReferendumLinks(<gmb>) aan. Daarom vond
                # deze module nooit een verwijzing naar de stukken: zij staat
                # er pas ná het laden in. Welk adres die functie bevraagt,
                # staat in een van de scripts van de pagina.
                _n, _u = kandidaten(gmb)[2]      # de zoekpagina
                _h, _f = haal(_u)
                _sporen = []
                if _f:
                    _sporen.append(f"pagina niet gelezen: {_f}")
                else:
                    _srcs = re.findall(r'<script[^>]+src="([^"]+)"', _h or "",
                                       re.I)
                    _sporen.append(f"{len(_srcs)} scripts op de pagina")
                    for _src in _srcs[:12]:
                        _vol = urllib.parse.urljoin(_u, _src)
                        if not toegestaan(_vol):
                            _sporen.append(f"  {_src[:60]}: host niet "
                                           f"toegestaan")
                            continue
                        _js, _jf = haal(_vol)
                        if _jf:
                            _sporen.append(f"  {_src[:50]}: {_jf}")
                            continue
                        if "Referendum" not in (_js or ""):
                            continue
                        _sporen.append(f"  GEVONDEN in {_src[:60]}")
                        for _m in re.finditer(
                                r'.{0,160}Referendum.{0,240}', _js, re.S):
                            _sporen.append("    "
                                           + re.sub(r"\s+", " ",
                                                    _m.group(0))[:400])
                v["js"] = _sporen
            if args.tekst:
                # DE PUBLICATIE ZELF LATEN SPREKEN.
                # Twee keer heb ik beredeneerd waar de stukken zouden moeten
                # hangen en twee keer zat ik ernaast. De bekendmaking is een
                # openbaar stuk van de overheid; wat er staat is te lezen.
                _n, _u = kandidaten(gmb)[0]
                _h, _f = haal(_u)
                _kaal = re.sub(r"<[^>]+>", " ", _h or "")
                _kaal = re.sub(r"\s+", " ", _kaal).strip()
                # De kop en de staart van de pagina zijn vaste navigatie; het
                # middenstuk is de bekendmaking.
                v["tekst"] = _kaal[:3000] if not _f else f"niet gelezen: {_f}"
                # Ook de metadata, want daar zou de gemeente een
                # inzage-adres in kwijt kunnen. Drieduizend tekens, dus het
                # kost niets om het te zien in plaats van het te vermoeden.
                _mn, _mu = kandidaten(gmb)[1]
                _mh, _mf = haal(_mu)
                v["metadata"] = ((_mh or "")[:2500] if not _mf
                                 else f"niet gelezen: {_mf}")
            for vorm in v["vormen"]:
                print(f"  {vorm['vorm']}: {vorm['uitkomst']}, "
                      f"{vorm.get('aantal', 0)} bijlagen", file=sys.stderr)
            for d in v.get("bestanden", []):
                print(f"    {d.get('naam', '?')[:60]:60} "
                      f"{d.get('bytes', '')} {d.get('soort', d.get('fout', ''))}",
                      file=sys.stderr)
            bevindingen.append(v)
    finally:
        # Ook bij een fout halverwege hoort er te staan wat wel is gevonden.
        if args.samenvatting:
            with open(args.samenvatting, "w", encoding="utf-8") as f:
                f.write(samenvatting(bevindingen, niet_gehaald=niet_gehaald))
    return 0


if __name__ == "__main__":
    # sys.exit en niet main(): anders is de exitcode altijd 0 en is de poort
    # in de workflow een formaliteit.
    sys.exit(main())
