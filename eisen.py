#!/usr/bin/env python3
"""
De eisen aan nijmegen-marktdata lezen, en nameten of ze werkelijk gehandhaafd
worden.

HERKOMST EN SCHULD. Dit is een kopie van eisen.py uit de vastgoedbrief, van 11
november, toen de ophaalrondes naar deze openbare repo verhuisden. Drie
controles die alleen over de brief gaan staan hier uit: de kaartschakelaar, de
kennisblokken van bronnen.py en de startdagen van de briefworkflow; die laatste
meet hier de voorraadworkflow. Twee kopieën van dezelfde controles lopen
uiteen. Dat staat als schuld in VERBETERLIJST.md: dit bestand hoort de enige
implementatie te worden, en de brief hoort het hiervandaan te gebruiken.

WAT DIT OPLOST. De regels waaraan de brief zich houdt stonden verspreid over
33.000 regels docstrings en workflowcommentaar, elk opgeschreven op de dag dat
het misging. Een losse lijst in markdown zou dat niet oplossen: die veroudert
stil, en stil verouderen is precies de fout die we deze week vijf keer hebben
gezien.

Daarom noemt elke eis in eisen.txt de controle die hem handhaaft, en meet dit
bestand na of die controle bestaat, groen staat, en de naam draagt waar de eis
naar verwijst. Wordt zo'n controle weggehaald of omgedoopt, dan is dit rood.

WAT HET NIET DOET. Het toetst niet of een controle werkelijk meet wat de eis
zegt; dat kan geen programma. Een eis zonder proef staat er met "proef: -" en
dat is een eerlijker antwoord dan een verwijzing die niets afdwingt. Het
verschil tussen wat we willen en wat gecontroleerd wordt, hoort zichtbaar te
zijn in plaats van impliciet.
"""
import argparse
import glob
import os
import re
import subprocess
import sys

PAD = "eisen.txt"
VERPLICHT = ("eis", "waarom", "proef")
TOEGESTAAN = VERPLICHT + ("soort", "let op", "deels")

# DRIE STANDEN EN NIET TWEE. Een eis met een proef EN een "let op" dat zegt
# dat hij niet verder te handhaven is, is deels afgedwongen. Die bij de
# afgedwongen eisen tellen overdrijft, en bij de niet-afgedwongen
# onderschat. Dat verschil zichtbaar houden is precies waarvoor dit bestand
# bestaat, dus krijgt het een eigen veld: "deels: ja".


def lees(pad=PAD):
    """
    De eisen als lijst van dicts, in de volgorde waarin ze in het bestand staan.

    Een waarde loopt door op de volgende regel als die met twee spaties begint;
    dat houdt een eis van twee zinnen leesbaar in het bestand zonder dat hij
    uit elkaar valt. Fouten in de vorm worden niet stil overgeslagen maar
    verzameld in de sleutel "_fouten" van het laatste blok, zodat proef() ze
    kan melden.
    """
    eisen, blok, veld, fouten = [], None, None, []
    try:
        with open(pad, encoding="utf-8") as f:
            regels = f.read().splitlines()
    except Exception as e:
        return ([], [f"{pad} niet te lezen: {str(e)[:60]}"])
    for n, regel in enumerate(regels, 1):
        kaal = regel.strip()
        if kaal.startswith("#") or (not kaal and blok is None):
            continue
        if kaal == "---":
            if blok:
                eisen.append(blok)
            blok, veld = {}, None
            continue
        if blok is None:
            if kaal:
                fouten.append(f"regel {n}: tekst voor het eerste --- blok")
            continue
        if regel.startswith("  ") and veld:
            # Doorloop van de vorige waarde.
            blok[veld] = (blok[veld] + " " + kaal).strip()
            continue
        if not kaal:
            continue
        if ":" not in kaal:
            fouten.append(f"regel {n}: geen veld, en geen doorloop: {kaal[:40]!r}")
            continue
        naam, waarde = kaal.split(":", 1)
        naam, waarde = naam.strip().lower(), waarde.strip()
        if naam not in TOEGESTAAN:
            fouten.append(f"regel {n}: onbekend veld {naam!r}")
            continue
        # TWEE KEER HETZELFDE VELD IN EEN BLOK IS EEN VERLOREN EIS. Op 16
        # oktober botsten twee pull requests in dit bestand; bij het oplossen
        # verdween de --- ertussen, en twee eisen werden één blok. De tweede
        # overschreef de eerste stil, en de proef bleef groen met 78 in plaats
        # van 79 eisen.
        if naam in blok:
            fouten.append(f"regel {n}: veld {naam!r} staat twee keer in één "
                          f"blok; ontbreekt hier een regel met ---?")
        blok[naam] = waarde
        veld = naam
    if blok:
        eisen.append(blok)
    for i, e in enumerate(eisen, 1):
        for v in VERPLICHT:
            if not e.get(v):
                fouten.append(f"eis {i} mist het veld {v!r}: "
                              f"{(e.get('eis') or '?')[:50]}")
    return (eisen, fouten)


def _modules_met_proef():
    """
    De modules met een proef, uit de bron en niet uit een lijst.

    HET CRITERIUM IS "def proef(" EN GEEN "--proef". Een eerdere versie zocht
    naar de vlag, en dan viel toets_artikel15.py erbuiten: die draait zijn
    proef onvoorwaardelijk als script en heeft dus geen vlag. Daarmee sloeg
    de controle op de exitcode die module stil over, terwijl hij als poort in
    de workflow staat. Een detector met een eigen aanname over hoe een proef
    wordt aangeroepen, mist precies de module die het anders doet.
    """
    uit = []
    for naam in sorted(os.listdir(".")):
        if not naam.endswith(".py"):
            continue
        try:
            with open(naam, encoding="utf-8") as f:
                bron = f.read()
        except Exception:
            continue
        if "def proef(" in bron and "__main__" in bron:
            uit.append(naam[:-3])
    return uit


def _vlag(module):
    """Hoe deze module zijn proef aangeroepen wil hebben."""
    bron = _bron(module) or ""
    return ["--proef"] if '"--proef"' in bron else []


