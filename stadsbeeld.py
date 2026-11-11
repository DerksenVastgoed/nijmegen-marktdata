#!/usr/bin/env python3
"""
De begrenzing van het voorbeschermd stadsbeeld Wederopbouwcentrum ophalen.

WAAROM. Sinds 4 september 2026 heeft Nijmegen het naoorlogse centrum in het
omgevingsplan voorbeschermd als stadsbeeld (CVDR766239): sloop van
gebouwdelen aan de openbare ruimte en het wijzigen van gevels en dakvlakken
die naar openbaar gebied gekeerd zijn, zijn dan vergunningplichtig. Dat staat
in geen van onze twee bronnen: ruimtelijkeplannen.nl mist het omgevingsplan
in de nieuwe standaard, en de RCE kent alleen rijksgezichten. Gemeten op 17
oktober: 466 panden in het Stadscentrum liggen in geen rijksgezicht, en een
deel daarvan valt hier waarschijnlijk onder.

DE BRON. De regeling verwijst in Bijlage I naar twee geografische
informatieobjecten (GIO's), met een JOIN-identificatie bij de officiele
bekendmakingen. Een GIO is een openbare publicatie van de overheid. Deze stap
volgt de JOIN-identificatie, bewaart wat hij vindt en zoekt naar de
geometrie, zonder sleutel. Eerst kijkt hij in robots.txt van elke host; staat
daar dat automatisch ophalen niet mag, dan stopt hij voor die host en zegt
dat. Dat is dezelfde regel als bij jeleefomgeving.nl.

  python3 stadsbeeld.py --verken
"""
import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
import urllib.robotparser

GIO = {
    "werkingsgebied": "https://identifier.officielebekendmakingen.nl/join/id/"
                      "regdata/gm0268/2026/e2b2210e98944ca387229c231879c6d4/"
                      "nld@2026-09-03;09225018",
    "stadsbeeldobject": "https://identifier.officielebekendmakingen.nl/join/"
                        "id/regdata/gm0268/2026/7b82e3db52154524910d9bf933a"
                        "7213f/nld@2026-09-03;09225018",
}
AGENT = "NijmegenVastgoedMonitor/1.0"
VERSLAG = "stadsbeeld_verslag.md"
_robots = {}


def mag(url):
    """Mag dit volgens robots.txt van de host? Onbereikbare robots.txt telt
    als niet nagekeken, en dan halen we niets op."""
    deel = urllib.parse.urlsplit(url)
    host = f"{deel.scheme}://{deel.netloc}"
    if host not in _robots:
        rp = urllib.robotparser.RobotFileParser(host + "/robots.txt")
        try:
            rp.read()
            _robots[host] = rp
        except Exception as e:
            _robots[host] = e
    rp = _robots[host]
    if isinstance(rp, Exception):
        return None, f"robots.txt van {host} niet te lezen: {rp}"
    if not rp.can_fetch(AGENT, url):
        return False, f"robots.txt van {host} staat dit niet toe"
    return True, ""


def haal(url, r):
    ok, reden = mag(url)
    if not ok:
        r.append(f"- NIET OPGEHAALD {url}: {reden}")
        return None, None, None
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            inhoud = resp.read()
            return resp.geturl(), resp.headers.get("Content-Type", ""), inhoud
    except Exception as e:
        r.append(f"- FOUT {url}: {type(e).__name__} {str(e)[:200]}")
        return None, None, None


