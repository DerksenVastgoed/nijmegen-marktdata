#!/usr/bin/env python3
"""
Hoogtes en oppervlakken per pand uit de 3D BAG, bewaard in de eigen repo.

Waarom in de repo: als de bron wegvalt of van opzet verandert, hebben we onze
eigen panden nog. Het landelijke bestand is ruim een gigabyte en past daar niet
in, maar onze paar duizend panden wel; dat is een bestand van enkele
megabytes.

Wat we eruit halen, en waarom het telt voor de bouwkosten:
- b3_opp_buitenmuur: het buitenmuuroppervlak in m2. Dit is de hele schil van
  het pand, dus inclusief de zijgevels die tegen de buren staan; die eraf halen
  is een volgende stap.
- b3_opp_dak_plat en b3_opp_dak_schuin: het dakoppervlak, gesplitst.
- b3_opp_grond: het grondvlak, nodig om het aantal bouwlagen te controleren.
- b3_bouwlagen: het geschatte aantal bouwlagen.
- b3_h_nok en b3_h_maaiveld: nokhoogte en maaiveld, allebei in NAP.
- b3_kwaliteitsindicator: zegt of de meting betrouwbaar is; zonder AHN-dekking
  kunnen de waarden leeg of onbruikbaar zijn.

Bron: 3D BAG, 3D Geoinformation Research Group TU Delft en 3DGI, op basis van
de BAG en het Actueel Hoogtebestand Nederland. Licentie CC BY 4.0, dus de bron
hoort vermeld te worden waar we de cijfers gebruiken.
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request

UIT_PAD = "bag3d.json"
API = "https://api.3dbag.nl/collections/pand/items"
PER_RONDE = int(os.environ.get("BAG3D_PER_RONDE") or 300)

VELDEN = ("b3_opp_buitenmuur", "b3_opp_dak_plat", "b3_opp_dak_schuin",
          "b3_opp_grond", "b3_bouwlagen", "b3_h_nok", "b3_h_maaiveld",
          "b3_dak_type", "b3_volume_lod13", "b3_kwaliteitsindicator",
          "identificatie", "bouwjaar")


def lees(pad=UIT_PAD):
    try:
        with open(pad, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"versie": "", "panden": {}, "bijgewerkt": ""}


def lees_samen(*paden):
    """
    Meerdere snapshots als één, voor een lezer die alle panden wil.

    Sinds 11 november staat de 3D BAG op twee plekken: deze openbare repo
    houdt de panden van de ring en van de adressen met een bekendmaking bij,
    en een lezer kan daarnaast een eigen bestand hebben voor panden die hij
    zelf kiest. Zo'n eigen selectie hoort niet in een openbaar bestand. De
    samenvoeger is dezelfde als die van git, dus een gemeten pand wint altijd
    van een lege poging.
    """
    uit = {"versie": "", "panden": {}, "bijgewerkt": ""}
    for pad in paden or (UIT_PAD,):
        uit = samenvoegen(uit, lees(pad))
    return uit


PREFIX = "NL.IMBAG.Pand."


def volledig_id(pand_id):
    """
    Het pand-id zoals de 3D BAG het verwacht.

    Wij bewaren het kale nummer uit de BAG, zoals 0268100000001130. De 3D BAG
    wil er NL.IMBAG.Pand. voor; zonder dat voorvoegsel antwoordt de bron met
    een 502 op elk verzoek, en dat is geen fout die zichzelf verklaart.
    """
    pand_id = (pand_id or "").strip()
    return pand_id if pand_id.startswith(PREFIX) else PREFIX + pand_id


def _haal(pand_id):
    """De 3D BAG-gegevens van een pand, of None als er niets is."""
    url = f"{API}/{volledig_id(pand_id)}"
    verzoek = urllib.request.Request(
        url, headers={"Accept": "application/json",
                      "User-Agent": "NijmegenVastgoedMonitor/1.0"})
    try:
        with urllib.request.urlopen(verzoek, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _velden_uit(antwoord):
    """
    De velden die we willen, waar ze ook zitten.

    De API geeft een GeoJSON-feature terug; bij een pand met meerdere delen
    zitten de kenmerken soms een laag dieper. Daarom hier zoeken in plaats van
    een vaste plek aannemen: een verandering in de opzet van de bron mag geen
    lege waarden opleveren zonder dat iemand het merkt.
    """
    kandidaten = []
    if isinstance(antwoord, dict):
        kandidaten.append(antwoord.get("properties") or {})
        kandidaten.append(antwoord)
        for deel in (antwoord.get("features") or []):
            if isinstance(deel, dict):
                kandidaten.append(deel.get("properties") or {})
        # De 3D BAG antwoordt in CityJSON: de kenmerken zitten onder
        # feature.CityObjects.<id>.attributes, niet in properties.
        for blok in (antwoord.get("feature"), antwoord):
            if not isinstance(blok, dict):
                continue
            for obj in (blok.get("CityObjects") or {}).values():
                if isinstance(obj, dict):
                    kandidaten.append(obj.get("attributes") or {})
    uit = {}
    for bron in kandidaten:
        if not isinstance(bron, dict):
            continue
        for veld in VELDEN:
            if veld in bron and bron[veld] is not None and veld not in uit:
                uit[veld] = bron[veld]
    return uit


MAX_POGINGEN = 3


def te_doen(opgeslagen, pand_ids, versie_nu):
    """
    Welke panden opgehaald moeten worden.

    Bij een nieuwe versie van de bron opnieuw alles, want dan is de
    hoogtemeting vernieuwd. Anders alleen wat we nog niet hebben.
    """
    if versie_nu and opgeslagen.get("versie") and versie_nu != opgeslagen["versie"]:
        return list(pand_ids), True
    panden = opgeslagen.get("panden", {})

    def nog_doen(pand_id):
        """
        Moet dit pand nog opgehaald worden?

        Klaar is het pas als er gegevens zijn, of als de bron er na drie
        pogingen niets over geeft. Een pand met een mislukte poging staat wel in
        het bestand maar is niet klaar; keek je alleen of het bekend was, dan
        kreeg het nooit een tweede kans. Zonder de rem van drie pogingen kwamen
        dezelfde panden juist elke run terug.
        """
        p = panden.get(pand_id)
        if p is None:
            return True
        if p.get("b3_opp_buitenmuur") or p.get("leeg"):
            return False
        return int(p.get("pogingen") or 0) < MAX_POGINGEN

    return [p for p in pand_ids if nog_doen(p)], False


def pand_ids_uit_geschiedenis(pad="pandgeschiedenis.json"):
    # Opmerking: deze functie leest alleen pand_id per adres, en dat veld blijft
    # in de compacte vorm gewoon bij het adres staan. Uitvouwen is hier dus niet
    # nodig.
    """De pand-ids die we al kennen uit de geschiedenis per pand."""
    try:
        with open(pad, encoding="utf-8") as f:
            g = json.load(f)
    except Exception:
        return []
    ids = []
    for pand in g.values():
        pid = pand.get("pand_id")
        if pid and pid not in ids:
            ids.append(pid)
    return ids


HERKOMST_OPENBAAR = ("focusbuurt", "bekendmaking")


def pand_ids_uit_voorraad(pad="voorraad.json"):
    """
    De pand-ids van de woningen in de ringbuurten (ring.py) en van de
    adressen met een bekendmaking.

    Die tweede groep kwam tot 11 november uit pandgeschiedenis.json van de
    brief. Sinds de splitsing staan ze met herkomst "bekendmaking" in
    voorraad.json, uit het openbare archief, en dus horen ze hier.
    """
    try:
        with open(pad, encoding="utf-8") as f:
            v = json.load(f)
    except Exception:
        return []
    uit = []
    for r in (v.get("adressen") or {}).values():
        if r.get("herkomst") not in HERKOMST_OPENBAAR:
            continue
        for pid in (r.get("panden") or [r.get("pand")]):
            if pid and pid not in uit:
                uit.append(pid)
    return uit


def _rang(p):
    """
    Hoe ver een pand is: gegevens boven opgegeven boven een mislukte poging.

    Gebruikt bij het samenvoegen. Een pand met gegevens wint altijd, want een
    meting gaat niet verloren door een latere fout; daarna telt wie het vaakst
    geprobeerd heeft, zodat de teller van drie pogingen doorloopt.
    """
    p = p or {}
    if p.get("b3_opp_buitenmuur"):
        return (2, p.get("opgehaald") or "")
    if p.get("leeg"):
        return (1, str(p.get("pogingen") or 0))
    return (0, str(p.get("pogingen") or 0))


def samenvoegen(a, b):
    """
    Twee versies van bag3d.json samen, zonder dat er een pand wegvalt.

    WAAROM. Twee workflows schrijven dit bestand: de brief haalt elke dag 300
    panden op, de inhaalslag duizenden. Botsen ze bij het terugcommitten, dan
    zette de brief tot 15 oktober "de versie van deze run" neer. Begon de
    brief om 3:17 en de inhaalslag later, dan wiste de brief zo alles wat de
    inhaalslag intussen had opgehaald. Er komen alleen panden bij en er gaan
    er nooit af, dus de vereniging is altijd juist.

    Git roept dit aan als samenvoeger (zie .gitattributes), dus bij elke
    rebase of merge van dit bestand, in welke workflow ook.
    """
    uit = dict(a)
    panden = dict(a.get("panden") or {})
    for pid, pb in (b.get("panden") or {}).items():
        if pid not in panden or _rang(pb) > _rang(panden[pid]):
            panden[pid] = pb
    uit["panden"] = panden
    mislukt = dict(a.get("mislukt") or {})
    for pid, n in (b.get("mislukt") or {}).items():
        mislukt[pid] = max(int(n or 0), int(mislukt.get(pid) or 0))
    uit["mislukt"] = {pid: n for pid, n in mislukt.items()
                      if not (panden.get(pid) or {}).get("b3_opp_buitenmuur")}
    uit["bijgewerkt"] = max(a.get("bijgewerkt") or "", b.get("bijgewerkt") or "")
    uit["bron"] = a.get("bron") or b.get("bron") or ""
    uit["versie"] = a.get("versie") or b.get("versie") or ""
    return uit


def proef():
    """Het samenvoegen op vaste gevallen, zonder netwerk."""
    afw = []
    a = {"panden": {"p1": {"b3_opp_buitenmuur": 10, "opgehaald": "2026-10-01"},
                    "p2": {"pogingen": 1}},
         "mislukt": {"p2": 1}, "bijgewerkt": "2026-10-14"}
    b = {"panden": {"p2": {"b3_opp_buitenmuur": 20, "opgehaald": "2026-10-15"},
                    "p3": {"leeg": True}, "p1": {"leeg": True}},
         "mislukt": {"p4": 2}, "bijgewerkt": "2026-10-15"}
    s = samenvoegen(a, b)
    if set(s["panden"]) != {"p1", "p2", "p3"}:
        afw.append(f"bij het samenvoegen valt een pand weg: {sorted(s['panden'])}")
    if not s["panden"]["p1"].get("b3_opp_buitenmuur"):
        afw.append("een gemeten pand wordt overschreven door een lege poging")
    if not s["panden"]["p2"].get("b3_opp_buitenmuur"):
        afw.append("een gemeten pand van de andere kant gaat verloren")
    if "p2" in s["mislukt"] or s["mislukt"].get("p4") != 2:
        afw.append(f"de pogingenteller klopt niet na samenvoegen: {s['mislukt']}")
    if s["bijgewerkt"] != "2026-10-15":
        afw.append("de datum van de nieuwste kant gaat verloren")
    if samenvoegen(b, a)["panden"] != s["panden"]:
        afw.append("samenvoegen hangt af van de volgorde")
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        pa, pb = os.path.join(t, "a.json"), os.path.join(t, "b.json")
        with open(pa, "w") as f:
            json.dump(a, f)
        with open(pb, "w") as f:
            json.dump(b, f)
        if set(lees_samen(pa, pb)["panden"]) != {"p1", "p2", "p3"}:
            afw.append("lees_samen mist een pand uit een van de twee bestanden")
        if set(lees_samen(pa, os.path.join(t, "weg.json"))["panden"]) != {"p1", "p2"}:
            afw.append("lees_samen valt om op een bestand dat er niet is")
    for r in afw:
        print("AFWIJKING: " + r, file=sys.stderr)
    print(f"Proef 3D BAG: {len(afw)} afwijkingen", file=sys.stderr)
    return 1 if afw else 0


def _als_samenvoeger(basis, ons, hun):
    """Aangeroepen door git: schrijft de vereniging naar ons, de %A."""
    try:
        a, b = lees(ons), lees(hun)
        if not a.get("panden") and not b.get("panden"):
            return 1
        with open(ons, "w", encoding="utf-8") as f:
            json.dump(samenvoegen(a, b), f, ensure_ascii=False, indent=1)
        return 0
    except Exception as e:
        print(f"3D BAG samenvoegen mislukt: {e}", file=sys.stderr)
        return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uit", default=UIT_PAD)
    ap.add_argument("--per-ronde", type=int, default=PER_RONDE)
    ap.add_argument("--versie", default="",
                    help="versie van de bron; bij een andere waarde wordt alles "
                         "opnieuw opgehaald")
    ap.add_argument("--minuten", type=float, default=0,
                    help="stop na zoveel minuten; 0 is geen tijdgrens")
    ap.add_argument("--proef", action="store_true")
    ap.add_argument("--wachtrij", action="store_true",
                    help="alleen tellen hoeveel panden nog op te halen zijn, "
                         "zonder iets op te halen")
    ap.add_argument("--samenvoegen", nargs=3, metavar=("BASIS", "ONS", "HUN"),
                    help="samenvoeger voor git; zie .gitattributes")
    ap.add_argument("--bron", choices=("voorraad", "geschiedenis"),
                    default="voorraad",
                    help="welke panden: voorraad (ring en bekendmakingen, de "
                         "openbare set) of geschiedenis (pandgeschiedenis.json "
                         "van een lezer)")
    ap.add_argument("--al-bekend", default="",
                    help="panden die in dit bestand al staan, sla je over; zo "
                         "haalt een lezer met een eigen bestand niets dubbel op")
    ap.add_argument("--rest", default="",
                    help="schrijf het aantal panden dat nog te gaan is naar "
                         "dit bestand, voor de vervolgronde")
    args = ap.parse_args()
    if args.proef:
        return proef()
    if args.samenvoegen:
        return _als_samenvoeger(*args.samenvoegen)

    opgeslagen = lees(args.uit)
    # TOT 11 NOVEMBER NAM DIT BEIDE: de geschiedenis van de brief en de hele
    # ring. In deze openbare repo is dat alleen de voorraad (ring en adressen
    # met een bekendmaking); de brief draait deze module voor zijn eigen
    # panden met --bron geschiedenis en schrijft die naar zijn eigen bestand.
    ids = (pand_ids_uit_voorraad() if args.bron == "voorraad"
           else pand_ids_uit_geschiedenis())
    if args.al_bekend:
        al = set((lees(args.al_bekend).get("panden") or {}))
        ids = [p for p in ids if p not in al]
    if not ids:
        print(f"Geen pand-ids bekend uit {args.bron}", file=sys.stderr)
        return 0

    # Eerdere mislukkingen meenemen als poging, zodat de teller doorloopt.
    for pand_id, pogingen in (opgeslagen.get("mislukt") or {}).items():
        opgeslagen.setdefault("panden", {}).setdefault(
            pand_id, {"pogingen": pogingen}) if pogingen >= MAX_POGINGEN else None
    wachtrij, opnieuw = te_doen(opgeslagen, ids, args.versie)
    if args.wachtrij:
        print(len(wachtrij))
        return 0
    if opnieuw:
        print(f"Nieuwe versie van de bron ({args.versie}); alles opnieuw",
              file=sys.stderr)
    if not wachtrij:
        print(f"3D BAG bij: {len(opgeslagen.get('panden', {}))} panden",
              file=sys.stderr)
        if args.rest:
            with open(args.rest, "w", encoding="utf-8") as f:
                json.dump({"rest": 0}, f)
        return 0

    gedaan, leeg, fout = 0, 0, 0
    begin = time.monotonic()
    bekeken = 0
    for pand_id in wachtrij[:args.per_ronde]:
        if args.minuten and time.monotonic() - begin > args.minuten * 60:
            print(f"Tijdgrens van {args.minuten:g} minuten bereikt",
                  file=sys.stderr)
            break
        bekeken += 1
        try:
            antwoord = _haal(pand_id)
        except Exception as e:
            fout += 1
            # De poging onthouden, zodat dit pand niet eeuwig terugkomt.
            eerder = opgeslagen.setdefault("panden", {}).get(pand_id) or {}
            pogingen = int(eerder.get("pogingen") or 0) + 1
            if pogingen >= MAX_POGINGEN:
                opgeslagen["panden"][pand_id] = {
                    "pogingen": pogingen, "leeg": True,
                    "reden": str(e)[:60],
                    "opgegeven": dt.date.today().isoformat()}
            else:
                opgeslagen.setdefault("mislukt", {})[pand_id] = pogingen
            if fout <= 3:
                print(f"  {pand_id}: {str(e)[:90]}", file=sys.stderr)
            if fout > 20:
                print("Te veel fouten; de bron lijkt onbereikbaar of veranderd",
                      file=sys.stderr)
                break
            continue
        velden = _velden_uit(antwoord) if antwoord else {}
        if not velden:
            leeg += 1
            opgeslagen.setdefault("panden", {})[pand_id] = {"leeg": True}
            continue
        velden["opgehaald"] = dt.date.today().isoformat()
        opgeslagen.setdefault("panden", {})[pand_id] = velden
        gedaan += 1

    if args.versie:
        opgeslagen["versie"] = args.versie
    opgeslagen["bijgewerkt"] = dt.date.today().isoformat()
    opgeslagen["bron"] = ("3D BAG, TU Delft en 3DGI, op basis van de BAG en het "
                          "AHN; CC BY 4.0")
    with open(args.uit, "w", encoding="utf-8") as f:
        json.dump(opgeslagen, f, ensure_ascii=False, indent=1)

    rest = max(0, len(wachtrij) - bekeken)
    duur = time.monotonic() - begin
    if args.rest:
        with open(args.rest, "w", encoding="utf-8") as f:
            json.dump({"rest": rest, "bekeken": bekeken, "opgehaald": gedaan,
                       "fouten": fout, "seconden": round(duur, 1)}, f)
    opgegeven = sum(1 for p in (opgeslagen.get("panden") or {}).values()
                    if int(p.get("pogingen") or 0) >= MAX_POGINGEN)
    print(f"3D BAG: {gedaan} panden opgehaald, {leeg} zonder gegevens, "
          f"{fout} fouten in {duur:.0f} seconden, nog {rest} te gaan "
          f"(totaal {len(opgeslagen.get('panden', {}))}"
          + (f", {opgegeven} na drie pogingen opgegeven" if opgegeven else "")
          + ")", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