def _bron(module):
    try:
        with open(f"{module}.py", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def _eindigt_op_sys_exit(bron):
    """
    Geeft de main-regel terug als die NIET op sys.exit staat, anders None.

    Dit is de eis "een proef die rood staat geeft een exitcode die niet 0 is",
    en dit is het deel dat machinaal te zien is: een module die zijn main
    aanroept zonder sys.exit geeft altijd 0 terug, hoe rood de proef ook staat.
    Op 11 oktober was dat bij pandgeschiedenis.py het geval, en dan is de
    poort in de workflow altijd groen.
    """
    m = re.search(r'if __name__ == ["\']__main__["\']:\s*\n((?:[ \t]+.*\n?)+)',
                  bron or "")
    if not m:
        return "geen __main__ blok"
    staart = m.group(1)
    if "sys.exit" in staart:
        return None
    return staart.strip().splitlines()[-1][:60]


WORKFLOWS = (os.path.join(".github", "workflows", "voorraad.yml"),
             os.path.join(".github", "workflows", "publicaties.yml"))
BRIEFWORKFLOW = WORKFLOWS[0]
DAGNAMEN = ("zondag", "maandag", "dinsdag", "woensdag", "donderdag",
            "vrijdag", "zaterdag")


def _crondagen(veld):
    """
    De weekdagen uit het laatste veld van een cron, als verzameling 0 t/m 6.

    Cron kent zondag als 0 en als 7. Een expander die dat niet weet, noemt
    "17 0 * * 7" een zondag die er niet is en laat de zondag ongedekt lijken.
    """
    dagen = set()
    for deel in str(veld).split(","):
        deel, stap = deel.strip(), 1
        if "/" in deel:
            deel, _, s = deel.partition("/")
            try:
                stap = max(1, int(s))
            except ValueError:
                stap = 1
        if deel == "*":
            begin, eind = 0, 6
        elif "-" in deel:
            a, _, b = deel.partition("-")
            try:
                begin, eind = int(a), int(b)
            except ValueError:
                continue
        else:
            try:
                begin = eind = int(deel)
            except ValueError:
                continue
        for d in range(begin, eind + 1, stap):
            dagen.add(0 if d == 7 else d)
    return {d for d in dagen if 0 <= d <= 6}


def _alle_workflows(map_pad=os.path.join(".github", "workflows")):
    """
    Elk workflowbestand, en niet een vaste lijst van twee.

    WAAROM NIET EEN LIJST. commitstap() stond op WORKFLOWS, een tuple met
    bekendmakingen.yml en voorraad.yml. Zo'n lijst moet worden bijgewerkt bij
    elke nieuwe workflow, en dat gebeurt niet: deze controle bestaat juist
    omdat dezelfde fout in controle_sleutels_in_stappen al een keer een nieuwe
    workflow niet dekte. Nu komt de lijst uit de map.
    """
    try:
        return tuple(os.path.join(map_pad, n) for n in sorted(os.listdir(map_pad))
                     if n.endswith((".yml", ".yaml")))
    except Exception:
        return ()


def commitstap(paden=None):
    """
    Of een run die gegevens terugschrijft geen broncode kan veranderen.

    WAT HIER GEBEURDE. voorraad.yml zette bij een geweigerde push HEAD naar de
    remote met "git reset --soft" en committeerde opnieuw. Soft laat de hele
    index van de oude checkout staan, dus die commit schreef de boom van het
    moment waarop de ronde BEGON. De ronde van 13 oktober 07:04 duurde 102
    minuten; in dat uur werden PR 56 en PR 57 gemerged, en zijn commit van
    08:46 draaide beide volledig terug: zes bestanden broncode en drie eisen.

    Het ergste eraan was niet de terugdraai maar de stilte. Alle proeven bleven
    groen, want de eisen die naar die controles verwezen waren met dezelfde
    commit verdwenen. Daarom staat deze toets hier en niet in een proef van een
    van beide workflows: hij moet blijven staan ook als alles eromheen wegvalt.

    Twee dingen per workflow: geen "git reset --soft", en een toets die een
    commit tegenhoudt die .py of .yml aanraakt.
    """
    fouten = []
    paden = paden if paden is not None else _alle_workflows()
    if not paden:
        return ["geen workflowbestand gevonden om de commitstap te toetsen"]
    gekeken = 0
    for pad in paden:
        try:
            with open(pad, encoding="utf-8") as f:
                bron = f.read()
        except Exception as e:
            fouten.append(f"{pad} niet te lezen: {str(e)[:50]}")
            continue
        # ALLEEN WORKFLOWS DIE WERKELIJK COMMITTEN. Een verkenning die niets
        # terugschrijft heeft geen commitstap en dus ook geen vangnet nodig.
        # De uitzondering volgt uit de inhoud van het bestand en niet uit een
        # lijst met namen, want zo'n lijst veroudert.
        # EEN WORKFLOW DIE terugcommitten.sh AANROEPT, wordt op dat script
        # getoetst: daar staat sinds 11 november de lus, zodat twee workflows
        # niet elk een eigen kopie hebben.
        if "terugcommitten.sh" in bron:
            script = os.path.join(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(pad)))), "terugcommitten.sh")
            try:
                with open(script, encoding="utf-8") as f:
                    bron = bron + "\n" + f.read()
            except Exception as e:
                fouten.append(f"{pad} roept terugcommitten.sh aan, maar dat "
                              f"is niet te lezen: {str(e)[:50]}")
                continue
        if "git commit" not in bron:
            continue
        gekeken += 1
        # Alleen echte shellregels, niet het commentaar dat de fout uitlegt.
        regels = [r.strip() for r in bron.splitlines()
                  if not r.strip().startswith("#")]
        for r in regels:
            if "git reset --soft" in r:
                fouten.append(f"{pad} gebruikt 'git reset --soft'; die schrijft "
                              f"de hele index van de oude checkout terug en "
                              f"draait werk terug dat tijdens de run is "
                              f"gemerged")
                break
        if "geen_broncode" not in bron:
            fouten.append(f"{pad} committeert en heeft geen toets die een "
                          f"commit tegenhoudt die broncode aanraakt")
    if not gekeken:
        fouten.append("geen enkele workflow committeert; dat kan kloppen, "
                      "maar dan toetst deze controle niets")
    return fouten


def leesbaar_kanaal(paden=None):
    """
    Of elke workflow zijn uitkomst ergens neerzet waar wij hem kunnen lezen.

    WAT HIER GEBEURDE. dossiermail.yml draaide op 13 oktober groen: zes
    stappen gelukt, werkmap schoon. Wat er in het dossier zat was alleen naar
    stderr geschreven, en dat komt in het joblogboek van GitHub. Dat logboek
    zit achter productionresultssa8.blob.core.windows.net, dat van buiten de
    runner wordt geweigerd. Ik had dus een verkenning gebouwd waarvan ik de
    uitkomst niet kon lezen: groen en onleesbaar tegelijk.

    Dezelfde fout trof die ochtend de brief. Daar is hij opgelost door de
    staart van het logboek in briefstand.json te zetten. Zo'n oplossing per
    geval houdt niet: de volgende workflow begint weer met stderr. Daarom
    toetst dit de regel in plaats van de twee gevallen.

    WAT GELDT ALS EEN LEESBAAR KANAAL. Iets dat van buiten de runner op te
    vragen is: een commit, een issue, een mail, of een artefact. Het
    joblogboek niet. De lijst komt uit de inhoud van het bestand en niet uit
    een lijst met workflownamen, want zo'n lijst wordt niet bijgewerkt.
    """
    KANALEN = ("git commit", "gh issue", "gh api", "upload-artifact",
               "MAIL_USERNAME", "GITHUB_STEP_SUMMARY")
    fouten = []
    paden = paden if paden is not None else _alle_workflows()
    if not paden:
        return ["geen workflowbestand gevonden om het kanaal te toetsen"]
    for pad in paden:
        try:
            with open(pad, encoding="utf-8") as f:
                bron = f.read()
        except Exception as e:
            fouten.append(f"{pad} niet te lezen: {str(e)[:50]}")
            continue
        # Alleen echte regels, niet het commentaar waarin deze fout wordt
        # uitgelegd; anders maakt de uitleg zelf de toets groen.
        echt = "\n".join(r for r in bron.splitlines()
                         if not r.strip().startswith("#"))
        if not any(k in echt for k in KANALEN):
            fouten.append(f"{pad} zet zijn uitkomst nergens neer waar wij hem "
                          f"kunnen lezen. Alles wat de stappen printen komt "
                          f"in het joblogboek, en dat wordt van buiten de "
                          f"runner geweigerd. Een commit, een issue, een mail "
                          f"of een artefact is wel te lezen.")
    return fouten


