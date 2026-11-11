"""
Diagnose vastleggen voor het gezondheidsrapport.

Een script dat iets niet voor elkaar krijgt, schrijft hier op wat het zag: welke
velden er waren, welke foutmelding kwam, hoeveel er wel lukte. Het rapport neemt
dat letterlijk over. Zo staat de oorzaak in het rapport, en hoeft niemand in de
logs te zoeken of te raden.

Gebruik:
    from diagnose import leg_vast, wis
    wis("bouwkosten")                        # aan het begin: oude diagnose weg
    leg_vast("bouwkosten", "CBS gaf 404")    # bij een probleem
"""

import os

MAP = "diagnose"


def _pad(onderdeel):
    return os.path.join(MAP, f"{onderdeel}.txt")


def wis(onderdeel):
    """Een oude diagnose weghalen, zodat een opgelost probleem niet blijft staan."""
    try:
        os.remove(_pad(onderdeel))
    except FileNotFoundError:
        pass
    except Exception:
        pass


def alleen_lezen():
    """
    Draait dit een testrun?

    Bij een handmatige run met "alleen naar mij" mag niets worden afgestreept
    wat de echte brief van morgen nodig heeft: gelezen artikelen, het weetje van
    de dag, het achtergrondstuk. Anders verdwijnt het nieuws in een testrun.
    """
    return os.environ.get("GEHEUGEN_ALLEEN_LEZEN") == "1"


def leg_vast(onderdeel, tekst):
    """Een regel diagnose toevoegen. Mag meerdere keren per run."""
    try:
        os.makedirs(MAP, exist_ok=True)
        with open(_pad(onderdeel), "a", encoding="utf-8") as f:
            f.write(str(tekst).strip() + "\n")
    except Exception:
        pass
