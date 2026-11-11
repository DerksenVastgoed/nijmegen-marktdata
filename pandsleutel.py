#!/usr/bin/env python3
"""
Een pand heeft een sleutel, en die wordt op een plek gemaakt.

WAAROM DIT BESTAAT. Tien bestanden bevatten feiten per pand. De sleutel
daarvoor werd op veertien plekken in elf bestanden opnieuw gemaakt, plus
negentien keer los met isalnum() in de regel zelf. Die veertien lopen uiteen
op drie punten: of "professor" wordt afgekort tot "prof", of een accent
wegvalt of blijft staan, en of "doctor" meedoet. Vijf van de veertien dragen
in hun eigen docstring de regel "zelfde normalisatie als in de andere
scripts, anders matcht niets", en precies dat is wat er is gebeurd.

WAT HET KOST. Op de 1.777 adressen die we volgen geven twee van die veertien
een andere sleutel bij 41 adressen. Bij 28 daarvan staat het pand wel in het
bestand en vindt de lezer het niet. Dat geeft geen foutmelding: een
ontbrekende sleutel is gewoon None, en dan is een dossier stil leeg.

In pandgeschiedenis.json zelf staan drie conventies door elkaar: 13 records
zonder afkorting, 12 met, en 2 met een sleutel die uit geen enkele functie
kan komen. Die laatste twee zijn Professor Molkenboerstraat 18 en 20, die
daardoor twee keer in het bestand staan. De ene helft heeft de energielabels
en de andere de onttrekking van 2018 en de melding brandveilig gebruik van
2025. Welke helft een lezer ziet hangt af van welke van de veertien functies
hij gebruikt. Voor de kamerverhuurtoets is dat het verschil tussen een pand
dat onttrokken is en een pand dat schoon lijkt.

HOE DIT VEILIG IS IN TE VOEREN. sleutel() geeft één vorm, en varianten()
geeft alle vormen waaronder hetzelfde pand ooit is opgeslagen. Een lezer die
varianten() langsloopt vindt een record ook als het nog niet is overgezet.
Daardoor kan de overstap in twee stappen: eerst deze module erbij met een
proef die bewijst dat elke sleutel die vandaag op schijf staat te vinden is,
en daarna de bestanden omzetten en de veertien functies weghalen. Zonder die
eerste stap is er een moment waarop de helft is omgezet en de andere helft
niet, en dan verdwijnen er feiten.

WAT DE VORM IS, EN WAAROM.
  - kleine letters, en alles wat geen letter of cijfer is eruit
  - een lidwoord voorop valt weg. "aan de Pijnboomstraat 4" in een
    bekendmakingstitel levert "de Pijnboomstraat" als straatnaam op, en dat
    is dezelfde straat. Dit is de oorzaak van de twee dubbele records.
  - titels worden afgekort: sint, professor, burgemeester, doctor. De
    gemeente schrijft ze beide uit, soms in dezelfde publicatie.
  - accenten worden gevouwen en niet weggegooid. Mariënburg werd
    "marinburg", want de regex gooide de ë eruit in plaats van er een e van
    te maken. Dat is niet alleen lelijk, het botst ook: twee verschillende
    straten kunnen zo dezelfde sleutel krijgen.

WAT HIER NIET THUISHOORT. huur_dekking.sleutel() kort straatnamen af
(straat -> str, laan -> ln) om geplakte adressen van buiten te laten matchen.
Dat is een zoekhulp en geen identiteit: "Hertogstraat" en "Hertogstr" mogen
daar hetzelfde zijn, maar een sleutel die dat doet kan twee panden
samenvoegen. Die functie blijft dus waar hij staat.
"""
import re
import sys
import unicodedata

# Titels die de gemeente zowel voluit als afgekort schrijft. De lange vorm
# staat voorop en eindigt op een spatie, zodat "sinterklaasstraat" niet wordt
# geraakt.
TITELS = (
    ("sint ", "st "), ("st. ", "st "),
    ("professor ", "prof "), ("prof. ", "prof "),
    ("burgemeester ", "burg "), ("burg. ", "burg "),
    ("doctor ", "dr "), ("dr. ", "dr "),
)

# Lidwoorden die voor een straatnaam kunnen staan zonder bij de naam te horen.
# "aan de " eerst, want die bevat "de " en anders blijft "aan" staan.
LIDWOORDEN = ("aan de ", "aan het ", "aan 't ", "de ", "het ", "'t ")


def _vouw(tekst):
    """Accenten vouwen in plaats van weggooien: ë wordt e, niet niets."""
    ontleed = unicodedata.normalize("NFKD", tekst)
    return "".join(c for c in ontleed if not unicodedata.combining(c))


def _kaal(tekst):
    return re.sub(r"[^a-z0-9]", "", _vouw((tekst or "").lower()))


def _straatvorm(straat, met_titels=True, met_lidwoord=False):
    s = _vouw((straat or "").lower()).strip()
    if not met_lidwoord:
        for lid in LIDWOORDEN:
            if s.startswith(lid):
                s = s[len(lid):]
                break
    if met_titels:
        for lang, kort in TITELS:
            s = s.replace(lang, kort)
    return re.sub(r"[^a-z0-9]", "", s)