def _modules_die_importeren(naam, map_pad="."):
    """Welke modules in de map een bepaalde module importeren. Uit de map."""
    uit = []
    try:
        namen = sorted(n for n in os.listdir(map_pad) if n.endswith(".py"))
    except Exception:
        return uit
    for n in namen:
        if n == naam + ".py":
            continue
        try:
            with open(os.path.join(map_pad, n), encoding="utf-8") as f:
                bron = f.read()
        except Exception:
            continue
        if re.search(rf"^\s*(import {naam}\b|from {naam} import)", bron,
                     re.M):
            uit.append(n)
    return uit


def kaartschakelaar():
    """
    Of de workflow die een kaartmodule aanroept ook REPO_PRIVE meegeeft.

    WAT HIER SPEELT. De drie kaarten in de brief staan op GitHub Pages, en
    Pages werkt alleen bij een publieke repo. kaartlink.py laat de link weg
    zodra REPO_PRIVE "true" is, en ook als hij niet is gezet, want een dode
    link in een brief naar pa is erger dan geen link.

    DAAROM DEZE TOETS. Die voorzichtige kant heeft een keerzijde: zet niemand
    de variabele, dan vallen de kaarten stil uit de brief en lijkt dat op een
    bewuste keuze. "Niet gezet" en "op prive gezet" mogen niet hetzelfde
    lezen. Dus toetst dit dat elke workflow die zo'n module aanroept de
    variabele werkelijk meegeeft.

    De lijst modules komt uit de map en niet uit een opsomming hier: wie
    kaartlink gaat importeren, valt er vanzelf onder.
    """
    fouten = []
    modules = _modules_die_importeren("kaartlink")
    if not modules:
        # Geen enkele module gebruikt de schakelaar. Dat kan kloppen, maar dan
        # toetst dit niets en hoort dat te blijken.
        return ["geen enkele module importeert kaartlink; dan staat de "
                "Pages-url weer los in de scripts of is de schakelaar weg"]
    for pad in _alle_workflows():
        try:
            with open(pad, encoding="utf-8") as f:
                bron = f.read()
        except Exception as e:
            fouten.append(f"{pad} niet te lezen: {str(e)[:50]}")
            continue
        roept = [m for m in modules if f"python {m}" in bron or
                 f"python3 {m}" in bron]
        if not roept:
            continue
        if "REPO_PRIVE" not in bron:
            fouten.append(f"{pad} roept {', '.join(roept)} aan en geeft "
                          f"REPO_PRIVE niet mee. Dan vallen de kaartlinks "
                          f"stil uit de brief, ook als de repo publiek is.")
    return fouten


def pijp_zonder_vangnet(paden=None):
    """
    Of een stap die iets door een pijp stuurt ook pipefail aanzet.

    WAT HIER GEBEURDE. De veldenronde van 13 oktober meldde "gelukt" terwijl
    python met een traceback stierf. De regel was

        python publicatievelden.py ... 2>&1 | tee "$RUNNER_TEMP/ronde.log"

    en in een pijplijn is de exitcode die van het LAATSTE commando. tee
    slaagt altijd. De stap stond dus groen, er werd niets gecommit, en de
    meldstap ging niet af omdat er formeel geen mislukking was. Drie rondes
    kwijt voordat ik doorhad dat de fout al in de eerste stap zat.

    Dit is geen eigenaardigheid van die ene regel. Elke stap die uitvoer
    door tee, head, tail of grep haalt om hem te bewaren of te filteren,
    verliest de exitcode van wat ervoor stond. Daarom toetst dit alle
    workflows in de map en niet die ene.

    Commentaar telt niet mee: de uitleg van deze fout zou de toets anders
    zelf groen maken.
    """
    # ALLEEN tee, EN NIET head, tail OF grep.
    #
    # Eerst stond hier ook head, tail en grep. Nagemeten op de echte
    # workflows gaf dat twee treffers in de briefworkflow die geen van
    # beide een fout zijn: daar staat "grep -E Versies ... | head -3" om
    # iets te TONEN, en een grep die niets vindt is daar geen mislukking.
    # Met pipefail zou die stap gaan melden bij correct gedrag, en dat is
    # precies het soort valse melding dat de lezer leert het logboek over te
    # slaan.
    #
    # tee is anders: dat is het patroon "voer dit uit en bewaar de uitvoer".
    # Daar is de uitkomst van wat ervoor staat het hele punt, en die mag niet
    # verdwijnen.
    PIJPEN = re.compile(r"\|\s*tee\b")
    fouten = []
    paden = paden if paden is not None else _alle_workflows()
    if not paden:
        return ["geen workflowbestand gevonden om de pijpen te toetsen"]
    for pad in paden:
        try:
            with open(pad, encoding="utf-8") as f:
                bron = f.read()
        except Exception as e:
            fouten.append(f"{pad} niet te lezen: {str(e)[:50]}")
            continue
        for blok in bron.split("\n      - name: ")[1:]:
            naam = blok.split("\n")[0].strip()
            if "run: |" not in blok:
                continue
            run = blok.split("run: |", 1)[1]
            echt = "\n".join(r for r in run.splitlines()
                              if not r.strip().startswith("#"))
            if PIJPEN.search(echt) and "pipefail" not in echt:
                fouten.append(f"{pad}, stap {naam[:48]!r}: stuurt uitvoer "
                              f"door een pijp zonder 'set -o pipefail'. De "
                              f"exitcode is dan die van het laatste commando "
                              f"en een fout ervoor verdwijnt.")
    return fouten