def verken():
    r = ["# Verkenning stadsbeeld Wederopbouwcentrum", ""]
    gevonden = {}
    for naam, url in GIO.items():
        r.append(f"## {naam}")
        r.append(f"JOIN: `{url}`")
        eind, soort, inhoud = haal(url, r)
        if inhoud is None:
            r.append("")
            continue
        tekst = inhoud.decode("utf-8", errors="replace")
        r.append(f"- eindadres na doorverwijzing: `{eind}`")
        r.append(f"- type: {soort}, {len(inhoud)} bytes")
        links = sorted(set(re.findall(r'href="([^"]+)"', tekst)))
        geo = [l for l in links if re.search(r"\.(gml|xml|json|zip)(\?|$)", l,
                                             re.I)]
        r.append(f"- links naar mogelijke geometrie: {geo[:20]}")
        r.append(f"- begin van het antwoord: `{tekst[:800]}`")
        for l in geo[:5]:
            volledig = urllib.parse.urljoin(eind, l)
            e2, s2, i2 = haal(volledig, r)
            if i2 is None:
                continue
            t2 = i2.decode("utf-8", errors="replace")
            heeft = bool(re.search(r"posList|coordinates|Polygon", t2))
            r.append(f"  - `{e2}`: {s2}, {len(i2)} bytes, geometrie "
                     f"{'ja' if heeft else 'nee'}")
            if heeft:
                pad = f"stadsbeeld_{naam}{'.gml' if 'gml' in (s2 or '') or '<' in t2[:5] else '.json'}"
                with open(pad, "wb") as f:
                    f.write(i2)
                gevonden[naam] = {"bron": e2, "bestand": pad,
                                  "bytes": len(i2)}
                r.append(f"  - bewaard als {pad}")
                break
        r.append("")
    r.append(f"Gevonden: {json.dumps(gevonden, ensure_ascii=False)}")
    with open(VERSLAG, "w", encoding="utf-8") as f:
        f.write("\n".join(r) + "\n")
    print("\n".join(r))
    return 0


WERKINGSGEBIED = "stadsbeeld_werkingsgebied.gml"
OBJECTEN = "stadsbeeld_stadsbeeldobject.gml"
_GML = "{http://www.opengis.net/gml/3.2}"


def vlakken(pad):
    """De vlakken uit een GIO als GeoJSON-achtige Polygon-dicts, in RD
    (EPSG:28992, zoals het GIO zelf zegt). None als het bestand er niet is:
    dat is niet nagekeken, en geen leeg gebied."""
    import xml.etree.ElementTree as ET
    try:
        boom = ET.parse(pad)
    except (OSError, ET.ParseError):
        return None
    uit = []
    for poly in boom.iter(_GML + "Polygon"):
        ringen = []
        for pl in poly.iter(_GML + "posList"):
            w = [float(x) for x in (pl.text or "").split()]
            ringen.append([[w[i], w[i + 1]] for i in range(0, len(w) - 1, 2)])
        if ringen:
            uit.append({"type": "Polygon", "coordinates": ringen})
    return uit


# HET HELE OMGEVINGSPLAN, NIET ALLEEN HET STADSBEELD. 18 oktober: de vraag
# was welke gemeentelijke bescherming er nog meer is (gemeentelijke
# monumenten, andere stadsbeelden; een oud commentaar sprak van acht). Het
# omgevingsplan noemt in Bijlage I alle geografische informatieobjecten, maar
# een samenvatting van de pagina gaf die lijst niet terug. Deze stap leest de
# pagina zelf, bewaart elke JOIN-identificatie met haar naam, en haalt de
# geometrie op van de objecten waarvan de naam op erfgoed wijst. Gemeentelijke
# monumenten zijn onder de Omgevingswet mogelijk geen GIO maar een lijst; dan
# zegt het verslag dat er geen GIO met die naam is, en dat is iets anders dan
# "geen gemeentelijke monumenten".
OMGEVINGSPLAN = "https://lokaleregelgeving.overheid.nl/CVDR696550"
ERFGOEDWOORDEN = ("monument", "stadsgezicht", "stadsbeeld", "dorpsgezicht",
                  "erfgoed", "cultuurhistor", "karakteristiek", "beeldbepal")
GIO_LIJST = "omgevingsplan_gio.json"
GIO_VERSLAG = "omgevingsplan_gio_verslag.md"


def gio_uit_pagina(html):
    """[(naam, join-url)] uit de HTML van een regeling. De naam is de tekst
    van de link of, als die de URL zelf is, de tekst van de tabelcel ervoor."""
    uit, gezien = [], set()
    patroon = re.compile(
        r'(?:<td[^>]*>\s*(?P<cel>[^<]{2,200}?)\s*</td>\s*<td[^>]*>\s*)?'
        r'<a[^>]+href="(?P<url>https?://identifier\.officielebekendmakingen'
        r'\.nl/join/id/regdata/[^"]+)"[^>]*>(?P<tekst>[^<]*)</a>', re.S)
    for m in patroon.finditer(html):
        url = m.group("url").replace("&amp;", "&")
        tekst = (m.group("tekst") or "").strip()
        naam = (m.group("cel") or "").strip() if (
            not tekst or tekst.startswith("http")) else tekst
        if url not in gezien:
            gezien.add(url)
            uit.append((naam, url))
    return uit