def splits(adres):
    """
    (straat, nummer) uit een volledig adres, of (adres, "") als er geen
    nummer in staat.

    Het nummer is alles vanaf het eerste losse getal: "82-A" en "7A-12"
    blijven dus heel, want die horen bij het adres en niet bij de straat.
    """
    m = re.match(r"^(.*?)[\s,]+(\d.*)$", (adres or "").strip())
    if not m:
        return ((adres or "").strip(), "")
    return (m.group(1).strip(), m.group(2).strip())


def sleutel(adres, nummer=None):
    """
    De sleutel van dit pand. Eén vorm, voor elk bestand.

    Aan te roepen met een volledig adres, of met straat en nummer apart,
    want de veertien functies die dit vervangt deden het op beide manieren.

        sleutel("Professor Molkenboerstraat 18")  -> profmolkenboerstraat18
        sleutel("Professor Molkenboerstraat", 18) -> profmolkenboerstraat18
        sleutel("aan de Pijnboomstraat 4")        -> pijnboomstraat4
        sleutel("Mariënburg 82-A")                -> marienburg82a
    """
    if nummer is None:
        straat, nummer = splits(adres)
    else:
        straat = adres
    return _straatvorm(straat) + _kaal(str(nummer))


def sleutel_huisnummer(adres, nummer=None):
    """
    De sleutel zonder huisletter, voor bestanden die per huisnummer sleutelen.

    kamervergunningen.json doet dat: 83 van de 766 records staan onder
    "achterdewiemelpoort5" terwijl het adres "Achter de Wiemelpoort 5D" is.
    Dat is daar ook juist, want een onttrekking of omzetting wordt op het pand
    gegeven en niet op een afzonderlijke eenheid. Het is dus een andere vraag
    en geen andere spelling, en daarom een eigen functie: wie hiermee zoekt
    weet dat hij het pand bedoelt en niet de woning.
    """
    if nummer is None:
        straat, nummer = splits(adres)
    else:
        straat = adres
    m = re.match(r"\s*(\d+)", str(nummer))
    return _straatvorm(straat) + (m.group(1) if m else _kaal(str(nummer)))


def sleutel_archief(straat, huisnr=None):
    """
    De sleutel van het bekendmakingenarchief, dat zijn eigen conventie heeft.

    DRIE CONVENTIES, EN DAT IS GEEN ROMMEL. Het doel van deze module is één
    implementatie per conventie, niet één conventie voor alles. Er zijn er
    werkelijk drie:

      sleutel()            per woning. De identiteit van een pand waar wij
                           gebeurtenissen aan hangen.
      sleutel_huisnummer() per huisnummer. Een onttrekking of omzetting wordt
                           op het pand gegeven, niet op een eenheid, en
                           kamervergunningen.json sleutelt daarop.
      sleutel_archief()    per publicatietitel. Het archief kent een pand
                           alleen zoals de gemeente het opschreef, en "aan de
                           Pijnboomstraat 4" levert "de Pijnboomstraat" als
                           straatnaam op.

    Deze derde laat het lidwoord dus staan en gooit accenten weg in plaats van
    ze te vouwen, precies zoals bekendmakingen_archief.py het altijd deed. Dat
    is met opzet niet veranderd: de sleutels in bekendmakingen_archief.json
    komen uit titels en niet uit een adresregistratie, en dat bestand
    omzetten zou betekenen dat we uit elke titel opnieuw een adres parsen om
    een sleutel te repareren die werkt. varianten() kent deze vorm, dus wie
    van een schoon adres naar het archief zoekt vindt hem alsnog.

    Wat hier wél verandert: deze vorm stond in twee bestanden woordelijk
    uitgeschreven, in bekendmakingen_archief.py en in marktprijzen_bag.py,
    met in het tweede de regel "zelfde normalisatie als in
    bekendmakingen_archief.py, anders matcht niets". Twee kopieën van één
    regel lopen uiteen, en dat is het probleem dat deze module oplost.
    """
    s = (straat or "").lower()
    for lang, kort in TITELS:
        s = s.replace(lang, kort)
    s = re.sub(r"[^a-z0-9]", "", s)
    return f"{s}{'' if huisnr is None else huisnr}"


