#!/usr/bin/env python3
"""
De officiële bekendmakingen van Nijmegen ophalen uit de SRU van overheid.nl.

WAAROM EEN EIGEN MODULE. Tot 11 november stond deze aanroep twee keer in de
vastgoedbrief: in bekendmakingen_nijmegen.py (dagelijks) en in
bekendmakingen_archief.py (het archief). De twee kopieën waren al uiteen
gelopen: de ene zocht de link in preferredUrl en itemUrl, de andere in itemUrl
en identifier, en alleen de archiefkopie wachtte bij een 503. Hier staat hij
één keer, met het beste van beide.

Bron: https://repository.overheid.nl/sru, open, geen sleutel. Deze module haalt
alles van de gemeente Nijmegen op, zonder filter op straat of buurt: welke
bekendmakingen interessant zijn, beslist de lezer en niet deze openbare repo.
"""
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET

SRU_URL = "https://repository.overheid.nl/sru"
GEMEENTE = "Nijmegen"
MAX_PER_PAGINA = 100
# Boven 4.000 records geeft de SRU niets meer terug; een langere periode moet
# in blokken (zie bekendmakingen_archief.maanden()).
MAX_RECORDS = 4000


def bouw_cql(vanaf, tot=None, gemeente=GEMEENTE):
    delen = ["c.product-area==officielepublicaties",
             "w.organisatietype==gemeente",
             f'dt.creator=="{gemeente}"',
             f'dt.date>="{vanaf}"']
    if tot:
        delen.append(f'dt.date<="{tot}"')
    return " and ".join(delen)