def naam_uit_titel(html):
    """De naam van een informatieobject uit de titel van zijn pagina bij de
    officiele bekendmakingen.

    WAAROM UIT DE TITEL. De eerste ronde, 18 oktober, las de namen uit de
    bijlage van het omgevingsplan, met een regex op een vorm die ik had
    aangenomen. Die vorm klopte niet: de linktekst is daar het JOIN-pad zelf,
    en van de 31 objecten kreeg er geen een naam, dus vond de zeef nul
    erfgoedobjecten. De pagina waar de JOIN-identificatie naar verwijst heeft
    wel een titel met de naam, dat bleek bij het stadsbeeld:
    "Waardengebied erfgoed - voorbeschermd stadsbeeld | Overheid.nl > ...".
    """
    import html as _html
    m = re.search(r"<title>(.*?)</title>", html or "", re.S)
    if not m:
        return ""
    t = _html.unescape(m.group(1)).strip()
    return t.split(" | ")[0].strip()


def verken_omgevingsplan():
    r = ["# Geografische informatieobjecten in het omgevingsplan", "",
         f"Regeling: `{OMGEVINGSPLAN}`", ""]
    eind, soort, inhoud = haal(OMGEVINGSPLAN, r)
    if inhoud is None:
        with open(GIO_VERSLAG, "w", encoding="utf-8") as f:
            f.write("\n".join(r) + "\n")
        print("\n".join(r))
        return 0
    html = inhoud.decode("utf-8", errors="replace")
    alle = gio_uit_pagina(html)
    r.append(f"- eindadres `{eind}`, {len(inhoud)} bytes, {len(alle)} "
             f"informatieobjecten met een JOIN-identificatie")
    # Elke JOIN-identificatie volgen voor de naam: het zijn er tientallen,
    # geen duizenden, en de bijlage zelf noemt de namen niet leesbaar.
    paginas = {}
    benoemd = []
    for n, u in alle:
        e1, _s1, i1 = haal(u, r)
        t1 = i1.decode("utf-8", errors="replace") if i1 is not None else ""
        naam = naam_uit_titel(t1) or n
        paginas[u] = (e1, t1)
        benoemd.append((naam, u))
    alle = benoemd
    erfgoed = [(n, u) for n, u in alle
               if any(w in n.lower() for w in ERFGOEDWOORDEN)]
    r.append(f"- waarvan {len(erfgoed)} met een naam die op erfgoed wijst")
    r.append("")
    r.append("## Alle namen")
    r.append("")
    for n, u in alle:
        r.append(f"- {n or '(geen naam)'}")
    r.append("")
    r.append("## Erfgoed, met geometrie")
    r.append("")
    resultaat = []
    for i, (naam, url) in enumerate(erfgoed[:40]):
        e1, t1 = paginas.get(url, (None, ""))
        if not t1:
            continue
        gml = [l for l in re.findall(r'href="([^"]+\.gml)"', t1)]
        rij = {"naam": naam, "join": url, "pagina": e1, "gml": None}
        if gml:
            g_url = urllib.parse.urljoin(e1, gml[0])
            e2, _s2, i2 = haal(g_url, r)
            if i2 is not None:
                pad = f"omgevingsplan_gio_{i:02d}.gml"
                with open(pad, "wb") as f:
                    f.write(i2)
                n_vlak = i2.count(b"<gml:Polygon")
                rij.update(gml=e2, bestand=pad, vlakken=n_vlak)
        resultaat.append(rij)
        r.append(f"- {naam}: "
                 + (f"{rij.get('vlakken')} vlakken, bewaard als "
                    f"{rij.get('bestand')}" if rij.get("bestand")
                    else "geen GML gevonden"))
    with open(GIO_LIJST, "w", encoding="utf-8") as f:
        json.dump({"regeling": OMGEVINGSPLAN, "pagina": eind,
                   "alle": [{"naam": n, "join": u} for n, u in alle],
                   "erfgoed": resultaat}, f, ensure_ascii=False, indent=1)
    with open(GIO_VERSLAG, "w", encoding="utf-8") as f:
        f.write("\n".join(r) + "\n")
    print("\n".join(r[:60]))
    return 0