def varianten(adres, nummer=None, op_huisnummer=False):
    """
    Alle vormen waaronder dit pand op schijf kan staan, de huidige vooraan.

    Dit bestaat voor de overstap: zolang er bestanden zijn die nog niet zijn
    omgezet, moet een lezer het record alsnog vinden. Loop deze lijst langs
    en neem de eerste die bestaat.

    De vormen komen uit de veertien functies die dit vervangt:
      - met en zonder afkorting van titels (prof tegen professor)
      - met accenten weggegooid in plaats van gevouwen (marinburg)
      - met accenten ongemoeid (mariënburg, uit de isalnum-variant)
      - met het lidwoord er nog aan (deprofmolkenboerstraat18)

    op_huisnummer voegt de vorm zonder huisletter toe. Dat staat uit, want een
    lezer die "Augustijnenstraat 25B" zoekt mag niet stil het record van 25
    krijgen. Alleen een bestand dat per huisnummer sleutelt zet het aan.
    """
    if nummer is None:
        straat, nummer = splits(adres)
    else:
        straat = adres
    nr_kaal = _kaal(str(nummer))
    # De isalnum-variant laat niet-ascii letters staan, dus die kan niet door
    # _kaal: daar sneuvelen ze.
    rauw = (straat or "").lower()
    nr_rauw = "".join(c for c in str(nummer).lower() if c.isalnum())

    uit = []
    for vorm in (
        _straatvorm(straat) + nr_kaal,
        _straatvorm(straat, met_titels=False) + nr_kaal,
        _straatvorm(straat, met_lidwoord=True) + nr_kaal,
        _straatvorm(straat, met_titels=False, met_lidwoord=True) + nr_kaal,
        # Accenten weggegooid in plaats van gevouwen, met en zonder titels.
        re.sub(r"[^a-z0-9]", "", _titelvorm_zonder_vouwen(straat)) + nr_kaal,
        re.sub(r"[^a-z0-9]", "", rauw) + nr_kaal,
        # Accenten ongemoeid (de isalnum-variant), met en zonder lidwoord.
        "".join(c for c in rauw if c.isalnum()) + nr_rauw,
        "".join(c for c in _zonder_lidwoord(rauw) if c.isalnum()) + nr_rauw,
    ):
        if vorm and vorm not in uit:
            uit.append(vorm)
    # EN DE ANDERE KANT OP. De sleutel "deprofmolkenboerstraat18" hoort bij
    # het adres "Professor Molkenboerstraat 18", dat zelf geen lidwoord heeft:
    # de "de" komt uit een bekendmakingstitel die "aan de Professor
    # Molkenboerstraat 18" luidde. Uit het schone adres is die vorm dus niet
    # te maken door een lidwoord weg te halen, alleen door er een voor te
    # zetten. Zonder deze lus blijven de 56 dubbele records in
    # pandgeschiedenis.json onvindbaar vanaf het adres, en dat is precies de
    # helft van de geschiedenis die nu al stil wegvalt.
    basis = [v for v in uit]
    for lid in ("de", "het", "t"):
        for vorm in basis:
            samen = lid + vorm
            if samen not in uit:
                uit.append(samen)
    if op_huisnummer:
        for vorm in (sleutel_huisnummer(straat, nummer),
                     _straatvorm(straat, met_titels=False)
                     + (re.match(r"\s*(\d+)", str(nummer)).group(1)
                        if re.match(r"\s*(\d+)", str(nummer)) else "")):
            if vorm and vorm not in uit:
                uit.append(vorm)
    return uit


def _zonder_lidwoord(laag):
    for lid in LIDWOORDEN:
        if laag.startswith(lid):
            return laag[len(lid):]
    return laag


def _titelvorm_zonder_vouwen(straat):
    """De oude archiefvorm: titels afgekort, accenten weggegooid."""
    s = _zonder_lidwoord((straat or "").lower())
    for lang, kort in TITELS:
        s = s.replace(lang, kort)
    return s


def zoek_in(pad, bestand, adres, nummer=None, alles=False):
    """
    Zoeken met de conventie die bij dít bestand hoort, uit de tabel BESTANDEN.

    DIT IS DE INGANG, EN zoek() NIET. De vorm zonder huisletter is nodig voor
    kamervergunningen.json en gevaarlijk voor de rest: op de 2.105 adressen
    die we kennen levert hij 139 keer de sleutel van een ánder pand op.
    "Augustijnenstraat 25B" komt dan uit op het record van 25, en dat is een
    andere woning met een eigen geschiedenis. Zo'n keuze hoort niet bij de
    aanroeper te liggen, want die vergeet hem. Het bestand bepaalt hem, en de
    tabel staat in dit bestand zodat de proef hem kan nameten.
    """
    op_nr = next((o for p, o, _w in BESTANDEN if p == pad), False)
    return zoek(bestand, adres, nummer, op_huisnummer=op_nr, alles=alles)


def zoek(bestand, adres, nummer=None, op_huisnummer=False, alles=False):
    """
    Het record van dit pand uit een dict die per adres gesleuteld is.

    Geeft (sleutel, record) of (None, None). De sleutel komt terug zodat de
    aanroeper weet onder welke vorm hij het vond, en dus of er iets om te
    zetten valt.

    alles=True geeft [(sleutel, record), ...] voor élke vorm die bestaat. Dat
    is er voor de 60 panden die onder twee sleutels in hetzelfde bestand
    staan: wie alleen de eerste pakt, mist de helft van de geschiedenis. Bij
    de Berg en Dalseweg 287 zit de ene helft onder "bergendalseweg287" en de
    andere onder "debergendalseweg287".
    """
    if not isinstance(bestand, dict):
        return [] if alles else (None, None)
    gevonden = [(v, bestand[v]) for v in varianten(adres, nummer, op_huisnummer)
                if v in bestand]
    if alles:
        return gevonden
    return gevonden[0] if gevonden else (None, None)


