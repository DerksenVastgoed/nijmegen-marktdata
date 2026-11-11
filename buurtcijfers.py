#!/usr/bin/env python3
"""
Buurtcijfers van de ringbuurten uit de CBS Wijk- en Buurtkaart.

Haalt per buurt van de ring (ring.py) de eigendomsverdeling, WOZ, woningen,
huishoudens, inkomen en voorzieningen op uit de CBS Wijk- en Buurtkaart via
PDOK, en schrijft ze naar buurten_cbs.json. Tot 11 november heette dit
buurten_tabel.py en schreef het ook de tabel voor de brief; die tabel maakt de
brief nu zelf uit dit bestand.

Bron: https://api.pdok.nl/cbs/wijken-en-buurten-{jaar}/ogc/v1/collections/buurten/items
Open data, geen sleutel nodig.
"""

import argparse
import sys
import urllib.parse
import requests


try:
    from diagnose import leg_vast, wis
except Exception:  # noqa
    def leg_vast(*_a):
        pass

    def wis(*_a):
        pass

# --- CONFIG ---
CBS_PAD = "buurten_cbs.json"

# De ring staat in ring.py; hier alleen met de zijde erbij voor de tabel.
import ring as _ring
BUURTEN = [(b, _ring.zijde(b)) for b in _ring.BUURTEN]
GEMEENTE = "Nijmegen"
JAAR_NU = "2024"
# PDOK haalt oude jaargangen na verloop van tijd weg. Daarom proberen we
# meerdere jaren, van het verst terug naar het dichtstbij: hoe langer de
# periode, hoe betekenisvoller de trend. Het eerste jaar dat er nog is, wint.
JAREN_TREND = ["2021", "2022", "2023"]
PDOK_TMPL = ("https://api.pdok.nl/cbs/wijken-en-buurten-{jaar}"
             "/ogc/v1/collections/buurten/items?f=json&limit=2000"
             "&bbox=5.780,51.800,5.920,51.880")

# --------------


