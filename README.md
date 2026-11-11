# nijmegen-marktdata

Openbare gegevens over Nijmegen, automatisch opgehaald: de officiële
bekendmakingen van de gemeente, oppervlakte en gebruiksdoel uit de BAG,
energielabels uit EP-Online, parkeerzones en de postcodes van de ringbuurten.

Alles in deze repo komt uit een openbare bron. Er staat niets in over eigen
panden, kosten of plannen; die gegevens staan in een privé repo.

## Wat er draait

| Workflow | Wanneer | Wat |
|---|---|---|
| `voorraad.yml` | elke dag 04:40 UTC, en met de hand | BAG, energielabels, parkeerzones, buurtinventaris → `voorraad.json` |
| `publicaties.yml` | 01:37, 07:37, 13:37 en 19:37 UTC, en met de hand | alle bekendmakingen van Nijmegen → `bekendmakingen_recent.json`, `bekendmakingen_archief.json` |
| `cijfers.yml` | elke dag 01:07 UTC, en met de hand | CBS en Kadaster → woningprijsindex, COROP, bouwkostenindex, misdrijven per buurt |
| `inhaal-3dbag.yml` | gestart door de voorraadronde als er panden zonder 3D BAG zijn | hoogtes, oppervlakken en bouwlagen → `bag3d.json` |
| `proeven.yml` | bij elke push en PR | `python eisen.py --proef` |

Nodig als repo-secrets: `BAG_API_KEY` (Kadaster) en `EP_API_KEY` (RVO EP-Online).

## Gegevens

| Bestand | Inhoud |
|---|---|
| `bekendmakingen_recent.json` | alle bekendmakingen van de gemeente van de laatste 30 dagen, met tijdstip van ophalen |
| `bekendmakingen_archief.json` | per adres de bekendmakingen over gebruik, verbouwing en handhaving, sinds 2012 |
| `woningprijsindex.json`, `corop_prijzen.json`, `bouwkosten_index.json`, `misdrijven_per_buurt.json` | cijfers van CBS en Kadaster |
| `diagnose/*.txt` | wat er bij het ophalen misging, als dat zo is |
| `bag3d.json` | 3D BAG per pand voor de ring en de adressen met een bekendmaking (TU Delft en 3DGI, CC BY 4.0) |
| `voorraad.json` | woningen en niet-woningen per adres, met oppervlakte, gebruiksdoel, pand en label |
| `voorraad_stand.json` | verslag van de laatste ronde |
| `buurtinventaris.json` | postcodes per ringbuurt |
| `parkeerzones.json` | parkeerzones per pand |
| `eponline_antwoordvorm.json` | vastgelegde echte antwoorden van EP-Online, voor de proef |

Bronnen: officiële bekendmakingen (overheid.nl), CBS, Kadaster BAG, RVO EP-Online, gemeente Nijmegen, PDOK. Zie de docstrings
van de modules voor de voorwaarden per bron.