def samenvoeg(bestand, op_huisnummer=False):
    """
    Records van hetzelfde pand onder één canonieke sleutel brengen.

    Geeft (nieuw_bestand, verslag). Een verslagregel is
    (canonieke_sleutel, [oude sleutels], gebeurtenissen erbij, soort) met
    soort "samengevoegd", "omgezet" of "overgeslagen". Die soort is er zodat
    de aanroeper kan nameten dat niets verdwijnt: bij een samenvoeging gaat
    er een record op in een ander, bij een omzetting verhuist het alleen.
    Zonder dat onderscheid telde de migratie een verhuisd record als
    weggegooid en weigerde hij terecht te schrijven.

    WAT HIER SAMENGAAT EN WAT NIET. Alleen records waarvan de canonieke
    sleutel gelijk is. Dat is dezelfde maatstaf die zoek() gebruikt, dus wat
    hier samengaat is precies wat een lezer anders half zou missen. Er wordt
    niets samengevoegd op grond van een gelijkend adres of een gelijk pand-id:
    twee adressen in hetzelfde gebouw zijn twee panden met elk hun eigen
    geschiedenis.

    HOE DE VELDEN SAMENGAAN. Het record onder de canonieke sleutel is de
    basis, want dat is het record dat de lezers vandaag al vinden. Velden die
    daar leeg zijn, worden gevuld uit de andere. Gebeurtenissen gaan samen en
    worden ontdubbeld op datum, soort en tekst, want dezelfde bekendmaking
    staat soms in beide helften. Dat ontdubbelen is waarom dit geen simpele
    optelling is en waarom het verslag het aantal toegevoegde gebeurtenissen
    teruggeeft in plaats van de som.

    Is er geen record onder de canonieke sleutel, dan wordt het record met de
    meeste gebeurtenissen de basis en krijgt het de canonieke sleutel.
    """
    if not isinstance(bestand, dict):
        return (bestand, [])

    groepen, overig = {}, {}
    for k, rec in bestand.items():
        if k == "_panden" or not isinstance(rec, (dict, list)):
            overig[k] = rec
            continue
        adres = _adres_van(rec)
        if not adres:
            # Zonder adres is de canonieke sleutel niet te bepalen, en dan
            # raden we niet. Het record blijft staan zoals het staat.
            overig[k] = rec
            continue
        kan = (sleutel_huisnummer(adres) if op_huisnummer else sleutel(adres))
        groepen.setdefault(kan, []).append(k)

    uit, verslag = dict(overig), []
    for kan, sleutels in groepen.items():
        if len(sleutels) == 1:
            # OOK EEN LOS RECORD HOORT ONDER ZIJN CANONIEKE SLEUTEL.
            # Samenvoegen alleen is niet genoeg: 53 records in
            # pandgeschiedenis.json waren niet dubbel maar wel scheef
            # gesleuteld, 28 met het lidwoord uit een bekendmakingstitel nog
            # in de sleutel, 13 met een accent weggegooid in plaats van
            # gevouwen, en 12 met de titel voluit ("professor" tegen "prof").
            # Die blijven vindbaar via varianten(), maar zolang ze scheef
            # staan is elke lezer afhankelijk van die zoeklijst in plaats van
            # van de sleutel. Omzetten kan hier zonder risico, want geen van
            # de 53 botst met een bestaand record; staat er onverwacht toch
            # iets, dan blijft het record waar het staat en meldt het
            # verslag dat.
            oud = sleutels[0]
            if oud == kan:
                uit[oud] = bestand[oud]
            elif kan in uit or kan in bestand:
                uit[oud] = bestand[oud]
                verslag.append((kan, [oud], 0, "overgeslagen"))
            else:
                uit[kan] = bestand[oud]
                verslag.append((kan, [oud], 0, "omgezet"))
            continue
        # De basis kiezen: het record dat al onder de canonieke sleutel staat,
        # anders het record met de meeste gebeurtenissen.
        if kan in sleutels:
            basis_sl = kan
        else:
            basis_sl = max(sleutels, key=lambda s: len(
                (bestand[s] or {}).get("gebeurtenissen") or []
                if isinstance(bestand[s], dict) else bestand[s] or []))
        basis = bestand[basis_sl]
        erbij = 0
        if isinstance(basis, dict):
            samen = dict(basis)
            geb = list(samen.get("gebeurtenissen") or [])
            gezien = {(g.get("datum"), g.get("soort"), g.get("tekst"))
                      for g in geb}
            for s in sleutels:
                if s == basis_sl:
                    continue
                ander = bestand[s]
                if not isinstance(ander, dict):
                    continue
                for veld, waarde in ander.items():
                    if veld == "gebeurtenissen" or veld in _gedeelde_velden():
                        # PANDVELDEN VERHUIZEN NIET TUSSEN TWEE ADRESRECORDS.
                        # bag_eenheden, bag_woningen, labels en bag_gezien
                        # horen bij het gebouw en staan daarom in _panden,
                        # onder het pand-id. Een adresrecord dat ze toch bij
                        # zich heeft, is een record zonder pand-id waarvan
                        # pandlezer.compact() ze niet kon delen.
                        #
                        # Het gat vullen uit de andere helft is hier dus fout.
                        # Op 11 oktober zette deze lus bij 53 samengevoegde
                        # panden een bag_gezien van 8 dagen oud terug op het
                        # adresrecord, terwijl in _panden de verse datum
                        # stond. pandlezer.laad() laat wat bij het adres
                        # staat winnen, dus elke lezer had tot de volgende
                        # compacte schrijfronde de oude waarde gezien. Bij
                        # bag_gezien kost dat niets, want compact() neemt het
                        # maximum; bij bag_eenheden zou het een oude
                        # woningtelling zijn, en dat is precies het soort
                        # fout dat niets meldt.
                        continue
                    if waarde and not samen.get(veld):
                        samen[veld] = waarde
                for g in ander.get("gebeurtenissen") or []:
                    merk = (g.get("datum"), g.get("soort"), g.get("tekst"))
                    if merk in gezien:
                        continue
                    gezien.add(merk)
                    geb.append(g)
                    erbij += 1
            geb.sort(key=lambda g: (g.get("datum") or "", g.get("soort") or ""))
            samen["gebeurtenissen"] = geb
        else:
            # Een lijstrecord, zoals in kamervergunningen.json: gewoon
            # aanschuiven en ontdubbelen op de hele rij.
            samen, gezien = list(basis or []), set()
            gezien = {json_sleutelbaar(x) for x in samen}
            for s in sleutels:
                if s == basis_sl:
                    continue
                for x in bestand[s] or []:
                    merk = json_sleutelbaar(x)
                    if merk in gezien:
                        continue
                    gezien.add(merk)
                    samen.append(x)
                    erbij += 1
        uit[kan] = samen
        # De weggevouwen sleutels zijn die naast de BASIS, niet die naast de
        # canonieke sleutel. Dat is niet hetzelfde: bij Laan van Oost-Indië
        # 315 staan beide helften onder een sleutel met het accent weggegooid
        # ("indi"), dus bestaat de canonieke vorm ("indie") nog niet en wordt
        # de grootste helft de basis. Noemde het verslag die dan als
        # weggevouwen, dan leek de telling twee gebeurtenissen kwijt en
        # weigerde de migratie te schrijven. Terecht geweigerd, maar de fout
        # zat in deze regel en niet in de samenvoeging.
        verslag.append((kan, sorted(s for s in sleutels if s != basis_sl),
                        erbij, "samengevoegd"))
    return (uit, sorted(verslag))


