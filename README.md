# nijmegen-marktdata

Openbare gegevens over de woningvoorraad van Nijmegen, automatisch opgehaald:
oppervlakte en gebruiksdoel uit de BAG, energielabels uit EP-Online,
parkeerzones van de gemeente en de postcodes van de ringbuurten.

Alles in deze repo komt uit een openbare bron. Er staat niets in over eigen
panden, kosten of plannen; die gegevens staan in een privé repo.

## Wat er draait

| Workflow | Wanneer | Wat |
|---|---|---|
| `voorraad.yml` | elke dag 04:40 UTC, en met de hand | BAG, energielabels, parkeerzones, buurtinventaris → `voorraad.json` |
| `proeven.yml` | bij elke push en PR | `python eisen.py --proef` |

Nodig als repo-secrets: `BAG_API_KEY` (Kadaster) en `EP_API_KEY` (RVO EP-Online).

## Gegevens

| Bestand | Inhoud |
|---|---|
| `voorraad.json` | woningen en niet-woningen per adres, met oppervlakte, gebruiksdoel, pand en label |
| `voorraad_stand.json` | verslag van de laatste ronde |
| `buurtinventaris.json` | postcodes per ringbuurt |
| `parkeerzones.json` | parkeerzones per pand |
| `eponline_antwoordvorm.json` | vastgelegde echte antwoorden van EP-Online, voor de proef |

Bronnen: Kadaster BAG, RVO EP-Online, gemeente Nijmegen, PDOK. Zie de docstrings
van de modules voor de voorwaarden per bron.