def komma_vervanging(paden=None):
    """
    Een tekst met een komma erin, waarop .replace(",", ".") wordt gedaan.

    WAAROM. 20 oktober 2026: op acht plekken gaf f"... €{x:,} ...".replace(
    ",", ".") een punt waar de zin een komma had, en een duizendtalpunt waar
    een decimaal stond. In de brief: "gemeten premie 1.425 voor die klasse.
    dus €7.746/m2". Getallen gaan via getal.py; deze toets vindt de oude vorm
    terug, alleen waar de letterlijke tekst zelf een komma bevat.
    """
    import ast as _ast
    fouten = []
    for pad in paden or sorted(glob.glob("*.py")):
        try:
            boom = _ast.parse(open(pad, encoding="utf-8").read())
        except (OSError, SyntaxError) as e:
            fouten.append(f"{pad} niet te ontleden: {str(e)[:60]}")
            continue
        for n in _ast.walk(boom):
            if not (isinstance(n, _ast.Call)
                    and isinstance(n.func, _ast.Attribute)
                    and n.func.attr == "replace" and len(n.args) == 2
                    and all(isinstance(a, _ast.Constant) for a in n.args)
                    and [a.value for a in n.args] == [",", "."]):
                continue
            v = n.func.value
            if isinstance(v, _ast.JoinedStr):
                tekst = "".join(x.value for x in v.values
                                if isinstance(x, _ast.Constant))
            elif isinstance(v, _ast.Constant) and isinstance(v.value, str):
                tekst = v.value
            else:
                continue
            if "," in tekst:
                fouten.append(f"{pad}:{n.lineno}: .replace(',', '.') op een "
                              f"tekst met een komma ({tekst[:40]!r}); gebruik "
                              f"getal.euro of getal.getal")
    return fouten


def stille_proef(paden=None):
    """
    Of een proef zijn bevindingen opnoemt NA de laatste die erbij komt.

    WAT HIER GEBEURDE, twee keer op 14 oktober, in twee bestanden. De vorm is
    altijd dezelfde:

        for f in fouten:
            print(f"FOUT {f}")
        ...
        fouten.append("...")          # staat eronder
        print(f"Proef: {len(fouten)} fouten")

    Een bevinding die onder de lus wordt toegevoegd, telt wel mee in het
    AANTAL en wordt nooit GETOOND. De proef meldt dan "1 afwijking" zonder te
    zeggen welke. Dat is bijna erger dan groen staan: de exitcode is rood, dus
    de poort werkt, maar er is geen aanknopingspunt.

    In pandgeschiedenis.py kostte dat vanmiddag een ronde zoeken, en in
    voorraad_bag.py vanavond nog een. Twee keer dezelfde vorm in twee
    bestanden is geen vergissing meer.

    HOE DIT WORDT GEMETEN. Per functie: welke lus loopt over een lijst en
    print daarin iets. Dat is de meldlus. Daarna: waar wordt op diezelfde
    lijst voor het laatst append of extend aangeroepen. Staat dat lager dan de
    lus, dan kan die bevinding niet getoond worden.

    DE PRINT IN DIE LUS IS HET KENMERK, en dat is nagemeten. Laat je die eis
    vallen en kijk je naar elke lus over een lijst, dan is de eerste treffer
    ontdubbel_huur() in marktprijzen_bag.py: een lus over behouden op regel
    4135 en een append op 4152. Daar is niets mis, want die lus meldt niets.
    Een toets die daarop afgaat, leert de lezer het verslag over te slaan.

    NAGEMETEN OP DE ECHTE FOUT: voorraad_bag.py zoals het vóór PR 101 op main
    stond geeft precies een treffer, de meldlus op regel 2240 met een append
    op 2287. Over alle modules van nu: nul.
    """
    import ast

    fouten = []
    paden = paden if paden is not None else sorted(
        n for n in os.listdir(".") if n.endswith(".py"))
    for pad in paden:
        try:
            with open(pad, encoding="utf-8") as f:
                boom = ast.parse(f.read(), filename=pad)
        except Exception as e:
            fouten.append(f"{pad} niet te ontleden: {str(e)[:60]}")
            continue
        for functie in ast.walk(boom):
            if not isinstance(functie, (ast.FunctionDef,
                                        ast.AsyncFunctionDef)):
                continue
            # De meldlussen: for <x> in <lijst>: ... print(...)
            meldlus = {}
            for knoop in ast.walk(functie):
                if not isinstance(knoop, ast.For):
                    continue
                if not isinstance(knoop.iter, ast.Name):
                    continue
                print_erin = any(
                    isinstance(k, ast.Call) and isinstance(k.func, ast.Name)
                    and k.func.id == "print" for k in ast.walk(knoop))
                if print_erin:
                    naam = knoop.iter.id
                    meldlus[naam] = min(meldlus.get(naam, knoop.lineno),
                                        knoop.lineno)
            if not meldlus:
                continue
            # De laatste keer dat er iets bij die lijst komt.
            laatste = {}
            for knoop in ast.walk(functie):
                if not isinstance(knoop, ast.Call):
                    continue
                f = knoop.func
                if not isinstance(f, ast.Attribute):
                    continue
                if f.attr not in ("append", "extend"):
                    continue
                if not isinstance(f.value, ast.Name):
                    continue
                naam = f.value.id
                if naam in meldlus:
                    laatste[naam] = max(laatste.get(naam, 0), knoop.lineno)
            for naam, regel in sorted(meldlus.items()):
                na = laatste.get(naam, 0)
                if na > regel:
                    fouten.append(
                        f"{pad}, {functie.name}(): de lus die {naam} opnoemt "
                        f"staat op regel {regel}, maar op regel {na} komt er "
                        f"nog iets bij. Die bevinding telt mee in het aantal "
                        f"en wordt nooit getoond: de proef meldt dan een "
                        f"aantal zonder te zeggen wat er mis is.")
    return fouten


def schaduw_over_import(paden=None):
    """
    Of een module die wordt geïmporteerd verderop door een eigen naam wordt
    overschreven.

    WAT HIER GEBEURDE. Op 13 oktober kwam kaartlink.py erbij, met de url van
    de kaartpagina. marktprijzen_bag.py kreeg bovenaan `import kaartlink`. Op
    regel 1126 van datzelfde bestand stond al duizend regels lang

        def kaartlink(adres, plaats="Nijmegen", bron=""):

    en vanaf daar is de naam kaartlink de functie. `kaartlink.link(...)` gaf
    dus AttributeError: 'function' object has no attribute 'link'. Dat sloeg
    render() af voordat er iets geschreven was, en de marktprijzen, de
    dossiers en de bijlage verdwenen in een keer uit de brief van 14 oktober.

    Python zegt hier niets over: een naam opnieuw binden is geen fout. De
    toets kijkt per bestand naar de namen die worden geïmporteerd en naar de
    namen die op modulehoogte worden gedefinieerd of toegekend, en meldt de
    doorsnede.

    ALLEEN OP MODULEHOOGTE. Een lokale variabele in een functie die net zo
    heet als een import is lelijk maar niet stuk: die schaduw eindigt bij de
    functie. Deze fout gaat erom dat de module zelf de naam kwijt is.
    """
    import ast

    fouten = []
    paden = paden if paden is not None else sorted(
        n for n in os.listdir(".") if n.endswith(".py"))
    for pad in paden:
        try:
            with open(pad, encoding="utf-8") as f:
                boom = ast.parse(f.read(), filename=pad)
        except Exception as e:
            fouten.append(f"{pad} niet te ontleden: {str(e)[:60]}")
            continue
        ingevoerd, eigen = {}, {}
        for knoop in ast.walk(boom):
            # Een import kan ook binnen een functie staan; die telt mee, want
            # hij bindt de naam daar en de botsing is dezelfde.
            if isinstance(knoop, ast.Import):
                for alias in knoop.names:
                    naam = alias.asname or alias.name.split(".")[0]
                    ingevoerd.setdefault(naam, knoop.lineno)
        for knoop in boom.body:
            if isinstance(knoop, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef)):
                eigen.setdefault(knoop.name, knoop.lineno)
            elif isinstance(knoop, ast.Assign):
                for doel in knoop.targets:
                    if isinstance(doel, ast.Name):
                        eigen.setdefault(doel.id, knoop.lineno)
        for naam in sorted(set(ingevoerd) & set(eigen)):
            fouten.append(
                f"{pad}: 'import {naam}' op regel {ingevoerd[naam]} wordt op "
                f"regel {eigen[naam]} overschreven door een eigen {naam}. "
                f"Vanaf daar geeft {naam}.<iets> AttributeError, en python "
                f"waarschuwt daar niet voor.")
    return fouten


