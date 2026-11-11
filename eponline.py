#!/usr/bin/env python3
"""
Het energielabel uit EP-Online, uit één plek.

WAT HIER MISGING. De aanroep van EP-Online stond drie keer in de repo, en de
derde kopie was stuk. marktprijzen_bag.py en bekendmakingen_nijmegen.py
vragen eerst op verblijfsobject-id en dan pas op postcode, en lezen het label
uit zes mogelijke veldnamen. voorraad_bag.py vroeg alleen op postcode en las
alleen het veld "labelLetter".

Wat dat kostte, gemeten op 10 oktober: van 818 opgevraagde adressen kwamen er
803 terug als "geen label bekend" en 15 als HTTP 400. Nul labels gevonden,
terwijl de pandgeschiedenis er met de werkende aanroep 1.384 kent. Die 803
zijn geen antwoord maar een veldnaam die niet bestond: de API gaf HTTP 200,
de lus vond geen "labelLetter" en gaf een leeg antwoord terug, en de
aanroeper schreef dat op als "dit adres heeft geen label". Een aanname over
een veldnaam die zich voordoet als een feit over de woningvoorraad.

Dat is dezelfde fout als met de pandsleutel, en dezelfde oplossing: één
implementatie, en een proef die hem vasthoudt.

WAT DEZE PROEF WEL EN NIET AANTOONT. De vormen hieronder zijn afgeleid van de
veldnamen die de twee werkende implementaties aankunnen. De proef toetst dus
of het lezen klopt, en niet of de API er werkelijk zo uitziet. Wat hij wel
vangt: dat een lezer met één veldnaam langs de andere vijf heen loopt, en dat
een privélabel geen "niet bekend" wordt.

EN DAAROM LIGT ER NU EEN ECHT ANTWOORD BIJ. Hierboven stond tot 12 oktober
dat een zevende veldnaam niet gevangen zou worden, omdat er in de repo geen
enkel echt antwoord van EP-Online stond. Dat kon ook niet anders: de sleutel
staat in de workflow en niet op een werkplek. ruw() vraagt een paar
verblijfsobjecten onbewerkt op en legt het antwoord vast in
eponline_antwoordvorm.json, en proef_vastgelegd() meet daarop na of lees() er
hetzelfde uit haalt en of er een veldnaam in staat die op een label lijkt en
die wij niet kennen. Zolang dat bestand er niet is, meldt de proef dat hij
over de API zelf niets zegt. "Niet gekeken" en "gekeken en niets gevonden"
mogen nooit hetzelfde woord krijgen.

WAT ER AAN DE BUITENKANT VASTLIGT. Een W-label hoort bij één verblijfsobject
en niet bij het pand: BRL 9500-W zegt dat registratie op een woongebouw geen
energielabel oplevert, en het ISSO-protocol noemt de pand-id de bovengrens en
de object-id de ondergrens, met één W-label per object-id. Het recordformaat
van RVO past daarbij: één BAGVerblijfsobjectID en BAGPandIDs als herhalend
veld. Bij utiliteitsbouw mag een label wel over meerdere panden en meerdere
objecten gaan, dus voor de plint geldt dit niet.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

BASIS = "https://public.ep-online.nl/api/v5/PandEnergielabel"

# Waar een echt antwoord van EP-Online wordt vastgelegd. Zie ruw().
VORM = "eponline_antwoordvorm.json"

# De veldnamen waaronder het label kan staan. _veld() vergelijkt zonder te
# letten op hoofdletters en liggende streepjes, dus dit zijn vormen en geen
# exacte sleutels.
VELD_LABEL = ("Pand_energieklasse", "energieklasse", "labelLetter",
              "Pand_labelletter", "energielabel", "labelletter")
VELD_PRIVE = ("Pand_energielabel_is_prive", "isPrive", "prive")
VELD_DATUM = ("Pand_registratiedatum", "registratiedatum")
VELD_GELDIG = ("Meting_geldig_tot", "geldigTot", "metingGeldigTot",
               "Geldig_tot")
VELD_KLASSE = ("Pand_gebouwklasse", "gebouwklasse")

# DE VELDEN DIE WIJ EERST WEGGOOIDEN. Het echte antwoord van 11 oktober heeft
# zestien velden; lees() bewaarde er vijf. Dat is de eis "een veld dat een
# bron meegeeft, wordt opgeschreven of met reden weggelaten", en de reden
# ontbrak. Het zwaarste is Berekeningstype: in pand 0268100000026050 staan
# twee labels volgens de Rekenmethodiek van 2014 en drie volgens NTA 8800,
# en een D van 2017 is dus geen slechter huis dan een C van 2026 maar een
# andere rekenmethode. Zonder dit veld vergelijkt de brief twee grondslagen.
VELD_METHODE = ("Berekeningstype", "berekeningstype")
VELD_OPNAME = ("Opnamedatum", "opnamedatum")
VELD_TYPE = ("Gebouwtype", "gebouwtype")
VELD_SUBTYPE = ("Gebouwsubtype", "gebouwsubtype")
VELD_REFERENTIE = ("Op_basis_van_referentiegebouw",
                   "opBasisVanReferentiegebouw")
VELD_VBO = ("BAGVerblijfsobjectID", "bagVerblijfsobjectId")
VELD_PANDEN = ("BAGPandIDs", "bagPandIds", "BAGPandID")
VELD_VERBRUIK = ("BerekendeEnergieverbruik", "berekendeEnergieverbruik")
VELD_BOUWJAAR = ("Bouwjaar", "bouwjaar")

# Wat met reden WEL wordt weggelaten: Certificaathouder (de adviseur, niet
# het pand), BerekendeCO2Emissie (stond op 0.0 in alle vijf de echte
# antwoorden, dus daar valt niets op te bouwen), en Postcode en Huisnummer
# (die hebben wij al uit de BAG en een tweede bron voor hetzelfde adres is
# precies de soort dubbeling die we deze week hebben opgeruimd).


def _sleutel():
    return os.environ.get("EP_API_KEY") or ""


def _koppen():
    return {"Authorization": _sleutel(), "Accept": "application/json"}


def eerste(data):
    """
    Het eerste record uit een antwoord, in welke vorm het ook komt.

    De API geeft soms een lijst, soms een enkel object, en soms een object met
    de lijst eronder. Alle drie zijn vormen die de werkende implementaties
    aankunnen, dus alle drie horen hier.
    """
    if isinstance(data, list):
        return data[0] if data else None
    if isinstance(data, dict):
        for naam in ("results", "data", "items"):
            binnen = data.get(naam)
            if isinstance(binnen, list) and binnen:
                return binnen[0]
        return data
    return None


def veld(rec, namen):
    """
    De eerste gevulde waarde onder een van deze veldnamen.

    Vergelijkt zonder hoofdletters en zonder liggende streepjes, want de API
    schrijft hetzelfde begrip als Pand_energieklasse en als energieklasse.
    """
    if not isinstance(rec, dict):
        return None
    for naam in namen:
        doel = naam.lower().replace("_", "")
        for k, v in rec.items():
            if str(k).lower().replace("_", "") == doel and v not in (None, ""):
                return v
    return None


def splits_toevoeging(deel):
    """
    Uit "29A-24" komt ("29", "A", "24"), uit "20" komt ("20", "", "").

    Dit stond in drie varianten in de repo, waarvan er een de toevoeging liet
    vallen omdat zijn functie er geen parameter voor had. Bij Bachstraat
    29A-24 gaf dat HTTP 400, vijftien keer per ronde.
    """
    m = re.match(r"^\s*(\d+)\s*(.*)$", str(deel or ""))
    if not m:
        return ("", "", "")
    nr, rest = m.group(1), (m.group(2) or "").strip()
    if not rest:
        return (nr, "", "")
    if "-" in rest:
        letter, _, toev = rest.partition("-")
        return (nr, letter.strip(), toev.strip())
    # Een enkele letter is een huisletter; meer tekens zijn een toevoeging.
    rest = rest.lstrip("- ")
    if len(rest) == 1 and rest.isalpha():
        return (nr, rest, "")
    return (nr, "", rest)


def uit_adres(adres):
    """(huisnummer, huisletter, toevoeging) uit een heel adres."""
    deel = str(adres or "").split()
    if len(deel) < 2:
        return ("", "", "")
    return splits_toevoeging(deel[-1])


def lees(rec):
    """
    Uit een EP-Online-record: het label, of None als er niets in staat.

    Een privélabel is een antwoord en geen leegte: er IS een label, het is
    alleen niet openbaar. Wie dat als "niet bekend" opschrijft, vraagt het
    volgend jaar opnieuw en krijgt hetzelfde.
    """
    if not isinstance(rec, dict) or not rec:
        return None
    prive = veld(rec, VELD_PRIVE)
    is_prive = str(prive).lower() in ("1", "true", "ja")
    letter = veld(rec, VELD_LABEL)
    if not is_prive and not letter:
        return None
    panden = veld(rec, VELD_PANDEN)
    if isinstance(panden, str):
        panden = [panden]
    methode = str(veld(rec, VELD_METHODE) or "")
    return {
        # Bij een privelabel IS er een label, maar de letter niet. De rest
        # van het record staat er wel, en die werd eerst ook weggegooid.
        "label": None if is_prive else str(letter).strip(),
        "prive": is_prive,
        "registratiedatum": str(veld(rec, VELD_DATUM) or "")[:10],
        "opnamedatum": str(veld(rec, VELD_OPNAME) or "")[:10],
        "geldig_tot": str(veld(rec, VELD_GELDIG) or "")[:10],
        "gebouwklasse": veld(rec, VELD_KLASSE) or "",
        "gebouwtype": veld(rec, VELD_TYPE) or "",
        "gebouwsubtype": veld(rec, VELD_SUBTYPE) or "",
        "methode": methode,
        "nta8800": volgens_nta8800(methode),
        "referentiegebouw": veld(rec, VELD_REFERENTIE),
        "vbo": str(veld(rec, VELD_VBO) or ""),
        "panden": list(panden or []),
        "verbruik": veld(rec, VELD_VERBRUIK),
        "bouwjaar": veld(rec, VELD_BOUWJAAR),
    }


def volgens_nta8800(methode):
    """
    Of dit label volgens NTA 8800 is bepaald. None als het veld leeg is.

    WAAROM DIT EEN EIGEN FUNCTIE IS EN GEEN REGEL ONDERWEG. Dit is de
    grondslag onder de letter, en de eis zegt dat een getal nooit met een
    getal op een andere grondslag wordt vergeleken. Een label van voor 2021
    is bepaald met de Rekenmethodiek Definitief Energielabel van 2014 en een
    label daarna met NTA 8800, en die twee geven voor hetzelfde huis een
    andere letter. Gemeten in pand 0268100000026050: D en D volgens de oude
    methode, C, B en C volgens NTA 8800.

    De tekst van het veld is de bron en niet de datum, want er zijn labels
    die later onder de oude methode zijn geregistreerd en een opnamedatum
    telt tien jaar door.
    """
    kaal = str(methode or "").lower().replace(" ", "").replace("-", "")
    if not kaal:
        return None
    return "nta8800" in kaal


# Wat een foutcode betekent.
#
# GEEN_LABEL: EP-Online kent dit object niet. Dat is een ANTWOORD en geen
# fout: deze woning heeft geen geregistreerd label. Dat onderscheid is op 11
# oktober gemeten en niet bedacht. Een eerste versie rekende 404 bij de
# weigeringen, en toen leverde de eerste echte ronde 67 labels en "46 fouten"
# op terwijl die 46 precies het antwoord "geen label" waren. Een foutenteller
# die oploopt bij correct gedrag leert je de teller negeren, en dat is erger
# dan geen teller.
#
# GEWEIGERD: de vraag zelf wordt niet aangenomen. Dat gaat nooit lukken voor
# dit adres, dus niet elke ronde opnieuw, maar het is wel iets om te zien:
# het betekent dat wij de vraag verkeerd stellen.
#
# STOPPEN: iets is mis met ons en niet met het adres, dus de ronde afbreken.
GEEN_LABEL = (404,)
GEWEIGERD = (400,)
STOPPEN = (401, 403, 429)


def energielabel(vbo_id=None, postcode="", huisnr="", letter="", toev="",
                 haler=None):
    """
    Het label van één adres. Geeft (uitkomst, fout, definitief).

    uitkomst is een dict met het label, of {} als er geen label bekend is, of
    None als er niets te zeggen valt. fout is leeg bij een antwoord.
    definitief zegt of dit adres opnieuw vragen zin heeft.

    Eerst op verblijfsobject-id, want dat is exact en dat is de route die
    werkt. Daarna op postcode plus huisnummer. haler is er voor de proef:
    daarmee gaat er geen enkele aanroep de deur uit.
    """
    if haler is None:
        if not _sleutel():
            return (None, "geen EP_API_KEY", False)
        import requests

        def haler(url, params):
            r = requests.get(url, headers=_koppen(), params=params, timeout=20)
            return (r.status_code, (lambda: r.json()))

    pogingen = []
    if vbo_id:
        pogingen.append((f"{BASIS}/AdresseerbaarObject/{vbo_id}", None))
    if postcode and huisnr:
        params = {"postcode": str(postcode).replace(" ", ""),
                  "huisnummer": str(huisnr)}
        if letter:
            params["huisletter"] = letter
        if toev:
            params["huisnummertoevoeging"] = toev
        pogingen.append((f"{BASIS}/Adres", params))
    if not pogingen:
        return (None, "geen vbo-id en geen postcode met huisnummer", True)

    laatste, def_alles, alles_onbekend = "", True, True
    for url, params in pogingen:
        try:
            code, json_van = haler(url, params)
        except Exception as e:
            laatste, def_alles, alles_onbekend = (
                f"netwerk: {str(e)[:60]}", False, False)
            continue
        if code in STOPPEN:
            return (None, f"HTTP {code}", False)
        if code in GEEN_LABEL:
            laatste = f"HTTP {code}"
            continue
        if code in GEWEIGERD:
            laatste, alles_onbekend = f"HTTP {code}", False
            continue
        if code != 200:
            laatste, def_alles, alles_onbekend = f"HTTP {code}", False, False
            continue
        try:
            rec = eerste(json_van())
        except Exception as e:
            laatste, def_alles = f"antwoord onleesbaar: {str(e)[:50]}", False
            continue
        uit = lees(rec)
        if uit is not None:
            return (uit, "", True)
        # HTTP 200 zonder label is een echt antwoord: dit adres heeft er geen.
        return ({}, "", True)
    # Elke route gaf 404: EP-Online kent dit object niet, en dat is hetzelfde
    # antwoord als HTTP 200 zonder label. Niet als fout melden.
    if alles_onbekend and laatste.startswith("HTTP 4"):
        return ({}, "", True)
    return (None, laatste or "geen antwoord", def_alles)


def aantal(data):
    """Hoeveel records er in dit antwoord zitten."""
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for naam in ("results", "data", "items"):
            binnen = data.get(naam)
            if isinstance(binnen, list):
                return len(binnen)
        return 1
    return 0


def _kaal(naam):
    """De veldnaam zoals veld() hem vergelijkt."""
    return str(naam).lower().replace("_", "")


BEKENDE_VELDEN = tuple(_kaal(n) for groep in
                       (VELD_LABEL, VELD_PRIVE, VELD_DATUM, VELD_GELDIG,
                        VELD_KLASSE, VELD_METHODE, VELD_OPNAME, VELD_TYPE,
                        VELD_SUBTYPE, VELD_REFERENTIE, VELD_VBO, VELD_PANDEN,
                        VELD_VERBRUIK, VELD_BOUWJAAR) for n in groep)


def ruw(vbo_ids, haler=None):
    """
    De onbewerkte antwoorden van EP-Online, zonder enige interpretatie.

    WAAROM DIT ER IS. De proef hieronder meet of ons lezen klopt, en niet of
    de API er werkelijk zo uitziet; dat staat ook zo in de docstring van deze
    module, want in de repo stond geen enkel echt antwoord van EP-Online. Een
    zevende veldnaam zou die proef dus niet vangen, en dat is precies de fout
    die op 10 oktober 818 aanroepen en nul labels kostte.

    Dit is ook het gereedschap dat toen ontbrak. Er was geen manier om naar
    één antwoord te kijken: de werkende aanroep en de stukke gaven beide een
    leeg resultaat terug, en in de logs stond alleen het aantal. Vanaf nu kan
    één verblijfsobject ruw worden opgevraagd en teruggelezen.

    EN WAAROM DE UITKOMST DOOR GIT TERUG MOET. De logserver van GitHub en de
    blobserver voor artifacts zijn van buiten de run niet te lezen, dus een
    antwoord dat alleen naar stdout gaat is er niet. vastleggen() schrijft het
    in een bestand dat de workflow terugcommit.

    Geeft per verblijfsobject een rij met de HTTP-code, het aantal records in
    het antwoord, de veldnamen, het record zelf en wat lees() eruit haalt.
    """
    if haler is None:
        if not _sleutel():
            return [{"vbo": v, "fout": "geen EP_API_KEY"} for v in vbo_ids]
        import requests

        def haler(url, params):
            r = requests.get(url, headers=_koppen(), params=params, timeout=20)
            return (r.status_code, (lambda: r.json()))

    uit = []
    for vbo in vbo_ids:
        rij = {"vbo": vbo}
        try:
            code, json_van = haler(f"{BASIS}/AdresseerbaarObject/{vbo}", None)
        except Exception as e:
            rij["fout"] = f"netwerk: {str(e)[:60]}"
            uit.append(rij)
            continue
        rij["http"] = code
        if code != 200:
            uit.append(rij)
            continue
        try:
            data = json_van()
        except Exception as e:
            rij["fout"] = f"antwoord onleesbaar: {str(e)[:50]}"
            uit.append(rij)
            continue
        rec = eerste(data)
        # HOEVEEL RECORDS. Dit is geen bijzaak maar de meting zelf: als één
        # verblijfsobject meer dan één label kan hebben, staat dat hier. De
        # norm zegt van niet (één W-label per Object-ID), en een aanname over
        # de norm is iets anders dan een getal uit het antwoord.
        rij["records_in_antwoord"] = aantal(data)
        rij["vorm"] = type(data).__name__
        rij["velden"] = sorted(rec.keys()) if isinstance(rec, dict) else []
        rij["record"] = rec if isinstance(rec, dict) else None
        rij["gelezen"] = lees(rec)
        uit.append(rij)
    return uit


def vastleggen(rijen, pad=VORM):
    """Het echte antwoord bewaren, zodat de proef erop kan draaien."""
    blok = {
        "opgehaald": dt.date.today().isoformat(),
        "bron": BASIS,
        "waarvoor": "Een echt antwoord van EP-Online, zodat proef() niet "
                    "alleen op afgeleide vormen draait. Zie ruw().",
        "antwoorden": rijen,
    }
    with open(pad, "w", encoding="utf-8") as f:
        json.dump(blok, f, ensure_ascii=False, indent=1, sort_keys=True)
    return blok


def proef_vastgelegd(pad=VORM):
    """
    Het vastgelegde echte antwoord nameten. Geeft (fouten, hoeveel gekeken).

    Dit is het enige deel van de proef dat iets zegt over de API zelf in
    plaats van over ons lezen. Twee dingen worden gemeten: dat lees() het
    label uit elk vastgelegd record haalt, en dat er geen veldnaam in staat
    die op een label lijkt en die wij niet kennen. Dat laatste is de zevende
    veldnaam uit de docstring hierboven.

    Bestaat het bestand niet, dan is dat "niet gekeken" en geen "gekeken en
    niets gevonden". Die twee mogen nooit met hetzelfde woord worden gezegd,
    dus hier wordt geen groene controle gemeld maar nul gekeken.
    """
    fouten, gekeken, zonder_methode = [], 0, 0
    if not os.path.exists(pad):
        return (fouten, 0)
    try:
        with open(pad, encoding="utf-8") as f:
            blok = json.load(f)
    except Exception as e:
        return ([f"{pad} niet te lezen: {str(e)[:60]}"], 0)
    for rij in blok.get("antwoorden") or []:
        rec = rij.get("record")
        if not isinstance(rec, dict) or not rec:
            continue
        gekeken += 1
        vbo = rij.get("vbo") or "?"
        # Wat er bij het ophalen uit dit record kwam, moet er nu nog uit
        # komen. Verandert ons lezen, dan is dit rood op een echt antwoord.
        toen = rij.get("gelezen")
        nu = lees(rec)
        if (toen or {}).get("label") != (nu or {}).get("label"):
            fouten.append(f"vastgelegd antwoord {vbo}: bij het ophalen las "
                          f"lees() {(toen or {}).get('label')!r}, nu "
                          f"{(nu or {}).get('label')!r}")
        # Een veldnaam die op een label lijkt en die wij niet kennen.
        for k in rec:
            kaal = _kaal(k)
            if kaal in BEKENDE_VELDEN:
                continue
            if "label" in kaal or "klasse" in kaal:
                fouten.append(f"vastgelegd antwoord {vbo} heeft veldnaam "
                              f"{k!r} die wij niet lezen; de zevende veldnaam")
        # DE GRONDSLAG MOET ERIN STAAN. Zonder Berekeningstype is niet te
        # zeggen of deze letter met NTA 8800 of met de methode van 2014 is
        # bepaald, en dan vergelijkt de brief twee grondslagen.
        if (nu or {}).get("nta8800") is None:
            zonder_methode += 1
    if zonder_methode:
        fouten.append(f"{zonder_methode} van de {gekeken} vastgelegde "
                      f"antwoorden hebben geen rekenmethode, dus de grondslag "
                      f"onder die letters is niet te zien")
    return (fouten, gekeken)


def proef():
    """De vormen nameten zonder één aanroep te doen."""
    fouten = []

    def check(naam, echt, verwacht):
        if echt != verwacht:
            fouten.append(f"{naam}: {echt!r}, verwacht {verwacht!r}")

    # Alle zes veldnamen waaronder het label kan staan. Dit is de fout die
    # voorraad_bag maakte: hij las er een.
    for naam in VELD_LABEL:
        uit = lees({naam: "C"})
        check(f"veld {naam}", (uit or {}).get("label"), "C")
    # Dezelfde meting met een vaste naam, want eisen.txt verwijst hiernaar en
    # een naam die met een f-string wordt gemaakt staat niet letterlijk in de
    # bron. De eisenproef ving dat zelf op toen ik het verkeerd deed.
    check("alle zes veldnamen gelezen",
          sum(1 for n in VELD_LABEL if (lees({n: "C"}) or {}).get("label")),
          len(VELD_LABEL))
    check("hoofdletters en streepjes doen niet mee",
          (lees({"pandenergieklasse": "A++"}) or {}).get("label"), "A++")
    check("leeg veld telt niet", lees({"energieklasse": ""}), None)
    check("leeg record", lees({}), None)
    check("geen dict", lees(None), None)

    # DE REKENMETHODE KOMT MEE. Dit is de grondslag onder de letter. Een D
    # van 2017 volgens de Rekenmethodiek van 2014 en een C van 2026 volgens
    # NTA 8800 zijn geen vergelijkbare getallen, en ze stonden in hetzelfde
    # pand.
    oud = ("Rekenmethodiek Definitief Energielabel, versie 1.2, "
           "16 september 2014")
    nieuw = "NTA 8800:2024 (basisopname woningbouw)"
    check("de rekenmethode komt mee",
          (lees({"Energieklasse": "D", "Berekeningstype": oud}) or {}
           ).get("methode"), oud)
    check("de oude methode is niet NTA 8800", volgens_nta8800(oud), False)
    check("NTA 8800 wordt herkend", volgens_nta8800(nieuw), True)
    check("NTA 8800 met een streepje ook",
          volgens_nta8800("NTA-8800:2020 detailopname"), True)
    check("zonder methode geen aanname", volgens_nta8800(""), None)
    check("en dan staat dat in de uitkomst",
          (lees({"Energieklasse": "D"}) or {}).get("nta8800"), None)

    # De overige velden uit het echte antwoord.
    echt = {"BAGVerblijfsobjectID": "0268010000045931",
            "Energieklasse": "D", "Gebouwklasse": "Woningbouw",
            "Gebouwtype": "Flatwoning (overig)",
            "Gebouwsubtype": "Tussenmidden", "Bouwjaar": 1955,
            "BerekendeEnergieverbruik": 63499.91,
            "Op_basis_van_referentiegebouw": False,
            "Opnamedatum": "2020-12-28T00:00:00",
            "Geldig_tot": "2030-12-28T00:00:00",
            "Registratiedatum": "2020-12-28T22:02:04.443",
            "Berekeningstype": oud}
    u = lees(echt) or {}
    check("het verblijfsobject uit het antwoord", u.get("vbo"),
          "0268010000045931")
    check("gebouwtype", u.get("gebouwtype"), "Flatwoning (overig)")
    check("gebouwsubtype", u.get("gebouwsubtype"), "Tussenmidden")
    check("bouwjaar", u.get("bouwjaar"), 1955)
    check("verbruik", u.get("verbruik"), 63499.91)
    check("referentiegebouw blijft False en wordt geen None",
          u.get("referentiegebouw"), False)
    check("opnamedatum afgekapt", u.get("opnamedatum"), "2020-12-28")
    check("geldig_tot uit Geldig_tot", u.get("geldig_tot"), "2030-12-28")
    # Het echte antwoord van de objectroute geeft GEEN pand-id. Dat is geen
    # gemis maar het antwoord zelf: EP-Online identificeert het label met het
    # verblijfsobject. In het totaalbestand staat BAGPandIDs wel, als
    # herhalend veld, dus het lezen moet een lijst aankunnen.
    check("geen pand-id in het antwoord van de objectroute", u.get("panden"),
          [])
    check("een pand-id als lijst",
          (lees({"Energieklasse": "A", "BAGPandIDs":
                 ["0268100000026050", "0268100000026051"]}) or {}
           ).get("panden"), ["0268100000026050", "0268100000026051"])
    check("een pand-id als losse tekst wordt een lijst",
          (lees({"Energieklasse": "A", "BAGPandID": "0268100000026050"}) or {}
           ).get("panden"), ["0268100000026050"])

    # Een privélabel is een antwoord en geen leegte.
    p = lees({"Pand_energielabel_is_prive": True, "Pand_energieklasse": "B"})
    check("prive geeft geen letter", (p or {}).get("label"), None)
    check("prive zegt dat het prive is", (p or {}).get("prive"), True)
    check("prive als 1", (lees({"isPrive": 1}) or {}).get("prive"), True)
    check("niet prive", (lees({"prive": False, "energieklasse": "D"}) or {}
                         ).get("prive"), False)

    # De drie antwoordvormen.
    check("lijst", (lees(eerste([{"energieklasse": "E"}])) or {}).get("label"),
          "E")
    check("enkel object",
          (lees(eerste({"energieklasse": "F"})) or {}).get("label"), "F")
    check("lijst onder results",
          (lees(eerste({"results": [{"energieklasse": "G"}]})) or {}
           ).get("label"), "G")
    check("lege lijst", eerste([]), None)
    check("datum afgekapt op tien tekens",
          (lees({"energieklasse": "A", "registratiedatum":
                 "2025-03-04T00:00:00"}) or {}).get("registratiedatum"),
          "2025-03-04")

    # Het huisnummer uit een adres. "29A-24" gaf vijftien keer HTTP 400 omdat
    # een van de drie kopieen de toevoeging liet vallen.
    check("gewoon nummer", splits_toevoeging("20"), ("20", "", ""))
    check("huisletter", splits_toevoeging("29A"), ("29", "A", ""))
    check("letter en toevoeging", splits_toevoeging("29A-24"),
          ("29", "A", "24"))
    check("alleen toevoeging", splits_toevoeging("29-24"), ("29", "", "24"))
    check("toevoeging van meer tekens", splits_toevoeging("12BIS"),
          ("12", "", "BIS"))
    check("niets", splits_toevoeging(""), ("", "", ""))
    check("uit een heel adres", uit_adres("Bachstraat 29A-24"),
          ("29", "A", "24"))
    check("adres zonder nummer", uit_adres("Hertogstraat"), ("", "", ""))

    # De route: eerst het vbo-id, en de postcode alleen als dat niets geeft.
    gevraagd = []

    def nep(code_per_url, lichaam=None):
        def haler(url, params):
            gevraagd.append(url.rsplit("/", 2)[-2] if "AdresseerbaarObject"
                            in url else "Adres")
            code = code_per_url.get("vbo" if "AdresseerbaarObject" in url
                                    else "adres", 200)
            return (code, lambda: (lichaam or {}))
        return haler

    gevraagd.clear()
    uit, fout, definitief = energielabel(
        vbo_id="0268010000000056", postcode="6524LR", huisnr="20",
        haler=nep({"vbo": 200}, {"energieklasse": "C"}))
    check("vbo eerst gevraagd", gevraagd, ["AdresseerbaarObject"])
    check("label uit de vbo-route", (uit or {}).get("label"), "C")
    check("geen fout", fout, "")

    gevraagd.clear()
    uit, fout, definitief = energielabel(
        vbo_id="0268010000000056", postcode="6524LR", huisnr="20",
        haler=nep({"vbo": 404, "adres": 200}, {"labelLetter": "D"}))
    check("na 404 ook de adresroute", gevraagd,
          ["AdresseerbaarObject", "Adres"])
    check("label uit de adresroute", (uit or {}).get("label"), "D")

    # HTTP 200 zonder label is een antwoord: dit adres heeft er geen.
    uit, fout, definitief = energielabel(
        vbo_id="X", haler=nep({"vbo": 200}, {"iets": "anders"}))
    check("200 zonder label geeft een leeg antwoord", uit, {})
    check("en dat is definitief", definitief, True)

    # 404 OP ALLE ROUTES IS EEN ANTWOORD EN GEEN FOUT. Op 11 oktober leverde
    # de eerste echte ronde 67 labels en "46 fouten" op, en die 46 waren alle
    # 46 HTTP 404: EP-Online kent dat object niet, dus die woning heeft geen
    # geregistreerd label. Dat is hetzelfde antwoord als HTTP 200 zonder
    # label. Een foutenteller die oploopt bij correct gedrag leert je de
    # teller negeren.
    uit, fout, definitief = energielabel(
        vbo_id="X", postcode="6524LR", huisnr="20",
        haler=nep({"vbo": 404, "adres": 404}))
    check("404 overal geeft een leeg antwoord", uit, {})
    check("404 overal is geen fout", fout, "")
    check("404 overal is definitief", definitief, True)

    # 400 is iets anders: de vraag wordt niet aangenomen. Definitief voor dit
    # adres, maar wel iets om te zien, want het betekent dat wij hem verkeerd
    # stellen.
    uit, fout, definitief = energielabel(
        vbo_id="X", postcode="6524LR", huisnr="29", letter="A", toev="24",
        haler=nep({"vbo": 404, "adres": 400}))
    check("400 geeft geen uitkomst", uit, None)
    check("400 is definitief", definitief, True)
    check("400 noemt de code", fout, "HTTP 400")

    # 429 en een geweigerde sleutel zijn van ons en niet van het adres.
    for code in STOPPEN:
        uit, fout, definitief = energielabel(
            vbo_id="X", haler=nep({"vbo": code}))
        check(f"{code} stopt", (uit, definitief), (None, False))
    uit, fout, definitief = energielabel(vbo_id="X", haler=nep({"vbo": 500}))
    check("500 is niet definitief", definitief, False)

    def valt_om(url, params):
        raise OSError("verbinding weg")
    uit, fout, definitief = energielabel(vbo_id="X", haler=valt_om)
    check("netwerkfout is niet definitief", definitief, False)
    check("netwerkfout noemt zich", fout.startswith("netwerk:"), True)

    uit, fout, definitief = energielabel(haler=nep({}))
    check("zonder vbo en zonder postcode", (uit, definitief), (None, True))

    # En de drie aanroepers moeten deze module gebruiken en niet hun eigen
    # kopie. Dat is de eis "een conventie bestaat een keer in code", en voor
    # EP-Online was die kopie het verschil tussen 1.384 labels en nul.
    # Sinds de splitsing van 11 november staan marktprijzen_bag.py en
    # bekendmakingen_nijmegen.py in de brief-repo; die twee meet
    # marktdata_toets.py daar na. Hier blijft de aanroeper in deze repo.
    for pad, naam in (("voorraad_bag.py", "haal_label"),):
        try:
            with open(pad, encoding="utf-8") as f:
                bron = f.read()
        except Exception as e:
            fouten.append(f"{pad} niet te lezen: {str(e)[:40]}")
            continue
        if "eponline" not in bron:
            fouten.append(f"{pad} gebruikt eponline niet; {naam}() heeft dan "
                          f"een eigen kopie van de aanroep")
        if "labelLetter" in bron and "eponline" not in bron:
            fouten.append(f"{pad} leest labelLetter zelf")

    # HOEVEEL RECORDS ER IN EEN ANTWOORD ZITTEN, in alle drie de vormen.
    check("aantal uit een lijst", aantal([{"a": 1}, {"a": 2}]), 2)
    check("aantal uit een enkel object", aantal({"energieklasse": "C"}), 1)
    check("aantal onder results", aantal({"results": [{"a": 1}]}), 1)
    check("aantal uit een lege lijst onder results",
          aantal({"results": []}), 0)
    check("aantal uit niets", aantal(None), 0)

    # DE RUWE OPVRAGING, zonder aanroep. Wat hier wordt nagemeten is dat de
    # rij alles bewaart wat nodig is om later naar het antwoord te kijken:
    # de code, het aantal records, de veldnamen en het record zelf.
    rijen = ruw(["0268010000045931"],
                haler=nep({"vbo": 200},
                          {"Pand_energieklasse": "D",
                           "Pand_bagverblijfsobjectid": "0268010000045931",
                           "Pand_bagpandid": "0268100000026050"}))
    check("ruw geeft een rij per vbo", len(rijen), 1)
    check("ruw bewaart de code", rijen[0].get("http"), 200)
    check("ruw telt de records", rijen[0].get("records_in_antwoord"), 1)
    check("ruw bewaart de veldnamen",
          "Pand_energieklasse" in (rijen[0].get("velden") or []), True)
    check("ruw leest het label ook",
          (rijen[0].get("gelezen") or {}).get("label"), "D")
    rijen = ruw(["X"], haler=nep({"vbo": 404}))
    check("ruw bij 404 geen record", rijen[0].get("record"), None)
    check("ruw bij 404 wel de code", rijen[0].get("http"), 404)

    # EN DE CONTROLE OP HET VASTGELEGDE ANTWOORD, OPZETTELIJK GEBROKEN. Een
    # controle die nooit rood heeft gestaan is een bewering. Hier wordt een
    # vastgelegd antwoord gemaakt met een zevende veldnaam erin, en de
    # controle hoort die te noemen.
    import tempfile
    with tempfile.TemporaryDirectory() as map_:
        leeg = os.path.join(map_, "bestaat-niet.json")
        f_leeg, n_leeg = proef_vastgelegd(leeg)
        check("zonder vastgelegd antwoord: nul gekeken", (f_leeg, n_leeg),
              ([], 0))

        goed = os.path.join(map_, "goed.json")
        # Met de rekenmethode erin, want een vastgelegd antwoord zonder
        # grondslag is zelf een fout en dat wordt hieronder apart gemeten.
        ok = {"Pand_energieklasse": "C", "Berekeningstype": nieuw}
        vastleggen([{"vbo": "A", "http": 200, "record": ok,
                     "gelezen": lees(ok)}], goed)
        f_goed, n_goed = proef_vastgelegd(goed)
        check("een goed vastgelegd antwoord geeft geen fout",
              (f_goed, n_goed), ([], 1))

        zevende = os.path.join(map_, "zevende.json")
        zev = dict(ok, nieuwLabelVeld="B")
        vastleggen([{"vbo": "A", "http": 200, "record": zev,
                     "gelezen": lees(ok)}], zevende)
        f_zev, _n = proef_vastgelegd(zevende)
        check("een onbekende labelveldnaam wordt gemeld", len(f_zev), 1)
        check("en hij noemt de veldnaam",
              "nieuwLabelVeld" in (f_zev[0] if f_zev else ""), True)

        anders = os.path.join(map_, "anders.json")
        vastleggen([{"vbo": "A", "http": 200, "record": ok,
                     "gelezen": {"label": "G"}}], anders)
        f_and, _n = proef_vastgelegd(anders)
        check("een ander label dan bij het ophalen wordt gemeld",
              len(f_and), 1)

        geen = os.path.join(map_, "geen-methode.json")
        kaal = {"Pand_energieklasse": "C"}
        vastleggen([{"vbo": "A", "http": 200, "record": kaal,
                     "gelezen": lees(kaal)}], geen)
        f_geen, _n = proef_vastgelegd(geen)
        check("een vastgelegd antwoord zonder rekenmethode wordt gemeld",
              len(f_geen), 1)
        check("en hij noemt de grondslag",
              "grondslag" in (f_geen[0] if f_geen else ""), True)

    # HET ECHTE VASTGELEGDE ANTWOORD, als het er is.
    echte_fouten, echt_gekeken = proef_vastgelegd()
    fouten.extend(echte_fouten)

    for f in fouten:
        print(f"FOUT {f}", file=sys.stderr)
    if echt_gekeken:
        vastgelegd = f"{echt_gekeken} vastgelegde echte antwoorden nagemeten"
    elif os.path.exists(VORM):
        vastgelegd = (f"{VORM} bestaat maar bevat geen enkel record, dus over "
                      f"de API zelf zegt deze proef niets")
    else:
        vastgelegd = (f"GEEN vastgelegd echt antwoord ({VORM} bestaat niet), "
                      f"dus over de API zelf zegt deze proef niets")
    print(f"Proef: {len(fouten)} fouten. Gedekt: de zes veldnamen, het "
          f"privelabel, de drie antwoordvormen, het huisnummer met letter en "
          f"toevoeging, de route vbo-eerst, de ruwe opvraging, en dat 404 een "
          f"antwoord is en 400 een weigering. Geen enkele aanroep. "
          f"{vastgelegd}.", file=sys.stderr)
    return 1 if fouten else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--proef", action="store_true",
                    help="De vormen nameten zonder aanroep.")
    ap.add_argument("--adres", default="",
                    help="Eén adres opvragen, met EP_API_KEY in de omgeving.")
    ap.add_argument("--postcode", default="")
    ap.add_argument("--vbo", default="",
                    help="Verblijfsobject-id. Bij --ruw mogen er meer, "
                         "gescheiden door komma's.")
    ap.add_argument("--ruw", action="store_true",
                    help="De antwoorden ruw opvragen en vastleggen, zonder "
                         "interpretatie. Vraagt EP_API_KEY in de omgeving.")
    ap.add_argument("--uit", default=VORM,
                    help=f"Waar --ruw het antwoord vastlegt. Standaard "
                         f"{VORM}.")
    a = ap.parse_args()
    if a.proef:
        sys.exit(proef())
    if a.ruw:
        ids = [v.strip() for v in a.vbo.split(",") if v.strip()]
        if not ids:
            print("--ruw vraagt --vbo met een of meer verblijfsobject-id's",
                  file=sys.stderr)
            sys.exit(1)
        rijen = ruw(ids)
        # De uitkomst naar stdout, voor wie wel in de log kan kijken.
        for r in rijen:
            print(json.dumps(r, ensure_ascii=False, sort_keys=True))
        met_record = [r for r in rijen if isinstance(r.get("record"), dict)]
        # ALLEEN VASTLEGGEN ALS ER IETS IN ZIT. Zonder sleutel of met alleen
        # 404's komt er geen record binnen, en dan zou dit een bestand
        # opleveren dat er is maar niets zegt. Juist dat verschil moet
        # zichtbaar blijven: een bestand dat bestaat leest als "gekeken".
        if met_record:
            vastleggen(rijen, a.uit)
        print(f"Ruw opgevraagd: {len(rijen)} verblijfsobjecten, "
              f"{sum(1 for r in rijen if r.get('http') == 200)} met HTTP 200, "
              f"{len(met_record)} met een record"
              + (f", vastgelegd in {a.uit}" if met_record else
                 ", niets vastgelegd"), file=sys.stderr)
        # Een ronde waarin geen enkel record binnenkwam is geen succes.
        sys.exit(0 if met_record else 1)
    if a.adres or a.vbo:
        nr, letter, toev = uit_adres(a.adres) if a.adres else ("", "", "")
        print(energielabel(a.vbo or None, a.postcode, nr, letter, toev))
    sys.exit(0)