def _get(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def _pct(v):
    if v is None or v == "":
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= 100 else None


def _veld(p, namen):
    for n in namen:
        for k in (n, n.upper(), n.lower()):
            if k in p and p[k] not in (None, ""):
                return p[k]
    return None


def _eigendom(p):
    """Geeft koop, corp, over en 'rest' als % van ALLE woningen; som is 100."""
    koop = _pct(_veld(p, ["percentage_koopwoningen"]))
    corpH = _pct(_veld(p, ["perc_huurwoningen_in_bezit_woningcorporaties"]))
    overH = _pct(_veld(p, ["perc_huurwoningen_in_bezit_overige_verhuurders"]))
    if koop is None:
        return None, None, None, None
    huur = 100 - koop
    corp = round(huur * corpH / 100) if corpH is not None else None
    over = round(huur * overH / 100) if overH is not None else None
    bekend = round(koop) + (corp or 0) + (over or 0)
    rest = max(0, 100 - bekend)
    return round(koop), corp, over, rest



def _zoek_veld(props, bekende_namen, moet_bevatten, mag_niet_bevatten=()):
    """
    Zoek een veld, ook als het CBS de naam heeft veranderd.

    Eerst de bekende namen. Staat geen daarvan erin, dan het eerste veld dat
    ALLE woorden uit moet_bevatten heeft en geen enkel woord uit
    mag_niet_bevatten. Die regel is bewust streng: liever geen waarde dan een
    verkeerde. Een afstand tot een bos is geen afstand tot een station.

    Geeft de gebruikte naam terug, zodat het rapport kan melden dat er iets
    automatisch is gekozen.
    """
    for naam in bekende_namen:
        if naam in props:
            return naam, False
    for naam in sorted(props):
        laag = naam.lower()
        if (all(w in laag for w in moet_bevatten)
                and not any(w in laag for w in mag_niet_bevatten)):
            return naam, True
    return None, False


# Per soort: welke woorden moeten in de veldnaam staan, en welke niet
AFSTAND_REGELS = {
    "trein": (["afstand", "trein"], ["begraaf", "bos", "natuur", "recreat"]),
    "supermarkt": (["afstand", "supermarkt"], []),
    "huisarts": (["afstand", "huisarts"], ["post"]),
    # "Buitenschoolse opvang" bevat het woord school maar is kinderopvang.
    # Daarom eisen we "basis" en sluiten we opvang uit.
    "school": (["afstand", "basis"], ["opvang", "buitenschool", "kinderdag"]),
}
_AUTOMATISCH_GEKOZEN = {}


def _afstand(props, soort, bekende):
    moet, niet = AFSTAND_REGELS.get(soort, (["afstand", soort], []))
    naam, automatisch = _zoek_veld(props, bekende, moet, niet)
    if not naam:
        return None
    if automatisch:
        _AUTOMATISCH_GEKOZEN[f"afstand_{soort}"] = naam
    return _getal(props, [naam], 0, 100, decimalen=1)


def _eerste_bekend(*waarden):
    """De eerste waarde die niet None is. Anders dan 'or' telt nul hier mee."""
    for w in waarden:
        if w is not None:
            return w
    return None


def _gemiddelde_leeftijd(props):
    """
    Gewogen gemiddelde leeftijd uit de leeftijdsgroepen van het CBS.

    Het CBS publiceert geen gemiddelde leeftijd per buurt, wel het aantal
    inwoners per groep. Met het middelpunt van elke groep als schatting komt
    daar een bruikbaar gemiddelde uit. Het is een benadering, want binnen een
    groep zijn de leeftijden niet gelijk verdeeld.
    """
    som, aantal = 0.0, 0
    for velden, midden in LEEFTIJDSGROEPEN:
        n = _getal(props, velden, 0, 100000)
        if n:
            som += n * midden
            aantal += n
    return round(som / aantal, 1) if aantal else None


def _buurt_props(feats, naam):
    for f in feats:
        p = f.get("properties", {})
        for k in ("buurtnaam", "BUURTNAAM", "bu_naam", "BU_NAAM", "naam"):
            v = p.get(k)
            if v and str(v).strip().lower() == naam.lower() and str(p.get("gemeentenaam", GEMEENTE)).lower() == GEMEENTE.lower():
                return p
    return None


def _woningen(p):
    v = _veld(p, ["aantal_woningen", "woningvoorraad"])
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _woz(p):
    v = _veld(p, ["gemiddelde_woningwaarde", "gemiddelde_woz_waarde_woning"])
    try:
        return int(v) if v is not None and int(v) > 0 else None
    except (TypeError, ValueError):
        return None


# Mogelijke namen voor de gemiddelde woningoppervlakte. Of het CBS dit per buurt
# levert weten we niet zeker; vindt het script niets, dan logt het alle velden.
# Inkomen per buurt. Het CBS levert dit met ongeveer twee jaar vertraging en
# onderdrukt het bij kleine buurten, dus een lege waarde is normaal.
INKOMEN_VELDEN = [
    "gemiddeld_inkomen_per_inwoner",
    "gemiddeld_gestandaardiseerd_inkomen_van_huishoudens",
    "gemiddeld_inkomen_inwoner", "gem_inkomen_per_inwoner",
    "inkomen_per_inwoner",
]
INKOMEN_ONTVANGER_VELDEN = [
    "gemiddeld_inkomen_per_inkomensontvanger", "gem_inkomen_per_inkomensontvanger",
    "inkomen_per_inkomensontvanger",
]
# Het CBS heeft "laag inkomen" en "sociaal minimum" vervangen door een nieuwe
# armoededefinitie, ontwikkeld met Nibud en SCP. Beide reeksen staan erin,
# zodat het werkt met de oude en de nieuwe tabel.
LAAG_INKOMEN_VELDEN = [
    "percentage_huishoudens_met_een_laag_inkomen", "perc_huishoudens_laag_inkomen",
    "percentage_laag_inkomen", "perc_laag_inkomen",
    "percentage_huishoudens_onder_de_armoedegrens", "percentage_armoede",
    "perc_huishoudens_armoede", "percentage_huishoudens_in_armoede",
]

# Mediaan vermogen per buurt: het saldo van bezittingen en schulden. Dit is een
# gemeten cijfer, niet afgeleid uit leeftijd of inkomen. Bij weinig huishoudens
# onderdrukt het CBS de waarde.
VERMOGEN_VELDEN = [
    # De naam die het CBS werkelijk gebruikt, afgekort en al
    "mediaan_vermogen_van_particuliere_huish",
    "mediaan_vermogen_particuliere_huishoudens", "mediaan_vermogen",
    "med_vermogen_part_huish", "mediaan_vermogen_part_huishoudens",
    "mediaan_vermogen_van_particuliere_huishoudens",
]
MINIMUM_VELDEN = [
    "percentage_huishoudens_onder_of_rond_sociaal_minimum",
    "perc_huishoudens_onder_of_rond_sociaal_minimum",
    "percentage_onder_of_rond_sociaal_minimum",
]

# Huishoudenssamenstelling. Het aandeel alleenwonenden voorspelt de vraag naar
# kleine eenheden, en dat is waar de huur per m2 het hoogst ligt.
HUISHOUDENS_VELDEN = ["aantal_huishoudens", "aantal_particuliere_huishoudens"]
EENPERSOONS_VELDEN = [
    "percentage_eenpersoonshuishoudens", "perc_eenpersoonshuishoudens",
    "percentage_eenpersoons_huishoudens",
]
ZONDER_KINDEREN_VELDEN = [
    "percentage_huishoudens_zonder_kinderen", "perc_huishoudens_zonder_kinderen",
]
MET_KINDEREN_VELDEN = [
    "percentage_huishoudens_met_kinderen", "perc_huishoudens_met_kinderen",
]
GROOTTE_VELDEN = [
    "gemiddelde_huishoudsgrootte", "gemiddelde_huishoudensgrootte",
    "gem_huishoudensgrootte", "gemiddelde_huishoudens_grootte",
]

# Leeftijdsopbouw. Het CBS geeft inwoners per leeftijdsgroep; daar rekenen we
# een gewogen gemiddelde uit. Het middelpunt van de open bovengroep zetten we
# op 80, want daarboven wordt de groep snel dunner.
# Het CBS levert hier percentages per groep, geen aantallen. Voor een gewogen
# gemiddelde maakt dat niet uit: de gewichten tellen op tot honderd.
LEEFTIJDSGROEPEN = [
    (["percentage_personen_0_tot_15_jaar", "aantal_inwoners_0_tot_15_jaar"], 7.5),
    (["percentage_personen_15_tot_25_jaar", "aantal_inwoners_15_tot_25_jaar"], 20),
    (["percentage_personen_25_tot_45_jaar", "aantal_inwoners_25_tot_45_jaar"], 35),
    (["percentage_personen_45_tot_65_jaar", "aantal_inwoners_45_tot_65_jaar"], 55),
    (["percentage_personen_65_jaar_en_ouder", "aantal_inwoners_65_jaar_en_ouder"],
     75),
]

# Nabijheid van voorzieningen, in kilometers. Het CBS levert dit per buurt als
# gemiddelde afstand van een inwoner tot de dichtstbijzijnde voorziening.
# De eerste naam per soort is bevestigd in de run van 21 september 2026: het
# CBS schrijft ze als "<voorziening>_gemiddelde_afstand_in_km". De overige
# namen zijn oudere varianten, voor als het CBS terugvalt.
AFSTAND_VELDEN = {
    "trein": ["treinstation_gemiddelde_afstand_in_km",
              "afstand_tot_belangrijk_overstapstation",
              "afstand_tot_treinstation"],
    "supermarkt": ["grote_supermarkt_gemiddelde_afstand_in_km",
                   "afstand_tot_grote_supermarkt"],
    "huisarts": ["huisartsenpraktijk_gemiddelde_afstand_in_km",
                 "afstand_tot_huisartsenpraktijk"],
    # Nog niet bevestigd. De automatische keuze pakte op 21 september de
    # buitenschoolse opvang, wat geen school is.
    "school": ["basisonderwijs_gemiddelde_afstand_in_km",
               "basisschool_gemiddelde_afstand_in_km",
               "afstand_tot_school"],
}

OPPERVLAKTE_VELDEN = [
    "gemiddelde_woningoppervlakte", "gemiddeld_woonoppervlak",
    "gemiddelde_oppervlakte_woning", "gemiddeld_oppervlak_woning",
    "woonoppervlakte_gemiddeld", "gemiddelde_gebruiksoppervlakte",
    "gem_woonoppervlakte", "oppervlakte_wonen_gemiddeld",
]


def _getal(p, namen, minimum=None, maximum=None, decimalen=0):
    """
    Haalt een getal op en controleert of het binnen een zinnig bereik valt.

    Standaard afgerond op een heel getal, wat goed is voor aantallen en
    percentages. Afstanden, huishoudgrootte en inkomen hebben een decimaal
    nodig: 1,4 kilometer is geen 1, en 1,9 personen per huishouden is geen 2.
    """
    v = _veld(p, namen)
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if minimum is not None and v < minimum:
        return None
    if maximum is not None and v > maximum:
        return None
    return round(v, decimalen) if decimalen else round(v)


def _oppervlakte(p):
    v = _veld(p, OPPERVLAKTE_VELDEN)
    try:
        v = float(v)
        return round(v) if 15 <= v <= 400 else None
    except (TypeError, ValueError):
        return None


def _pijl(nu, toen):
    if nu is None or toen is None:
        return "—"
    d = nu - toen
    if d >= 3:
        return f"▲ +{d}"
    if d <= -3:
        return f"▼ {d}"
    return "▬ ±0" if abs(d) < 1 else f"▬ {d:+d}"


# DE TABEL VOOR DE BRIEF stond hier tot 11 november (render(), met een link
# naar een kaart van de brief). Die staat nu in buurten_tabel.py in de
# brief-repo, en leest buurten_cbs.json. Deze module haalt de CBS-buurtkaart op
# en schrijft de cijfers per buurt weg.


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()

    try:
        nu = _get(PDOK_TMPL.format(jaar=JAAR_NU))
    except Exception as e:  # noqa
        print(f"CBS {JAAR_NU} ophalen mislukt: {e}", file=sys.stderr); sys.exit(1)
    toen, jaar_trend = {"features": []}, None
    for jaar in JAREN_TREND:
        try:
            toen = _get(PDOK_TMPL.format(jaar=jaar))
            jaar_trend = jaar
            print(f"Trend tegen CBS {jaar}", file=sys.stderr)
            break
        except Exception as e:  # noqa
            print(f"  CBS {jaar} niet beschikbaar ({str(e)[:60]})",
                  file=sys.stderr)
    if not jaar_trend:
        print("Geen enkele oudere jaargang beschikbaar bij PDOK; trend "
              "uitgeschakeld. Controleer welke jaren er zijn op "
              "api.pdok.nl/cbs", file=sys.stderr)

    feats_nu = nu.get("features", [])
    feats_toen = toen.get("features", [])

    rijen = []
    for naam, zijde in BUURTEN:
        p_nu = _buurt_props(feats_nu, naam)
        if not p_nu:
            print(f"Waarschuwing: buurt {naam} niet gevonden in {JAAR_NU}", file=sys.stderr)
            continue
        koop, corp, over, onb = _eigendom(p_nu)
        p_toen = _buurt_props(feats_toen, naam)
        koop_toen = _eigendom(p_toen)[0] if p_toen else None
        rijen.append({
            "naam": naam, "zijde": zijde,
            "won": _woningen(p_nu), "woz": _woz(p_nu),
            "opp": _oppervlakte(p_nu),
            # Kenmerken die raken aan splitsen, renoveren en kamerverhuur
            "meergezins": _getal(p_nu, ["percentage_meergezinswoning"], 0, 100),
            "voor2000": _getal(p_nu, ["percentage_bouwjaarklasse_tot_2000"], 0, 100),
            "studenten": (_getal(p_nu, ["aantal_studenten_wo"], 0) or 0)
                         + (_getal(p_nu, ["aantal_studenten_hbo"], 0) or 0),
            "inwoners": _getal(p_nu, ["aantal_inwoners"], 0),
            "nietwoningen": _getal(p_nu, ["aantal_niet_woningvoorraad"], 0),
            # Leeftijd en bereikbaarheid
            "leeftijd": _gemiddelde_leeftijd(p_nu),
            **{f"afstand_{soort}": _afstand(p_nu, soort, velden)
               for soort, velden in AFSTAND_VELDEN.items()},
            # Huishoudens: wie woont er alleen en wie met hoeveel
            "huishoudens": _getal(p_nu, HUISHOUDENS_VELDEN, 0),
            "eenpersoons": _getal(p_nu, EENPERSOONS_VELDEN, 0, 100),
            "zonder_kinderen": _getal(p_nu, ZONDER_KINDEREN_VELDEN, 0, 100),
            "met_kinderen": _getal(p_nu, MET_KINDEREN_VELDEN, 0, 100),
            "huishoudgrootte": _getal(p_nu, GROOTTE_VELDEN, 1, 6, decimalen=1),
            # Inkomen zegt wat de buurt kan dragen aan huur
            # Ondergrens 1 in plaats van 0: het CBS zet -99999997 bij ontbrekend
            # Inkomen en vermogen publiceert het CBS met twee jaar vertraging.
            # Is het cijfer voor dit jaar er nog niet, dan het oudere jaar.
            "inkomen": (_getal(p_nu, INKOMEN_VELDEN, 1, 500, decimalen=1)
                        or _getal(p_toen or {}, INKOMEN_VELDEN, 1, 500,
                                  decimalen=1)),
            "inkomen_ontvanger": _getal(p_nu, INKOMEN_ONTVANGER_VELDEN, 0, 500),
            "laag_inkomen": (_getal(p_nu, LAAG_INKOMEN_VELDEN, 0, 100)
                             or _getal(p_toen or {}, LAAG_INKOMEN_VELDEN, 0, 100)),
            # Vermogen kan terecht nul of negatief zijn, dus alleen terugvallen
            # als er werkelijk niets is, niet bij een waarde van nul.
            "vermogen": _eerste_bekend(
                _getal(p_nu, VERMOGEN_VELDEN, -400, 5000),
                _getal(p_toen or {}, VERMOGEN_VELDEN, -400, 5000)),
            "sociaal_minimum": _getal(p_nu, MINIMUM_VELDEN, 0, 100),
            "bedrijven": _getal(p_nu, ["aantal_bedrijfsvestigingen"], 0),
            "leegstand": _getal(p_nu, ["percentage_leegstand_woningen"], 0, 100),
            "koop": koop, "corp": corp, "over": over, "onb": onb,
            "trend": _pijl(koop, koop_toen),
        })

    # Stadstotalen: alles wat in de opgehaalde set als Nijmegen geregistreerd staat.
    # Zo kun je de ring afzetten tegen de stad als geheel.
    stad = {"woningen": 0, "nietwoningen": 0, "inwoners": 0,
            "studenten": 0, "bedrijven": 0, "buurten": 0}
    for f in feats_nu:
        p = f.get("properties", {}) or {}
        if str(p.get("gemeentenaam", "")).lower() != GEMEENTE.lower():
            continue
        stad["buurten"] += 1
        stad["woningen"] += _getal(p, ["woningvoorraad", "aantal_woningen"], 0) or 0
        stad["nietwoningen"] += _getal(p, ["aantal_niet_woningvoorraad"], 0) or 0
        stad["inwoners"] += _getal(p, ["aantal_inwoners"], 0) or 0
        stad["studenten"] += ((_getal(p, ["aantal_studenten_wo"], 0) or 0)
                              + (_getal(p, ["aantal_studenten_hbo"], 0) or 0))
        stad["bedrijven"] += _getal(p, ["aantal_bedrijfsvestigingen"], 0) or 0
    print(f"Stadstotalen over {stad['buurten']} buurten: "
          f"{stad['woningen']} woningen, {stad['inwoners']} inwoners, "
          f"{stad['studenten']} studenten", file=sys.stderr)

    wis("buurtcijfers")
    eerste_d = _buurt_props(feats_nu, BUURTEN[0][0]) or {}
    for veld, naam in sorted(_AUTOMATISCH_GEKOZEN.items()):
        leg_vast("buurtcijfers",
                 f"AUTOMATISCH: voor {veld} is het veld '{naam}' gekozen, omdat "
                 f"de verwachte naam niet bestond. Controleer of dat klopt.")

    def _meld(veld, zoekwoorden, namen):
        """Bestaat het veld maar is het leeg, of heet het anders?"""
        if any(r.get(veld) is not None for r in rijen):
            return
        # Staat een van de verwachte namen er wel in, maar zonder bruikbare waarde?
        aanwezig = [(n, eerste_d.get(n)) for n in namen if n in eerste_d]
        if aanwezig:
            leg_vast("buurtcijfers",
                     f"{veld}: het veld bestaat wel, maar de waarde is "
                     f"{aanwezig[0][1]!r}. Bij het CBS betekent een lege of "
                     f"negatieve waarde meestal dat het cijfer voor dit jaar nog "
                     f"niet gepubliceerd is.")
            return
        # De meest specifieke zoekwoorden eerst, zodat "trein" niet wegvalt
        # achter acht velden met "afstand" erin
        lijkt = []
        for z in zoekwoorden:
            for k in sorted(eerste_d):
                if z in k.lower() and k not in lijkt:
                    lijkt.append(k)
        lijkt = lijkt[:8]
        leg_vast("buurtcijfers",
                 f"{veld}: niet gevonden onder de verwachte namen. Velden die erop "
                 f"lijken: {', '.join(lijkt) if lijkt else 'geen'}.")

    _meld("inkomen", ("inkom",), INKOMEN_VELDEN)
    _meld("vermogen", ("vermogen",), VERMOGEN_VELDEN)
    _meld("leeftijd", ("jaar", "leeftijd"),
          [n for groep, _m in LEEFTIJDSGROEPEN for n in groep])
    _meld("afstand_trein", ("trein", "station", "overstap", "afstand"),
          AFSTAND_VELDEN["trein"])

    if rijen and not any(r.get("afstand_trein") for r in rijen):
        eerste_a = _buurt_props(feats_nu, BUURTEN[0][0]) or {}
        afstandachtig = sorted(k for k in eerste_a
                               if "afstand" in k.lower() or "nabij" in k.lower())
        print("Geen afstandsgegevens gevonden in de CBS-buurtkaart.",
              file=sys.stderr)
        print(f"  Velden die op afstand lijken: {afstandachtig or 'geen'}",
              file=sys.stderr)

    if rijen and not any(r.get("leeftijd") for r in rijen):
        eerste_l = _buurt_props(feats_nu, BUURTEN[0][0]) or {}
        leeftijdachtig = sorted(k for k in eerste_l if "jaar" in k.lower())
        print("Geen leeftijdsopbouw gevonden in de CBS-buurtkaart.",
              file=sys.stderr)
        print(f"  Velden die op leeftijd lijken: {leeftijdachtig or 'geen'}",
              file=sys.stderr)

    if rijen and not any(r.get("vermogen") for r in rijen):
        eerste_v = _buurt_props(feats_nu, BUURTEN[0][0]) or {}
        vermogensachtig = sorted(k for k in eerste_v
                                 if "vermogen" in k.lower() or "armoede" in k.lower())
        print("Geen vermogensgegevens gevonden in de CBS-buurtkaart.", file=sys.stderr)
        print(f"  Velden die op vermogen of armoede lijken: "
              f"{vermogensachtig or 'geen'}", file=sys.stderr)

    if rijen and not any(r.get("eenpersoons") for r in rijen):
        eerste_h = _buurt_props(feats_nu, BUURTEN[0][0]) or {}
        huishoudachtig = sorted(k for k in eerste_h if "huishoud" in k.lower())
        print("Geen huishoudensgegevens gevonden in de CBS-buurtkaart.",
              file=sys.stderr)
        print(f"  Velden die op huishoudens lijken: {huishoudachtig or 'geen'}",
              file=sys.stderr)

    if rijen and not any(r.get("inkomen") or r.get("laag_inkomen") for r in rijen):
        eerste_i = _buurt_props(feats_nu, BUURTEN[0][0]) or {}
        inkomensachtig = sorted(k for k in eerste_i
                                if "inkom" in k.lower() or "minimum" in k.lower()
                                or "welvaart" in k.lower())
        print("Geen inkomensgegevens gevonden in de CBS-buurtkaart.", file=sys.stderr)
        print(f"  Velden die op inkomen lijken: {inkomensachtig or 'geen'}",
              file=sys.stderr)

    if rijen and not any(r.get("opp") for r in rijen):
        eerste = _buurt_props(feats_nu, BUURTEN[0][0]) or {}
        print("Geen gemiddelde woningoppervlakte gevonden in de CBS-gegevens.",
              file=sys.stderr)
        print(f"Beschikbare velden: {sorted(eerste.keys())}", file=sys.stderr)


    # Ook als los gegevensbestand wegschrijven. Het marktprijzen-script toont
    # deze cijfers per buurt, maar alleen bij buurten waar aanbod in staat.
    import json as _json
    gegevens = {r["naam"]: {k: r.get(k) for k in
                            ("naam", "zijde", "onb",
                             "won", "woz", "koop", "corp", "over", "trend", "opp",
                             "meergezins", "voor2000", "studenten", "leegstand",
                             "inwoners", "nietwoningen", "bedrijven",
                             "inkomen", "inkomen_ontvanger", "laag_inkomen",
                             "sociaal_minimum", "vermogen", "huishoudens", "eenpersoons",
                             "zonder_kinderen", "met_kinderen", "huishoudgrootte",
                             "leeftijd", "afstand_trein", "afstand_supermarkt",
                             "afstand_huisarts", "afstand_school")}
                for r in rijen}
    gegevens["_nijmegen"] = stad
    with open(CBS_PAD, "w", encoding="utf-8") as f:
        _json.dump(gegevens, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"Buurtgegevens opgeslagen in {CBS_PAD}", file=sys.stderr)


if __name__ == "__main__":
    main()