def fout_zonder_spoor(paden=None):
    """
    Of een stap die zijn eigen mislukking opvangt, daar een spoor van laat.

    WAT HIER GEBEURDE. Op 14 oktober mislukte de marktprijzenstap. De regel
    eindigde op

        || echo "Marktprijzen-stap overgeslagen"

    en daarmee is de exitcode nul: de stap stond groen, de run was groen, en
    de marktprijzen, de dossiers en de bijlage ontbraken in de brief. Mark
    ontdekte het doordat de bekendmakingen in zijn brief twee keer voorkwamen,
    een keer onder de kop "Bijlage: de cijfers".

    EEN OPGEVANGEN FOUT MAG, EEN STILLE NIET. De brief hoeft niet te stoppen
    omdat de bouwkostenindex niet ververst is. Maar wat niet is gelukt, moet
    ergens staan waar wij het kunnen lezen, en dat is niet het joblogboek van
    GitHub: dat zit achter results-receiver.actions.githubusercontent.com,
    die van buiten de runner wordt geweigerd. Daarom schrijft elke stap die
    zijn fout opvangt de naam in overgeslagen.txt, en leest gezondheid.py die
    lijst.

    De toets kijkt naar een venster van zeven regels, want de vorm met
    "if ! python ... ; then" zet het echo-blok een paar regels lager.
    """
    # Alleen een opvang die een MISLUKKING benoemt. "|| echo 0" is een
    # standaardwaarde en geen opgevangen fout; die meerekenen zou de toets
    # laten afgaan op correct gedrag.
    OPVANG = re.compile(r'\|\|\s*(\{\s*)?echo\s+"[^"]*'
                        r'(overgeslagen|mislukt|niet gelukt|kon niet)')
    VENSTER = 7
    fouten = []
    paden = paden if paden is not None else _alle_workflows()
    if not paden:
        return ["geen workflowbestand gevonden om de opgevangen fouten "
                "te toetsen"]
    for pad in paden:
        try:
            with open(pad, encoding="utf-8") as f:
                regels = f.read().splitlines()
        except Exception as e:
            fouten.append(f"{pad} niet te lezen: {str(e)[:50]}")
            continue
        for i, regel in enumerate(regels):
            if regel.strip().startswith("#"):
                continue
            if not OPVANG.search(regel):
                continue
            venster = "\n".join(regels[i:i + VENSTER])
            if "overgeslagen.txt" in venster:
                continue
            fouten.append(f"{pad}, regel {i + 1}: vangt de fout op zonder "
                           "hem ergens neer te zetten. Voeg "
                           '\'echo "<naam>" >> "$GITHUB_WORKSPACE/'
                           "overgeslagen.txt\"' toe, anders is de mislukking "
                           "alleen in het joblogboek te zien en dat is van "
                           "buiten de runner niet te lezen.")
    return fouten


def _achtergrond():
    """De kennisblokken uit bronnen.py, met hun trefwoorden en hun bron."""
    import importlib.util
    try:
        spec = importlib.util.spec_from_file_location("_br", "bronnen.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return (list(m.ACHTERGROND), dict(m.ACHTERGROND_TREFWOORDEN),
                dict(m.ACHTERGROND_BRONNEN))
    except Exception:
        return ([], {}, {})


def kennis_compleet():
    """
    Of elk kennisblok trefwoorden en een bron heeft.

    WAT HIER GEBEURDE. Op 13 oktober zocht ik een parkeerregel op het web,
    schreef hem op als nieuwe vondst, en pas toen Mark vroeg of de bron in de
    repo stond bleek het blok "Parkeren bij splitsen" er al jaren te staan,
    beter opgeschreven dan mijn versie. Ik had niet gezocht.

    Bij het nazoeken bleek iets scherpers: alle 36 blokken hadden
    trefwoorden, maar zeven hadden geen bron, en dat waren precies de zeven
    nieuwste, over splitsen en vergunningen. Kennis die erin is gezet zonder
    het dossier af te maken. Niets mat dat na, dus het viel niet op.

    Zonder bron is niet te zien waarop een regel rust en dus ook niet wanneer
    hij veroudert: worden de Beleidsregels Parkeren herzien, dan moet te
    vinden zijn welke blokken daarop leunen.
    """
    fouten = []
    blokken, trefwoorden, bronnen = _achtergrond()
    if not blokken:
        return ["de kennisblokken uit bronnen.py zijn niet te lezen"]
    for titel, *_rest in blokken:
        if not trefwoorden.get(titel):
            fouten.append(f"kennisblok {titel[:50]!r} heeft geen trefwoorden; "
                          f"dan is hij alleen te vinden door wie al weet dat "
                          f"hij bestaat")
        if not (bronnen.get(titel) or "").strip():
            fouten.append(f"kennisblok {titel[:50]!r} heeft geen bron; dan is "
                          f"niet te zien waarop hij rust en wanneer hij "
                          f"veroudert")
    return fouten


# Wat een regel herkenbaar maakt: de naam van een regeling met een jaartal,
# of een getal met een eenheid erachter. Losse woorden niet: "parkeren" komt
# overal voor en zegt niets over dubbeling.
RE_REGELING = re.compile(
    r"\b((?:Beleidsregels?|Huisvestingsverordening|Uitwerkingsnota|"
    r"Omgevingswet|Besluit bouwwerken leefomgeving|Wet [a-z ]{3,30})"
    r"[A-Za-z ]{0,30}?\s?20\d\d)")
# ALLEEN EEN MAAT MET EEN ONDERWERP ERAAN VAST.
#
# Eerst stond hier ook de kale vorm "55 procent" en "500 m2". Nagemeten gaf
# dat een valse treffer: de 55 procent in het blok over gemeubileerd verhuren
# gaat over iets heel anders dan de 55 procent verblijfsgebied bij een
# woonruimte. Een kaal getal komt overal voor en zou elke dag melden bij
# correct gedrag, en dat leert de lezer de melding over te slaan.
#
# "0,70 per woning" is wel onderscheidend, want daar zit het onderwerp in.
RE_MAATREGEL = re.compile(r"\b(\d,\d{1,2} per (?:woning|wooneenheid|kamer))")


