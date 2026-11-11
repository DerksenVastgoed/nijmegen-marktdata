#!/usr/bin/env python3
"""
Welke kaartlagen de KaartViewer van de gemeente laadt (kaart.nijmegen.nl).

WAAROM. 18 oktober 2026, Mark gaf https://kaart.nijmegen.nl/menu/index.html.
De pagina is een JavaScript-app: zonder browser staat er alleen "KaartViewer
Menu werkt niet goed als JavaScript is uitgeschakeld", en de lagen komen pas
na het laden binnen. De browsers op Marks computer waren vanuit deze sessie
niet bereikbaar. Daarom laadt deze stap de pagina in een headless Chromium in
de workflow en schrijft hij op welke adressen de pagina opvraagt: de
configuratie, de werkruimtes op services.nijmegen.nl en de lagen. Eerst
robots.txt, zoals overal; staat die het niet toe, dan gebeurt er niets.

  python3 kaartviewer.py --verken
"""
import argparse
import json
import re
import sys

import stadsbeeld  # mag(): robots.txt eerst, een implementatie

START = "https://kaart.nijmegen.nl/menu/index.html"
VERSLAG = "kaartviewer_verslag.md"
INTERESSANT = re.compile(r"geoservices|wms|wfs|ows|\.json|config|layer|laag|"
                         r"monument|erfgoed|cultuur", re.I)


def verken():
    r = ["# KaartViewer gemeente Nijmegen", "", f"Start: `{START}`", ""]
    ok, reden = stadsbeeld.mag(START)
    if not ok:
        r.append(f"NIET GELADEN: {reden}")
        _schrijf(r)
        return 0
    from playwright.sync_api import sync_playwright
    verzoeken, links = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(user_agent=stadsbeeld.AGENT)
        pg.on("request", lambda q: verzoeken.append(q.url))
        # DE LAGENBOOM. De tweede ronde, 18 oktober, liet zien dat de kaart
        # Historie haar lagen ophaalt via kaartviewerapi/bookmark/10/tree. Dat
        # antwoord haalt de pagina zelf op; hier wordt het alleen bewaard,
        # niet opnieuw opgevraagd.
        bomen = {}

        def bewaar(resp):
            if "/kaartviewerapi/bookmark/" in resp.url and \
                    resp.url.rstrip("/").endswith("/tree"):
                try:
                    bomen[resp.url] = resp.json()
                except Exception:
                    pass
        pg.on("response", bewaar)
        pg.goto(START, wait_until="networkidle", timeout=60000)
        links = pg.eval_on_selector_all(
            "a", "els => els.map(e => [e.innerText.trim(), e.href])")
        # Elke kaart in het menu met monument, erfgoed of cultuur in de naam
        # ook openen, want pas daar laadt de kaart haar lagen.
        doelen = [h for t, h in links
                  if re.search(r"monument|erfgoed|cultuur|histor", t + h, re.I)]
        teksten = {}
        for h in doelen[:5]:
            ok2, reden2 = stadsbeeld.mag(h)
            if not ok2:
                r.append(f"- niet geopend {h}: {reden2}")
                continue
            try:
                pg.goto(h, wait_until="networkidle", timeout=60000)
                pg.wait_for_timeout(5000)
                # De lagenlijst van de kaart: pas aangevinkte lagen worden
                # opgevraagd, dus de namen staan alleen in de pagina zelf.
                teksten[h] = pg.inner_text("body")[:6000]
            except Exception as e:
                r.append(f"- fout bij {h}: {type(e).__name__}")
        # DE PRESENTATIE VAN DE MONUMENTENLAGEN. De boom noemt per laag geen
        # dienst, alleen een ID; de app haalt bij het aanzetten van een laag
        # bookmark/10/bookmarkpresentation/<ID>/presentation op, en dat zag de
        # tweede ronde voor drie andere lagen. Hier hetzelfde verzoek voor de
        # lagen met monument of beschermd in de naam, met robots.txt eerst.
        presentaties = {}
        for url, boom in bomen.items():
            basis = url.rsplit("/tree", 1)[0]
            for knoop in _knopen(boom):
                if re.search(r"monument|beschermd", str(knoop.get("label")),
                             re.I) and not knoop.get("folder") \
                        and knoop.get("ID"):
                    purl = f"{basis}/bookmarkpresentation/{knoop['ID']}/" \
                           f"presentation"
                    ok3, reden3 = stadsbeeld.mag(purl)
                    if not ok3:
                        r.append(f"- niet opgehaald {purl}: {reden3}")
                        continue
                    try:
                        antw = pg.request.get(purl)
                        presentaties[knoop["label"]] = antw.json()
                    except Exception as e:
                        r.append(f"- fout bij {purl}: {type(e).__name__}")
        b.close()
    r.append("## Menu")
    r += [f"- {t[:80]} -> {h}" for t, h in links[:80]]
    r.append("")
    # ALLES BEHALVE ACHTERGRONDTEGELS. De eerste ronde, 18 oktober, filterde
    # op woorden als json en config, en zag alleen de gemeentegrens: de
    # configuratie van de kaart Historie kwam blijkbaar via een adres zonder
    # die woorden. Nu staat elk verzoek erin, behalve de tegels van de
    # achtergrondkaart, met de kaartlagen bovenaan.
    uniek = sorted(set(u for u in verzoeken if "openbasiskaart" not in u
                       and not re.search(r"\.(png|jpg|svg|woff2?|ttf|css)"
                                         r"(\?|$)", u)))
    r.append("## Opgevraagde adressen die op kaartlagen wijzen")
    r += [f"- {u[:300]}" for u in uniek if INTERESSANT.search(u)][:150]
    r.append("")
    r.append("## Alle andere opgevraagde adressen")
    r += [f"- {u[:300]}" for u in uniek if not INTERESSANT.search(u)][:150]
    r.append("")
    for h, t in teksten.items():
        r.append(f"## Tekst op {h}")
        r.append("```")
        r.append(t)
        r.append("```")
    lagen = []
    for url, boom in bomen.items():
        lagen += lagen_uit_boom(boom)
    with open(BOOM, "w", encoding="utf-8") as f:
        json.dump({"bron": list(bomen), "bomen": bomen,
                   "presentaties": presentaties}, f,
                  ensure_ascii=False, indent=1)
    r.append("## Presentaties van de monumentenlagen")
    for naam, pres in presentaties.items():
        tekst = json.dumps(pres, ensure_ascii=False)
        urls = sorted(set(re.findall(r"https?://[^\"\s]+", tekst)))
        lagen_p = sorted(set(re.findall(r'"(?:layers?|layerName|LAYERS|'
                                        r'name)"\s*:\s*"([^"]+)"', tekst)))
        r.append(f"- {naam}: adressen {urls[:10]}, laagnamen {lagen_p[:10]}")
        r.append(f"  - ruw: `{tekst[:1200]}`")
    r.append("")
    r.append("## Lagen in de lagenboom")
    raak = [l for l in lagen if re.search(r"monument|stadsbeeld|stadsgezicht"
                                          r"|erfgoed|beschermd",
                                          json.dumps(l, ensure_ascii=False),
                                          re.I)]
    if not lagen:
        lagen = [{"pad": "", "naam": k.get("label"), "ID": k.get("ID")}
                 for b in bomen.values() for k in _knopen(b)
                 if k.get("label") and not k.get("folder")]
    r.append(f"- {len(lagen)} lagen, waarvan {len(raak)} over monumenten of "
             f"bescherming:")
    r += [f"  - {json.dumps(l, ensure_ascii=False)[:400]}" for l in raak]
    _schrijf(r)
    return 0