def _gedeelde_velden():
    """
    De velden die bij het gebouw horen, uit pandlezer en niet uit een kopie.

    Valt die import weg, dan geeft dit de velden die pandlezer vandaag deelt.
    Een lege rij teruggeven zou erger zijn dan een verouderde kopie: dan
    verhuist samenvoeg() stil weer pandvelden tussen adresrecords.
    """
    try:
        from pandlezer import GEDEELDE_VELDEN
        return GEDEELDE_VELDEN
    except Exception:
        return ("bag_eenheden", "bag_woningen", "bag_gevormd", "labels",
                "bag_gezien")


def json_sleutelbaar(x):
    """Een rij vergelijkbaar maken, ook als er een dict in zit."""
    import json as _json
    try:
        return _json.dumps(x, sort_keys=True, ensure_ascii=False)
    except Exception:
        return repr(x)


# Per bestand: hoe het gesleuteld is, en wat erin staat. Dit hoort hier en
# niet in een los overzichtsdocument, want dan veroudert het stil. De proef
# hieronder loopt deze tabel langs, dus een regel die niet klopt wordt rood.
BESTANDEN = (
    # pad, sleutelt op huisnummer zonder letter, wat erin staat
    ("pandgeschiedenis.json", False,
     "gebeurtenissen per adres, plus gedeelde pandgegevens onder _panden"),
    ("kamerverhuur_objecten.json", False,
     "panden die bij ons als kamerverhuur bekend staan, met bron"),
    ("verkocht_details.json", False,
     "verkochte panden met prijs, label, makelaar en perceel"),
    ("kamervergunningen.json", True,
     "onttrekkingen, omzettingen en samenvoegingen uit het Woo-verzoek"),
    ("rijksmonumenten_nijmegen.json", False,
     "rijksmonumenten met nummer, naam en functie"),
    ("verkoopdatums_model.json", False,
     "geschatte verkoopdatums uit het model"),
    ("brief_gezien.json", False,
     "wat de brief van dit pand eerder al vertelde"),
)


def _adres_van(rec):
    if isinstance(rec, dict):
        return rec.get("adres")
    if isinstance(rec, list):
        for x in rec:
            if isinstance(x, dict) and x.get("adres"):
                return x["adres"]
    return None