def _kenmerken(tekst):
    """De herkenbare brokjes uit een tekst: regelingen en maten."""
    t = tekst or ""
    uit = set()
    for m in RE_REGELING.finditer(t):
        uit.add(re.sub(r"\s+", " ", m.group(1)).strip().lower())
    for m in RE_MAATREGEL.finditer(t):
        uit.add(re.sub(r"\s+", " ", m.group(1)).strip().lower())
    return uit


def dubbele_kennis(extra=None):
    """
    Of dezelfde regel op twee plaatsen staat.

    WAAROM DIT BESTAAT. Op 13 oktober schreef ik de parkeerregel in
    vergunningsmaten.json terwijl hij al in bronnen.py stond. Twee plaatsen
    met dezelfde regel lopen uit elkaar zodra er een wordt bijgewerkt, en dan
    weet niemand welke geldt. Niets merkte het; Mark vroeg ernaar.

    Dit is het enige voorstel uit dat gesprek dat niet afhangt van mijn
    geheugen, en daarom staat het hier en niet in een voornemen.

    Het vergelijkt geen losse woorden maar herkenbare brokjes: de naam van
    een regeling met een jaartal, of een maat met een eenheid. "Parkeren"
    komt overal voor en zou alles melden.
    """
    import json as _json
    fouten = []
    blokken, _tw, _br = _achtergrond()
    kennis = {}
    for titel, *rest in blokken:
        for k in _kenmerken(" ".join(str(r) for r in rest)):
            kennis.setdefault(k, []).append(f"bronnen.py: {titel[:40]}")
    anders = extra
    if anders is None:
        try:
            with open("vergunningsmaten.json", encoding="utf-8") as f:
                d = _json.load(f)
            anders = {"vergunningsmaten.json": _json.dumps(
                d.get("regels") or [], ensure_ascii=False)}
        except Exception:
            anders = {}
    for naam, tekst in (anders or {}).items():
        for k in _kenmerken(tekst):
            if k in kennis:
                fouten.append(f"{k!r} staat zowel in {kennis[k][0]} als in "
                              f"{naam}. Twee plaatsen met dezelfde regel "
                              f"lopen uit elkaar zodra er een wordt "
                              f"bijgewerkt.")
    return fouten


def startdagen(pad=BRIEFWORKFLOW):
    """
    Voor welke weekdagen de briefworkflow een geplande start heeft.

    Levert (per_dag, crons, fout): per_dag is een dict 0 t/m 6 met het aantal
    crons dat op die dag vuurt, crons het aantal gelezen cronregels, en fout
    een reden als het bestand niet te lezen was.

    WAAROM DIT HIER STAAT EN NIET IN HET GEZONDHEIDSRAPPORT. Een ontbrekende
    dag hoort de poort tegen te houden en niet alleen in de bijlage te staan.
    Zaterdag stond niet in de cron en niet in de geplande taak die de run van
    buitenaf start; de brief van 3 en 10 oktober bestond dus alleen omdat er
    iemand keek. Dat was aan niets te zien, want de digests-map had voor elke
    dag een brief.

    WAT DIT NIET MEET. Niet of de brief op tijd komt. De cron van GitHub vuurt
    op deze repo uren te laat, en de start die hem wel op tijd brengt komt van
    een geplande taak buiten de repo, die dit programma niet kan zien. Dit
    meet de terugval die in de repo zelf vastligt.
    """
    per_dag = {d: 0 for d in range(7)}
    try:
        with open(pad, encoding="utf-8") as f:
            regels = f.read().splitlines()
    except Exception as e:
        return (per_dag, 0, f"{pad} niet te lezen: {str(e)[:60]}")
    crons = 0
    for regel in regels:
        kaal = regel.strip()
        if not kaal.startswith("- cron:"):
            continue
        # EERST HET COMMENTAAR, DAN DE AANHALINGSTEKENS. Andersom haalt strip
        # alleen het aanhalingsteken aan de voorkant weg, want achteraan staat
        # het commentaar; dan blijft het laatste veld '1-6"' en leest geen
        # enkele dag. De controle meldde zo zeven ongedekte dagen terwijl er
        # drie crons stonden.
        waarde = kaal.split(":", 1)[1].split("#", 1)[0].strip()
        velden = waarde.strip('"').strip("'").strip().split()
        if len(velden) != 5:
            continue
        crons += 1
        for d in _crondagen(velden[4]):
            per_dag[d] += 1
    return (per_dag, crons, "")