# GEMEENTELIJKE MONUMENTEN. 18 oktober: het omgevingsplan heeft 31
# informatieobjecten en geen enkel daarvan is een gemeentelijk monument. De
# Erfgoedverordening (CVDR731607, art. 2) schrijft een register voor dat
# "door eenieder te raadplegen" is, zonder te zeggen waar. nijmegen.nl heeft
# een pagina "Monumentenlijst" met een lijst of kaart, en de gemeente heeft
# een GeoServer op services.nijmegen.nl. Deze stap legt vast wat de pagina
# insluit (iframes, kaartlinks) en welke lagen de GeoServer kent met
# monument, erfgoed of stadsbeeld in de naam.
MONUMENTENPAGINA = "https://www.nijmegen.nl/cultuur/monumentenlijst/"
GEOSERVER = ("https://services.nijmegen.nl/geoservices/ows?"
             "service=WMS&request=GetCapabilities")
MON_VERSLAG = "monumenten_verslag.md"


def lagen_uit_capabilities(xml):
    """(naam, titel) van elke laag in een WMS GetCapabilities."""
    uit = []
    for blok in re.findall(r"<Layer[^>]*>(.*?)</Layer>", xml or "", re.S):
        naam = re.search(r"<Name>([^<]+)</Name>", blok)
        titel = re.search(r"<Title>([^<]+)</Title>", blok)
        if naam:
            uit.append((naam.group(1).strip(),
                        titel.group(1).strip() if titel else ""))
    return uit


# TWEEDE RONDE, 18 OKTOBER. De monumentenlijst-pagina sluit geen kaart of
# bestand in (geen iframe, geen downloadlink), en de algemene GeoServer-ingang
# gaf 401. De open lagen van de gemeente zitten per werkruimte
# (extern_Mobiliteit, extern_Sport_Speel, ...), en de gemeente publiceert ze
# als "odn-..." op data.overheid.nl. Die catalogus heeft een CKAN-API; daar
# zoeken naar monumenten levert de echte werkruimte- en laagnamen, in plaats
# van ze te raden.
CKAN = ("https://data.overheid.nl/data/api/3/action/package_search?"
        "q=monumenten%20nijmegen&rows=50")


def datasets_uit_ckan(antwoord):
    """[(titel, [resource-url])] uit een CKAN package_search-antwoord."""
    try:
        d = json.loads(antwoord)
    except ValueError:
        return None
    uit = []
    for pk in (d.get("result") or {}).get("results") or []:
        urls = [res.get("url") for res in pk.get("resources") or []
                if res.get("url")]
        uit.append((pk.get("title") or pk.get("name") or "", urls))
    return uit


def verken_monumenten():
    r = ["# Verkenning gemeentelijke monumenten", ""]
    _e, _s, inhoud = haal(CKAN, r)
    sets = datasets_uit_ckan(inhoud.decode("utf-8", "replace")) if inhoud \
        else None
    r.append(f"## data.overheid.nl, zoeken op 'monumenten nijmegen'")
    if sets is None:
        r.append("- geen leesbaar antwoord")
    else:
        r.append(f"- {len(sets)} datasets")
        for titel, urls in sets:
            r.append(f"- {titel}")
            r += [f"  - {u}" for u in urls[:6]]
    r.append("")
    for titel, urls in (sets or []):
        if not re.search(r"monument", titel, re.I):
            continue
        for u in urls:
            if "services.nijmegen.nl" in u:
                werk = re.search(r"geoservices/([^/]+)/", u)
                if werk:
                    caps = (f"https://services.nijmegen.nl/geoservices/"
                            f"{werk.group(1)}/ows?service=WFS&"
                            f"request=GetCapabilities")
                    _e2, _s2, c = haal(caps, r)
                    if c is not None:
                        namen = re.findall(r"<(?:wfs:)?Name>([^<]+)</",
                                           c.decode("utf-8", "replace"))
                        r.append(f"- WFS {werk.group(1)}: {namen[:30]}")
    r.append("")
    eind, soort, inhoud = haal(MONUMENTENPAGINA, r)
    if inhoud is not None:
        t = inhoud.decode("utf-8", errors="replace")
        bronnen = sorted(set(re.findall(r'<iframe[^>]+src="([^"]+)"', t)))
        links = sorted(set(l for l in re.findall(r'href="([^"]+)"', t)
                           if re.search(r"kaart|atlas|monument|geo|\.pdf|"
                                        r"\.xlsx?|\.csv", l, re.I)))
        r.append(f"## {MONUMENTENPAGINA}")
        r.append(f"- eindadres `{eind}`, {len(inhoud)} bytes")
        r.append(f"- iframes: {bronnen}")
        r.append("- links:")
        r += [f"  - {l}" for l in links[:60]]
        r.append("")
    eind, soort, inhoud = haal(GEOSERVER, r)
    if inhoud is not None:
        lagen = lagen_uit_capabilities(inhoud.decode("utf-8", "replace"))
        raak = [(n, t) for n, t in lagen
                if re.search(r"monument|erfgoed|stadsbeeld|stadsgezicht|"
                             r"cultuurhist", n + " " + t, re.I)]
        r.append(f"## GeoServer `{GEOSERVER}`")
        r.append(f"- {len(lagen)} lagen, waarvan {len(raak)} over erfgoed:")
        r += [f"  - `{n}`: {t}" for n, t in raak]
        r.append("")
    with open(MON_VERSLAG, "w", encoding="utf-8") as f:
        f.write("\n".join(r) + "\n")
    print("\n".join(r))
    return 0