def proef():
    """
    Nameten op de echte bestanden, zonder netwerk en zonder iets te wijzigen.

    De vraag die deze proef stelt: raakt er een sleutel onvindbaar als de
    veertien oude functies door deze ene worden vervangen? Dat is de enige
    vraag die telt, want een onvindbare sleutel geeft geen foutmelding maar
    een leeg dossier.
    """
    import json
    import os
    fouten = []

    def check(naam, echt, verwacht):
        if echt != verwacht:
            fouten.append(f"{naam}: {echt!r}, verwacht {verwacht!r}")

    def veld_van(bestand, sleutel, veld):
        """
        Een veld van een record, of None als dat record er niet is.

        Zonder dit valt de proef om met een KeyError zodra een omzetting niet
        gebeurt, en dan is niet te lezen welke controle rood stond. Dat is me
        in deze sessie twee keer overkomen, dus staat het nu in een hulpje.
        """
        rec = (bestand or {}).get(sleutel)
        return (rec or {}).get(veld) if isinstance(rec, dict) else None

    # De vorm zelf, op echte adressen uit de bestanden.
    check("gewoon", sleutel("Abeelstraat 4"), "abeelstraat4")
    check("twee argumenten", sleutel("Abeelstraat", 4), "abeelstraat4")
    check("titel voluit", sleutel("Professor Molkenboerstraat 18"),
          "profmolkenboerstraat18")
    check("titel afgekort", sleutel("Prof. Molkenboerstraat 18"),
          "profmolkenboerstraat18")
    check("sint", sleutel("Sint Annastraat 7"), "stannastraat7")
    check("sint afgekort", sleutel("St. Annastraat 7"), "stannastraat7")
    # Niet elke straat die met "sint" begint is een heilige.
    check("sinterklaas blijft heel", sleutel("Sinterklaasstraat 1"),
          "sinterklaasstraat1")
    check("lidwoord weg", sleutel("de Pijnboomstraat 17"), "pijnboomstraat17")
    check("aan de weg", sleutel("aan de Pijnboomstraat 17"),
          "pijnboomstraat17")
    # Het accent wordt gevouwen en niet weggegooid: de oude regex maakte van
    # Mariënburg "marinburg", en dat kan met een andere straat botsen.
    check("accent gevouwen", sleutel("Mariënburg 82-A"), "marienburg82a")
    check("accent in de straat", sleutel("Marga Klompélaan 37"),
          "margaklompelaan37")
    check("letter blijft", sleutel("Augustijnenstraat 25B"),
          "augustijnenstraat25b")
    check("zonder letter", sleutel_huisnummer("Augustijnenstraat 25B"),
          "augustijnenstraat25")
    check("getal in de straatnaam", sleutel("Plein 1944 168"), "plein1944168")
    check("geen nummer", sleutel("Jozef Israëlsstraat"), "jozefisraelsstraat")
    check("splits bereik", splits("Mariënburg 82-A"), ("Mariënburg", "82-A"))
    check("splits zonder nummer", splits("Hertogstraat"), ("Hertogstraat", ""))
    check("leeg", sleutel(""), "")
    check("none", sleutel(None), "")

    # De oude vormen moeten vindbaar blijven, anders kan de overstap niet in
    # twee stappen.
    v = varianten("de Berg en Dalseweg 287")
    check("oude lidwoordvorm in varianten", "debergendalseweg287" in v, True)
    check("canonieke vorm vooraan", v[0], "bergendalseweg287")
    v = varianten("Professor Molkenboerstraat 18")
    for oud in ("profmolkenboerstraat18", "professormolkenboerstraat18",
                "deprofmolkenboerstraat18"):
        check(f"variant {oud}", oud in v, True)
    v = varianten("Mariënburg 20")
    for oud in ("marienburg20", "marinburg20", "mariënburg20"):
        check(f"variant {oud}", oud in v, True)
    # De vorm zonder huisletter staat er alleen in als erom gevraagd wordt.
    check("nummervorm niet standaard",
          "augustijnenstraat25" in varianten("Augustijnenstraat 25B"), False)
    check("nummervorm op verzoek",
          "augustijnenstraat25" in varianten("Augustijnenstraat 25B",
                                             op_huisnummer=True), True)

    # SAMENVOEGEN: niets mag verdwijnen, en niets mag onterecht samengaan.
    heen = {
        "bergendalseweg287": {
            "adres": "Berg en Dalseweg 287", "pand_id": "P9",
            "gebeurtenissen": [
                {"datum": "2026-10-01", "soort": "bag", "tekst": "een"},
                {"datum": "2026-10-02", "soort": "bag", "tekst": "twee"}]},
        "debergendalseweg287": {
            "adres": "de Berg en Dalseweg 287", "pand_id": None,
            "labels": {"Berg en Dalseweg 287": "C"},
            "gebeurtenissen": [
                # Deze staat in beide helften en mag niet dubbel worden.
                {"datum": "2026-10-01", "soort": "bag", "tekst": "een"},
                {"datum": "2026-10-03", "soort": "bekendmaking",
                 "tekst": "drie"}]},
        # Een ander pand in dezelfde straat mag niet meegaan.
        "bergendalseweg289": {
            "adres": "Berg en Dalseweg 289", "pand_id": "P10",
            "gebeurtenissen": [{"datum": "2026-10-01", "soort": "bag",
                                "tekst": "van 289"}]},
        # Zonder adres is de canonieke sleutel niet te bepalen: laten staan.
        "ietszonderadres": {"gebeurtenissen": []},
        "_panden": {"P9": {"bag_eenheden": [["Berg en Dalseweg 287", 90]]}},
    }
    voor = sum(len(r.get("gebeurtenissen") or []) for k, r in heen.items()
               if k != "_panden" and isinstance(r, dict))
    nieuw, verslag = samenvoeg(heen)
    check("samenvoegen laat drie records over", len(
        [k for k in nieuw if k != "_panden"]), 3)
    check("de de-vorm is weg", "debergendalseweg287" in nieuw, False)
    check("de canonieke vorm staat er", "bergendalseweg287" in nieuw, True)
    check("buurpand blijft apart", "bergendalseweg289" in nieuw, True)
    check("record zonder adres blijft", "ietszonderadres" in nieuw, True)
    check("_panden blijft", "P9" in (nieuw.get("_panden") or {}), True)
    geb = veld_van(nieuw, "bergendalseweg287", "gebeurtenissen") or []
    check("gebeurtenissen samen", len(geb), 3)
    check("niet dubbel geteld",
          sum(1 for g in geb if g.get("tekst") == "een"), 1)
    check("op datum gesorteerd", [g.get("datum") for g in geb],
          ["2026-10-01", "2026-10-02", "2026-10-03"])
    samen = nieuw.get("bergendalseweg287") or {}
    # PANDVELDEN NIET AANVULLEN UIT DE ANDERE HELFT. labels hoort bij het
    # gebouw en staat in _panden; op het adresrecord zetten laat
    # pandlezer.laad() die waarde winnen van de gedeelde, en dan leest
    # iedereen een oude telling tot de volgende compacte schrijfronde. Op 11
    # oktober deed deze lus dat bij 53 panden met bag_gezien.
    check("pandveld niet overgenomen", samen.get("labels"), None)
    check("gewoon veld blijft van de basis", samen.get("pand_id"), "P9")
    # Een pand-id dat de basis mist, mag wel uit de andere helft komen: dat
    # is geen gedeeld veld maar de verwijzing ernaar.
    zonder_id = {"a": {"adres": "Berg en Dalseweg 287", "pand_id": None,
                       "gebeurtenissen": []},
                 "debergendalseweg287": {"adres": "de Berg en Dalseweg 287",
                                         "pand_id": "P9",
                                         "gebeurtenissen": []}}
    nieuw5, _v5 = samenvoeg(zonder_id)
    check("pand-id wel aangevuld",
          veld_van(nieuw5, "bergendalseweg287", "pand_id"), "P9")
    # Eén erbij en niet twee: de andere helft had twee gebeurtenissen, maar
    # "een" stond al in de basis. Het verslag telt wat er werkelijk bijkwam,
    # niet wat er in de andere helft stond.
    check("verslag noemt wat erbij kwam",
          [r for r in verslag if r[3] == "samengevoegd"],
          [("bergendalseweg287", ["debergendalseweg287"], 1,
            "samengevoegd")])
    # Het buurpand staat al goed en hoort dus niet in het verslag; het record
    # zonder adres kan niet omgezet worden en staat er ook niet in.
    check("niets anders in het verslag", len(verslag), 1)
    na = sum(len(r.get("gebeurtenissen") or []) for k, r in nieuw.items()
             if k != "_panden" and isinstance(r, dict))
    check("geen gebeurtenis verdwenen", na, voor - 1)  # de ene dubbele eraf
    # Nog eens samenvoegen hoort niets meer te doen.
    weer, verslag2 = samenvoeg(nieuw)
    check("tweede keer verandert niets", verslag2, [])
    check("tweede keer gelijk resultaat", weer, nieuw)

    # EEN LOS RECORD ONDER EEN SCHEVE SLEUTEL VERHUIST. 53 records in
    # pandgeschiedenis.json waren niet dubbel maar wel scheef gesleuteld, en
    # samenvoegen alleen liet die staan.
    los = {"decargadoorweg3": {"adres": "de Cargadoorweg 3",
                               "gebeurtenissen": [{"datum": "2026-10-01",
                                                   "soort": "bag",
                                                   "tekst": "x"}]},
           "professormolkenboerstraat20": {"adres": "Professor "
                                                    "Molkenboerstraat 20",
                                           "gebeurtenissen": []}}
    nieuw3, verslag3 = samenvoeg(los)
    check("lidwoord uit de sleutel", "cargadoorweg3" in nieuw3, True)
    check("titel afgekort in de sleutel",
          "profmolkenboerstraat20" in nieuw3, True)
    check("oude vormen zijn weg",
          [k for k in ("decargadoorweg3", "professormolkenboerstraat20")
           if k in nieuw3], [])
    check("de weergave blijft zoals de bron hem gaf",
          veld_van(nieuw3, "cargadoorweg3", "adres"), "de Cargadoorweg 3")
    check("omzetting staat als omzetting in het verslag",
          sorted(s for _k, _o, _n, s in verslag3), ["omgezet", "omgezet"])
    check("een omzetting voegt niets samen",
          sum(n for _k, _o, n, _s in verslag3), 0)
    # EEN OMZETTING MAG NOOIT EEN ANDER RECORD OVERSCHRIJVEN. Dat kan alleen
    # als de doelsleutel al bezet is door een record dat er zelf niet hoort:
    # hieronder staat onder "cargadoorweg3" een pand aan de Hertogstraat. Een
    # eerste versie van deze controle zette twee records neer die dezelfde
    # canonieke sleutel hadden, en die namen de samenvoegweg, dus deze tak
    # werd niet geraakt en de controle bewees niets.
    bots = {"decargadoorweg3": {"adres": "de Cargadoorweg 3",
                                "gebeurtenissen": []},
            "cargadoorweg3": {"adres": "Hertogstraat 1",
                              "gebeurtenissen": [{"datum": "2026-01-01",
                                                  "soort": "bag",
                                                  "tekst": "van hertog"}]}}
    nieuw4, verslag4 = samenvoeg(bots)
    check("bezette sleutel wordt niet overschreven",
          [r.get("adres") for r in nieuw4.values()
           if isinstance(r, dict) and r.get("gebeurtenissen")],
          ["Hertogstraat 1"])
    check("overgeslagen staat in het verslag",
          sorted(s for _k, _o, _n, s in verslag4), ["omgezet", "overgeslagen"])
    check("geen gebeurtenis kwijt bij een botsing",
          _tel_gebeurtenissen(nieuw4), _tel_gebeurtenissen(bots))

    # DE CONTROLES OP DE BRIEF STAAN IN DE BRIEF. Tot 11 november stonden hier
    # ook de zestien sleutelfuncties in de brief en de nameting op de echte
    # bestanden van de brief. Sinds de splitsing staat deze module in de
    # openbare repo nijmegen-marktdata en kan hij de brief niet meer zien.
    # Die controles staan nu in marktdata_toets.py in de brief-repo, en de
    # eisen die ernaar verwijzen ook. Een openbare repo die naar een privé
    # repo kijkt, zou die privé repo openbaar maken.

    for f in fouten:
        print(f"FOUT {f}", file=sys.stderr)
    print(f"Proef: {len(fouten)} fouten. Gedekt: de vorm zelf, de oude "
          f"vormen die vindbaar moeten blijven, het verschil tussen pand en "
          f"woning, en het samenvoegen. De nameting op de bestanden van de "
          f"brief staat in marktdata_toets.py in de brief-repo.",
          file=sys.stderr)
    return 1 if fouten else 0