def proef(snel=False):
    """
    Nameten of de eisen werkelijk gehandhaafd worden.

    snel=True slaat het draaien van de verwezen proeven over. Dat is er voor
    de poort in de workflow, waar die proeven toch al apart draaien; zonder
    snel duurt dit een paar seconden omdat elke verwezen module opnieuw wordt
    gestart.
    """
    eisen, fouten = lees()
    if not eisen:
        fouten.append("geen enkele eis gelezen")

    heeft = [e for e in eisen if (e.get("proef") or "-") != "-"]
    deels = [e for e in heeft if (e.get("deels") or "").lower() == "ja"]
    met_proef = [e for e in heeft if e not in deels]
    zonder = [e for e in eisen if (e.get("proef") or "-") == "-"]
    # Een eis die als deels is gemarkeerd moet zeggen waarom, net als een eis
    # zonder proef. Anders leest "deels" als een slag om de arm.
    for e in deels:
        if not e.get("let op"):
            fouten.append(f"eis met deels: ja maar zonder uitleg: "
                          f"{e['eis'][:60]}")

    # Een eis zonder proef moet uitleggen waarom, anders leest "-" als
    # vergeten in plaats van als bewuste keuze.
    for e in zonder:
        if not e.get("let op"):
            fouten.append(f"eis zonder proef en zonder uitleg: "
                          f"{e['eis'][:60]}")

    beschikbaar = set(_modules_met_proef())
    gedraaid = {}
    for e in heeft:
        # EEN EIS MAG OP MEER DAN EEN PLEK WORDEN AFGEDWONGEN, gescheiden
        # door een puntkomma. Dat is er omdat de eis over het leesbare kanaal
        # op twee plaatsen bleek te gelden: in de brief en in een verkenning.
        # Een tweede veld ernaast zou hetzelfde ding twee namen geven, en dan
        # kijkt de controle maar naar een van de twee.
        for verwijzing in e["proef"].split(";"):
            module, _, label = verwijzing.partition(":")
            module, label = module.strip(), label.strip()
            if not module:
                continue
            if module == "eisen":
                # Naar onszelf verwijzen mag, maar het label moet dan wel in
                # dit bestand staan: anders verdwijnt een controle hier
                # zonder dat de eis het merkt.
                if label and label not in (_bron("eisen") or ""):
                    fouten.append(f"de controle {label!r} staat niet in "
                                  f"eisen.py: {e['eis'][:50]}")
                continue
            if module not in beschikbaar:
                fouten.append(f"eis verwijst naar {module!r}, maar dat heeft "
                              f"geen --proef: {e['eis'][:50]}")
                continue
            bron = _bron(module)
            if label and label not in (bron or ""):
                fouten.append(f"de controle {label!r} staat niet in "
                              f"{module}.py; omgedoopt of weggehaald? Eis: "
                              f"{e['eis'][:50]}")
            if snel or module in gedraaid:
                continue
            r = subprocess.run([sys.executable, f"{module}.py"] + _vlag(module),
                               capture_output=True, text=True, timeout=600)
            gedraaid[module] = r.returncode
            if r.returncode != 0:
                laatste = (r.stderr or "").strip().splitlines()
                fouten.append(f"{module} --proef staat rood ({r.returncode}): "
                              f"{laatste[-1][:80] if laatste else 'geen uitvoer'}")

    # EISEN DIE DIT BESTAND ZELF HANDHAAFT.
    #
    # elke proef eindigt op sys.exit.
    #
    # Elke module met een --proef moet op sys.exit eindigen. Zonder dat geeft
    # het proces exitcode 0, ook als de proef rood staat, en dan is de poort
    # in de workflow een formaliteit. Dit geldt voor alle modules met een
    # proef en niet alleen voor die waar een eis naar verwijst, want een
    # stille poort is overal even stil.
    for module in sorted(beschikbaar):
        reden = _eindigt_op_sys_exit(_bron(module))
        if reden:
            fouten.append(f"{module}.py heeft een --proef maar eindigt niet op "
                          f"sys.exit: {reden}. De exitcode is dan altijd 0.")

    # Een run die gegevens terugschrijft mag geen broncode veranderen. Zie
    # commitstap() voor wat dat op 13 oktober kostte.
    fouten.extend(commitstap())

    # Een stap die zijn eigen fout opvangt, laat daar een spoor van. Zie
    # fout_zonder_spoor() voor de brief die op 14 oktober een heel onderdeel
    # miste zonder dat iets rood stond.
    fouten.extend(fout_zonder_spoor())

    # Een geïmporteerde module mag niet door een eigen naam worden
    # overschreven. Zie schaduw_over_import(): dat was de oorzaak onder die
    # brief.
    fouten.extend(schaduw_over_import())

    # Een proef noemt zijn bevindingen op NA de laatste die erbij komt. Zie
    # stille_proef(): twee keer op 14 oktober meldde een proef een aantal
    # zonder te zeggen wat er mis was.
    fouten.extend(stille_proef())

    # Geen komma's in een zin wegvervangen; zie komma_vervanging(). En de
    # toets moet de vorm zien die op 20 oktober in de brief stond.
    fouten.extend(komma_vervanging())
    import tempfile as _tf4
    with _tf4.TemporaryDirectory() as _m4:
        _k = os.path.join(_m4, "k.py")
        with open(_k, "w", encoding="utf-8") as _f4:
            _f4.write('x = 1\ny = (f"premie {x} voor die klasse, dus "\n'
                      '     f"€{x:,}".replace(",", "."))\n'
                      'z = f"€{x:,}".replace(",", ".")\n')
        _gevonden = komma_vervanging([_k])
        if len(_gevonden) != 1:
            fouten.append(f"komma_vervanging ziet de vorm uit de brief niet, "
                          f"of meldt ook de goede vorm: {_gevonden}")

    # EN DIE TOETS MOET DE ECHTE VORM ZIEN. Nagemeten op voorraad_bag.py zoals
    # het op main stond vóór PR 101: precies een treffer, de meldlus op regel
    # 2240 met een append op 2287. Hier staat dezelfde vorm na, plus de goede
    # vorm, want een toets die alleen de fout kent meldt straks ook elke
    # correcte proef.
    import tempfile as _tf3
    with _tf3.TemporaryDirectory() as _m3:
        _slecht = os.path.join(_m3, "slecht.py")
        with open(_slecht, "w", encoding="utf-8") as _f3:
            _f3.write("def proef():\n"
                      "    fouten = []\n"
                      "    if 1:\n"
                      "        fouten.append('eerste')\n"
                      "    for f in fouten:\n"
                      "        print(f)\n"
                      "    if 2:\n"
                      "        fouten.append('deze wordt nooit getoond')\n"
                      "    print(len(fouten))\n"
                      "    return 1 if fouten else 0\n")
        if not stille_proef([_slecht]):
            fouten.append("een proef die bevindingen toevoegt na de lus die "
                          "ze opnoemt, wordt niet gemeld; dan meldt een proef "
                          "een aantal zonder te zeggen wat er mis is")
        _goed = os.path.join(_m3, "goed.py")
        with open(_goed, "w", encoding="utf-8") as _f3:
            _f3.write("def proef():\n"
                      "    fouten = []\n"
                      "    if 1:\n"
                      "        fouten.append('eerste')\n"
                      "    if 2:\n"
                      "        fouten.append('tweede')\n"
                      "    for f in fouten:\n"
                      "        print(f)\n"
                      "    print(len(fouten))\n"
                      "    return 1 if fouten else 0\n")
        _uit3 = stille_proef([_goed])
        if _uit3:
            fouten.append(f"een proef die alles vóór de lus toevoegt wordt "
                          f"toch gemeld: {_uit3[0][:90]}")
        # En een lus die over iets anders print mag niet voor meldlus
        # doorgaan: anders gaat deze toets af op elke functie die een lijst
        # afdrukt en daarna een andere lijst vult.
        _ander = os.path.join(_m3, "ander.py")
        with open(_ander, "w", encoding="utf-8") as _f3:
            _f3.write("def doe():\n"
                      "    regels = ['a']\n"
                      "    fouten = []\n"
                      "    for r in regels:\n"
                      "        print(r)\n"
                      "    fouten.append('hoort niet bij die lus')\n"
                      "    return fouten\n")
        _uit3 = stille_proef([_ander])
        if _uit3:
            fouten.append(f"een lus over een andere lijst wordt als meldlus "
                          f"gelezen: {_uit3[0][:90]}")

    # EN DE TOETS MOET DE ECHTE FOUT KUNNEN ZIEN. Dit is de vorm zoals hij in
    # marktprijzen_bag.py stond: een import bovenaan, duizend regels lager een
    # functie met dezelfde naam. Nagemeten op het echte bestand van main gaf
    # dit precies een treffer.
    import tempfile as _tf2
    with _tf2.TemporaryDirectory() as _m2:
        _p2 = os.path.join(_m2, "nagemaakt.py")
        with open(_p2, "w", encoding="utf-8") as _f2:
            _f2.write("import kaartlink\n\n\n"
                      "def kaartlink(adres):\n    return adres\n\n\n"
                      "def gebruik():\n"
                      "    return kaartlink.link('tekst', 'pagina')\n")
        if not schaduw_over_import([_p2]):
            fouten.append("een import die door een eigen functie wordt "
                          "overschreven wordt niet gemeld; dat was de oorzaak "
                          "van de brief zonder marktprijzen op 14 oktober")
        # En een import die NIET wordt overschreven mag niet melden.
        with open(_p2, "w", encoding="utf-8") as _f2:
            _f2.write("import kaartlink\n\n\n"
                      "def adreslink(adres):\n    return adres\n\n\n"
                      "def gebruik():\n"
                      "    kaartlink = 'lokaal, eindigt hier'\n"
                      "    return kaartlink\n")
        _uit = schaduw_over_import([_p2])
        if _uit:
            fouten.append(f"een lokale naam in een functie wordt als schaduw "
                          f"over de import gemeld: {_uit[0][:80]}")

    # Elke workflow moet zijn uitkomst neerzetten waar wij hem kunnen lezen.
    # Zie leesbaar_kanaal() voor de verkenning die groen en onleesbaar
    # tegelijk was.
    fouten.extend(leesbaar_kanaal())

    # Een kaartlink die stil wegvalt leest als een keuze. Zie
    # kaartschakelaar().
    # Niet in deze repo: de kaartschakelaar hoort bij de brief.

    # COMMENTAAR MAG DE TOETS NIET GROEN MAKEN. Het blok hieronder noemt
    # pipefail wel in de uitleg en zet het niet aan. Zonder dit geval zou
    # een stap die de fout keurig uitlegt en hem laat staan, erdoorheen
    # glippen, en dat is precies hoe de uitleg van een fout die fout
    # verbergt.
    import tempfile as _tf
    with _tf.TemporaryDirectory() as _m:
        _p = os.path.join(_m, "nep.yml")
        with open(_p, "w", encoding="utf-8") as _f:
            _f.write("jobs:\n  x:\n    steps:\n"
                     "      - name: Zonder vangnet\n"
                     "        run: |\n"
                     "          # hier hoort set -o pipefail te staan\n"
                     "          python iets.py 2>&1 | tee /tmp/log\n")
        _r = pijp_zonder_vangnet([_p])
        if len(_r) != 1:
            fouten.append(f"een stap die pipefail alleen in commentaar noemt "
                          f"wordt niet gemeld: {_r}")
        _p2 = os.path.join(_m, "goed.yml")
        with open(_p2, "w", encoding="utf-8") as _f:
            _f.write("jobs:\n  x:\n    steps:\n"
                     "      - name: Met vangnet\n"
                     "        run: |\n"
                     "          set -o pipefail\n"
                     "          python iets.py 2>&1 | tee /tmp/log\n")
        if pijp_zonder_vangnet([_p2]):
            fouten.append("een stap met pipefail wordt ten onrechte gemeld")
        _p3 = os.path.join(_m, "tonen.yml")
        with open(_p3, "w", encoding="utf-8") as _f:
            _f.write("jobs:\n  x:\n    steps:\n"
                     "      - name: Iets tonen\n"
                     "        run: |\n"
                     "          grep -E Versies rapport.md | head -3\n")
        if pijp_zonder_vangnet([_p3]):
            fouten.append("een grep die iets toont wordt ten onrechte "
                          "gemeld; een grep zonder treffer is daar geen fout")

    # Een stap die zijn uitvoer door een pijp stuurt, verliest de exitcode
    # van wat ervoor stond. Zie pijp_zonder_vangnet() voor wat dat kostte.
    fouten.extend(pijp_zonder_vangnet())

    # Elk kennisblok hoort trefwoorden en een bron te hebben, en dezelfde
    # regel hoort niet op twee plaatsen te staan. Zie kennis_compleet() en
    # dubbele_kennis() voor wat dat op 13 oktober kostte.
    # Niet in deze repo: bronnen.py en zijn kennisblokken staan in de brief.

    # Elke dag van de week moet een geplande start van de brief hebben. Een
    # dag zonder cron heeft geen terugval, en dat valt pas op als niemand
    # kijkt. Zie startdagen() voor wat dit wel en niet meet.
    per_dag, crons, fout = startdagen()
    if fout:
        fouten.append(f"de startdagen niet na te meten: {fout}")
    elif not crons:
        fouten.append(f"geen enkele cron in {BRIEFWORKFLOW}; dan hangt de "
                      f"brief volledig aan de geplande taak buiten de repo")
    else:
        kaal = [DAGNAMEN[d] for d in range(7) if not per_dag[d]]
        if kaal:
            fouten.append(f"zonder geplande start: {', '.join(kaal)}. Op die "
                          f"dag komt de brief alleen als iemand hem met de "
                          f"hand start.")

    print(f"Eisen: {len(eisen)} gelezen, {len(met_proef)} afgedwongen, "
          f"{len(deels)} deels, {len(zonder)} bewust zonder, "
          f"{len(beschikbaar)} modules met een proef nagekeken op hun "
          f"exitcode" + ("" if snel else f", {len(gedraaid)} gedraaid"),
          file=sys.stderr)
    for f in fouten:
        print(f"FOUT {f}", file=sys.stderr)
    print(f"Proef: {len(fouten)} fouten", file=sys.stderr)
    return 1 if fouten else 0