BOOM = "kaartviewer_boom.json"


def _knopen(k):
    if isinstance(k, dict):
        yield k
        for v in k.values():
            yield from _knopen(v)
    elif isinstance(k, list):
        for v in k:
            yield from _knopen(v)


def lagen_uit_boom(knoop, pad=()):
    """Elke knoop met een naam en iets dat op een dienst of laagnaam lijkt,
    met het pad van mappen erboven. De vorm van de boom is niet
    gedocumenteerd, dus dit zoekt breed: elk dict met een titel of naam, en
    alle tekstvelden waarin geoservices, wms, wfs of layer voorkomt."""
    uit = []
    if isinstance(knoop, dict):
        naam = next((knoop[k] for k in ("title", "name", "naam", "label",
                                        "titel") if isinstance(knoop.get(k),
                                                               str)), None)
        dienst = {k: v for k, v in knoop.items() if isinstance(v, str) and
                  re.search(r"geoservices|wms|wfs|layer", k + v, re.I)}
        if naam and dienst:
            uit.append({"pad": " / ".join(pad), "naam": naam, **dienst})
        for v in knoop.values():
            uit += lagen_uit_boom(v, pad + ((naam,) if naam else ()))
    elif isinstance(knoop, list):
        for v in knoop:
            uit += lagen_uit_boom(v, pad)
    return uit


def _schrijf(r):
    with open(VERSLAG, "w", encoding="utf-8") as f:
        f.write("\n".join(r) + "\n")
    print("\n".join(r))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verken", action="store_true")
    a = ap.parse_args()
    if a.verken:
        return verken()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