# DE REGELS VOOR EEN GEMEENTELIJK STADSBEELD. 19 oktober 2026. Het dossier
# zei bij een stadsbeeldobject "welke wijzigingen precies vergunningplichtig
# zijn, staat in het aanwijzingsbesluit en is hier niet nagelezen". Deze stap
# leest de twee regelingen waar die regels kunnen staan, de
# Erfgoedverordening en het omgevingsplan, en schrijft elk artikel op waarin
# stadsbeeld voorkomt, met de volledige tekst. Wet- en regelgeving valt niet
# onder het auteursrecht (Auteurswet art. 11), dus de tekst mag in de repo.
REGELINGEN = {"Erfgoedverordening Nijmegen":
              "https://lokaleregelgeving.overheid.nl/CVDR731607",
              "Omgevingsplan Nijmegen": OMGEVINGSPLAN}
REGELS_VERSLAG = "stadsbeeld_regels.md"
# "verbodsbepaling" erbij om art. 14 (gemeentelijk monument) naast art. 19
# (stadsbeeldobject) te kunnen leggen.
REGELWOORDEN = ("stadsbeeld", "verbodsbepaling")


def tekst_uit_html(html):
    """Platte tekst met een regel per blok, zonder scripts en stijlen."""
    import html as _html
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html or "")
    t = re.sub(r"(?i)<br\s*/?>|</(p|div|h\d|li|tr|td|th|dt|dd)>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = _html.unescape(t)
    regels = [" ".join(x.split()) for x in t.split("\n")]
    return "\n".join(x for x in regels if x)


def artikelen(tekst):
    """[(kop, tekst)] per artikel: een regel die met "Artikel" begint, opent
    een artikel; alles tot de volgende zulke regel hoort erbij."""
    uit, kop, buf = [], None, []
    for regel in tekst.split("\n"):
        if re.match(r"Artikel\s+[\dIVXLC][\w.:]*\b", regel):
            if kop:
                uit.append((kop, "\n".join(buf)))
            kop, buf = regel, []
        elif kop:
            buf.append(regel)
    if kop:
        uit.append((kop, "\n".join(buf)))
    return uit


def lees_regels():
    r = ["# Regels over stadsbeelden", "",
         "Elk artikel waarin " + " of ".join(REGELWOORDEN) + " voorkomt, "
         "met de volledige tekst. Bron per regeling hieronder.", ""]
    for naam, url in REGELINGEN.items():
        r.append(f"## {naam}")
        r.append("")
        eind, _s, inhoud = haal(url, r)
        if inhoud is None:
            r.append("- NIET GELEZEN")
            r.append("")
            continue
        tekst = tekst_uit_html(inhoud.decode("utf-8", errors="replace"))
        alle = artikelen(tekst)
        raak = [(k, t) for k, t in alle
                if any(w in (k + t).lower() for w in REGELWOORDEN)]
        # Waar komt het woord buiten de artikelen voor? Nul artikelen is
        # anders dan nul vermeldingen.
        r.append(f"- het woord stadsbeeld staat {tekst.lower().count('stadsbeeld')} "
                 f"keer in de hele tekst")
        r.append(f"- `{eind}`, {len(alle)} artikelen gelezen, {len(raak)} "
                 f"over stadsbeelden")
        if not alle:
            r.append("- GEEN ARTIKELEN HERKEND: de indeling van de pagina is "
                     "anders dan aangenomen; dit is geen nul")
        r.append("")
        for k, t in raak[:60]:
            r.append(f"### {k}")
            r.append("")
            r.append(t[:6000])
            r.append("")
    with open(REGELS_VERSLAG, "w", encoding="utf-8") as f:
        f.write("\n".join(r) + "\n")
    print("\n".join(r[:40]))
    return 0


def proef():
    afw = []
    html = ('<tr><td>Gemeentelijk monument</td><td><a href="https://'
            'identifier.officielebekendmakingen.nl/join/id/regdata/gm0268/'
            '2024/abc/nld@2024-01-01;1">https://identifier.officielebekend'
            'makingen.nl/join/id/regdata/gm0268/2024/abc/nld@2024-01-01;1'
            '</a></td></tr><a href="https://identifier.officielebekendmakingen'
            '.nl/join/id/regdata/gm0268/2024/def/nld@2024-01-01;1">Molen'
            'biotoop</a>')
    uit = gio_uit_pagina(html)
    if len(uit) != 2:
        afw.append(f"de JOIN-identificaties worden niet gevonden: {uit}")
    # Een echte titel, uit stadsbeeld_verslag.md van 18 oktober.
    echt = ("<title>Waardengebied erfgoed - voorbeschermd stadsbeeld | "
            "Overheid.nl &gt; Offici&#xEB;le bekendmakingen</title>")
    if naam_uit_titel(echt) != "Waardengebied erfgoed - voorbeschermd stadsbeeld":
        afw.append(f"de naam uit de titel wordt niet gelezen: "
                   f"{naam_uit_titel(echt)!r}")
    if not any(w in naam_uit_titel(echt).lower() for w in ERFGOEDWOORDEN):
        afw.append("het stadsbeeld valt niet onder de erfgoedwoorden")
    if datasets_uit_ckan('{"result":{"results":[{"title":"Monumenten",'
                         '"resources":[{"url":"https://x/y"}]}]}}') != [
            ("Monumenten", ["https://x/y"])]:
        afw.append("de CKAN-zoekresultaten worden niet gelezen")
    if datasets_uit_ckan("<html>") is not None:
        afw.append("een onleesbaar CKAN-antwoord telt als nul datasets")
    caps = ("<Layer><Name>extern_Erfgoed:gemeentelijke_monumenten</Name>"
            "<Title>Gemeentelijke monumenten</Title></Layer>")
    if lagen_uit_capabilities(caps) != [
            ("extern_Erfgoed:gemeentelijke_monumenten",
             "Gemeentelijke monumenten")]:
        afw.append("de lagen uit GetCapabilities worden niet gelezen")
    # Artikelen uit een regeling: kop tot de volgende kop.
    t = tekst_uit_html("<h3>Hoofdstuk 3</h3><h4>Artikel 14 Verboden</h4>"
                       "<p>1. Het is verboden een beschermd stadsbeeld te "
                       "ontsieren.</p><h4>Artikel 15 Vergunning</h4><p>Ander"
                       "</p><script>Artikel 99</script>")
    a = artikelen(t)
    if [k for k, _ in a] != ["Artikel 14 Verboden", "Artikel 15 Vergunning"] \
            or "stadsbeeld" not in a[0][1] or "Artikel 99" in t:
        afw.append(f"de artikelen worden verkeerd gesplitst: {a}")
    for a in afw:
        print("AFWIJKING: " + a, file=sys.stderr)
    print(f"Proef stadsbeeld: {len(afw)} afwijkingen", file=sys.stderr)
    return 1 if afw else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verken", action="store_true")
    ap.add_argument("--omgevingsplan", action="store_true")
    ap.add_argument("--proef", action="store_true")
    ap.add_argument("--monumenten", action="store_true")
    ap.add_argument("--regels", action="store_true")
    a = ap.parse_args()
    if a.proef:
        return proef()
    if a.regels:
        return lees_regels()
    if a.monumenten:
        return verken_monumenten()
    if a.omgevingsplan:
        return verken_omgevingsplan()
    if a.verken:
        return verken()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