def tekst(pad=PAD):
    """Een blok voor de bijlage: wat we eisen en wat daarvan vastligt."""
    eisen, _f = lees(pad)
    if not eisen:
        return ""
    heeft = [e for e in eisen if (e.get("proef") or "-") != "-"]
    deelt = [e for e in heeft if (e.get("deels") or "").lower() == "ja"]
    met = [e for e in heeft if e not in deelt]
    zonder = [e for e in eisen if (e.get("proef") or "-") == "-"]
    r = ["## Wat de brief moet doen, en wat daarvan vastligt", ""]
    r.append(f"_{len(eisen)} eisen. {len(met)} worden volledig afgedwongen "
             f"door een proef die bij elke run draait, {len(deelt)} deels, en "
             f"{len(zonder)} niet. Die laatste twee groepen staan er met de "
             f"reden waarom ze niet verder te handhaven zijn; dat verschil "
             f"hoort zichtbaar te zijn in plaats van impliciet._")
    r.append("")
    for soort, kop in (("brief", "Over de brief"),
                       ("gegevens", "Over de gegevens"),
                       ("werking", "Over de werking")):
        groep = [e for e in eisen if (e.get("soort") or "") == soort]
        if not groep:
            continue
        r.append(f"### {kop}")
        r.append("")
        for e in groep:
            if (e.get("proef") or "-") == "-":
                kop = "**Niet afgedwongen.**"
            elif (e.get("deels") or "").lower() == "ja":
                kop = "**Deels vastgelegd.**"
            else:
                kop = "**Vastgelegd.**"
            r.append(f"- {kop} {e['eis']}")
        r.append("")
    return "\n".join(r)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--proef", action="store_true",
                    help="Nameten of de eisen gehandhaafd worden.")
    ap.add_argument("--snel", action="store_true",
                    help="Bij --proef: de verwezen proeven niet draaien.")
    ap.add_argument("--tekst", default="",
                    help="Het blok voor de bijlage hierheen schrijven.")
    a = ap.parse_args()
    if a.proef:
        return proef(snel=a.snel)
    if a.tekst:
        blok = tekst()
        if blok:
            with open(a.tekst, "w", encoding="utf-8") as f:
                f.write(blok)
        eisen, _f = lees()
        print(f"Eisen: {len(eisen)} naar {a.tekst}", file=sys.stderr)
        return 0
    print(tekst())
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