def lokaal(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def eerste_tekst(element, naam):
    for el in element.iter():
        if lokaal(el.tag) == naam and el.text:
            return el.text.strip()
    return None


def url_uit_record(record):
    """De link naar de publicatie: preferredUrl, itemUrl, identifier, attribuut."""
    for namen in (("preferredUrl", "itemUrl"), ("identifier",)):
        for el in record.iter():
            if (lokaal(el.tag) in namen and el.text
                    and el.text.strip().startswith("http")):
                return el.text.strip()
    for el in record.iter():
        for waarde in el.attrib.values():
            if isinstance(waarde, str) and waarde.startswith("http"):
                return waarde
    return ""


def parse_record(record):
    return {
        "titel": eerste_tekst(record, "title") or "(geen titel)",
        "datum": eerste_tekst(record, "date") or eerste_tekst(record, "available") or "",
        "type": eerste_tekst(record, "type") or "",
        "url": url_uit_record(record),
    }


def haal(cql, pauze=1.0, pogingen=4, stil=False, haler=None):
    """
    Alle records voor deze zoekvraag, als XML-elementen.

    Bij een fout of een 503 wacht hij steeds langer (20, 40, 60 seconden): de
    SRU geeft 503 als je te snel vraagt, en is soms even weg. Lukt een pagina
    na alle pogingen niet, dan GOOIT hij een fout in plaats van een halve
    lijst terug te geven. Een halve lijst ziet eruit als een rustige dag.
    """
    import requests
    haler = haler or (lambda url: requests.get(url, timeout=(20, 90)))
    records, start = [], 1
    while True:
        params = {"version": "2.0", "operation": "searchRetrieve", "query": cql,
                  "maximumRecords": MAX_PER_PAGINA, "startRecord": start}
        url = SRU_URL + "?" + urllib.parse.urlencode(
            params, quote_via=urllib.parse.quote)
        root = None
        for poging in range(1, pogingen + 1):
            try:
                resp = haler(url)
                if resp.status_code == 503:
                    raise RuntimeError("503 Service Unavailable")
                resp.raise_for_status()
                root = ET.fromstring(resp.content)
                break
            except Exception as e:
                if poging == pogingen:
                    raise RuntimeError(f"SRU vanaf record {start}: {e}") from e
                wacht = poging * 20 if pauze else 0
                if not stil:
                    print(f"  SRU record {start}: poging {poging} mislukt "
                          f"({e}), opnieuw over {wacht}s", file=sys.stderr)
                time.sleep(wacht)
        pagina = [el for el in root.iter() if lokaal(el.tag) == "record"]
        if not pagina:
            break
        records.extend(pagina)
        totaal = eerste_tekst(root, "numberOfRecords")
        totaal = int(totaal) if totaal and totaal.isdigit() else len(records)
        start += MAX_PER_PAGINA
        if start > totaal or start > MAX_RECORDS:
            break
        time.sleep(pauze)
    return records


VOORBEELD = b"""<?xml version="1.0"?>
<searchRetrieveResponse xmlns="http://docs.oasis-open.org/ns/search-ws/sruResponse">
 <numberOfRecords>2</numberOfRecords>
 <records>
  <record><recordData><gzd xmlns:dcterms="http://purl.org/dc/terms/">
   <dcterms:title>Melding brandveilig gebruik kamerverhuurpand, aan Ackerbroekweg 31, 6546HX Nijmegen</dcterms:title>
   <dcterms:date>2026-08-10</dcterms:date><dcterms:type>gemeenteblad</dcterms:type>
   <preferredUrl>https://repository.overheid.nl/frbr/officielepublicaties/gmb/2026/gmb-2026-380227/1/html/gmb-2026-380227.html</preferredUrl>
  </gzd></recordData></record>
  <record><recordData><gzd xmlns:dcterms="http://purl.org/dc/terms/">
   <dcterms:title>Verordening zonder link</dcterms:title>
   <dcterms:available>2026-08-11</dcterms:available>
   <identifier>https://zoek.officielebekendmakingen.nl/gmb-2026-1</identifier>
  </gzd></recordData></record>
 </records>
</searchRetrieveResponse>"""


def proef():
    """Zonder netwerk: de vorm van een antwoord, de link, en dat een fout een fout blijft."""
    fouten = []

    def check(naam, echt, wil):
        if echt != wil:
            fouten.append(f"{naam}: {echt!r}, verwacht {wil!r}")

    class Antw:
        def __init__(self, code, inhoud=b""):
            self.status_code, self.content = code, inhoud

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(str(self.status_code))

    recs = haal("x", pauze=0, stil=True, haler=lambda u: Antw(200, VOORBEELD))
    check("twee records", len(recs), 2)
    a, b = [parse_record(r) for r in recs]
    check("titel", a["titel"][:24], "Melding brandveilig gebr")
    check("datum", a["datum"], "2026-08-10")
    check("link uit preferredUrl", a["url"].endswith("gmb-2026-380227.html"), True)
    check("datum uit available", b["datum"], "2026-08-11")
    check("link uit identifier", b["url"], "https://zoek.officielebekendmakingen.nl/gmb-2026-1")
    check("cql met einddatum", bouw_cql("2026-01-01", "2026-01-31").endswith(
        'dt.date<="2026-01-31"'), True)
    check("cql zonder einddatum", "dt.date<=" in bouw_cql("2026-01-01"), False)

    # EEN MISLUKTE PAGINA IS EEN FOUT, GEEN LEGE DAG. Breek dit door hierboven
    # "raise" door "break" te vervangen, en deze controle wordt rood.
    tel = {"n": 0}

    def altijd_503(u):
        tel["n"] += 1
        return Antw(503)
    try:
        haal("x", pauze=0, pogingen=3, stil=True, haler=altijd_503)
        fouten.append("een SRU die alleen 503 geeft levert geen fout op")
    except RuntimeError:
        pass
    check("drie pogingen bij 503", tel["n"], 3)

    for f in fouten:
        print(f"FOUT {f}", file=sys.stderr)
    print(f"Proef sru: {len(fouten)} fouten. Gedekt: de vorm van een antwoord, "
          f"de link op twee plekken, de datum op twee plekken, de zoekvraag, en "
          f"dat een SRU die niet antwoordt een fout geeft en geen lege lijst.",
          file=sys.stderr)
    return 1 if fouten else 0


if __name__ == "__main__":
    sys.exit(proef() if "--proef" in sys.argv else 0)