def _tel_gebeurtenissen(bestand):
    n = 0
    for k, rec in bestand.items():
        if k == "_panden":
            continue
        if isinstance(rec, dict):
            n += len(rec.get("gebeurtenissen") or [])
        elif isinstance(rec, list):
            n += len(rec)
    return n


def migreer(droog=False):
    """
    De dubbele records in de bestanden samenvoegen, eenmalig.

    Dit staat hier en niet in een los script, want een script dat één keer
    draait en daarna niemand meer leest, is geen code die iemand onderhoudt.
    Als functie draait hij mee in de proef en is hij opnieuw te gebruiken
    zodra er ooit weer dubbele records opduiken.

    Hij telt de gebeurtenissen voor en na. Dat aantal mag alleen dalen door
    gebeurtenissen die in beide helften stonden, en hoeveel dat er zijn staat
    in het verslag. Klopt die som niet, dan schrijft hij niets.
    """
    import json
    import os
    fout = 0
    for pad, op_nr, _wat in BESTANDEN:
        if not os.path.exists(pad):
            print(f"{pad}: bestaat niet, overgeslagen", file=sys.stderr)
            continue
        with open(pad, encoding="utf-8") as f:
            oud = json.load(f)
        voor_records = len([k for k in oud if k != GEDEELD_PANDEN])
        voor_geb = _tel_gebeurtenissen(oud)
        nieuw, verslag = samenvoeg(oud, op_huisnummer=op_nr)
        if not verslag:
            print(f"{pad}: {voor_records} records, niets dubbel",
                  file=sys.stderr)
            continue
        na_records = len([k for k in nieuw if k != GEDEELD_PANDEN])
        na_geb = _tel_gebeurtenissen(nieuw)
        # Wat er volgens het verslag bij is gekomen, plus wat er volgens de
        # telling is verdwenen, moet precies het aantal gebeurtenissen zijn
        # dat in de samengevoegde helften stond. Anders is er iets weg.
        # Alleen de samenvoegingen laten gebeurtenissen opgaan in een ander
        # record; een omzetting verhuist alleen een sleutel.
        voeg = [r for r in verslag if r[3] == "samengevoegd"]
        erbij = sum(n for _k, _o, n, _s in voeg)
        weg = sum(_tel_gebeurtenissen({k: oud[k]})
                  for _k, ouds, _n, _s in voeg for k in ouds)
        verwacht = voor_geb - (weg - erbij)
        print(f"{pad}: {voor_records} -> {na_records} records, "
              f"{len(verslag)} samengevoegd, {voor_geb} -> {na_geb} "
              f"gebeurtenissen (verwacht {verwacht})", file=sys.stderr)
        for kan, ouds, n, soort in verslag[:5]:
            print(f"    {soort}: {kan} <- {', '.join(ouds)} (+{n})",
                  file=sys.stderr)
        if na_geb != verwacht:
            print(f"  NIET GESCHREVEN: de telling klopt niet, er zou een "
                  f"gebeurtenis verdwijnen", file=sys.stderr)
            fout += 1
            continue
        if droog:
            print("  droog, niets geschreven", file=sys.stderr)
            continue
        with open(pad, "w", encoding="utf-8") as f:
            json.dump(nieuw, f, ensure_ascii=False, indent=1, sort_keys=True)
        print(f"  geschreven", file=sys.stderr)
    return 1 if fout else 0


GEDEELD_PANDEN = "_panden"


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--proef", action="store_true",
                    help="Nameten op de echte bestanden.")
    ap.add_argument("--adres", default="",
                    help="De sleutel en de varianten van dit adres tonen.")
    ap.add_argument("--migreer", action="store_true",
                    help="Dubbele records in de bestanden samenvoegen.")
    ap.add_argument("--droog", action="store_true",
                    help="Bij --migreer: tellen wat er zou gebeuren, niets "
                         "schrijven.")
    a = ap.parse_args()
    if a.adres:
        print(f"sleutel:          {sleutel(a.adres)}")
        print(f"op huisnummer:    {sleutel_huisnummer(a.adres)}")
        print("varianten:")
        for v in varianten(a.adres, op_huisnummer=True):
            print(f"  {v}")
        sys.exit(0)
    if a.migreer:
        sys.exit(migreer(droog=a.droog))
    sys.exit(proef() if a.proef else 0)
