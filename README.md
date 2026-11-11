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
| `cijfers.yml` | elke dag 01:07 UTC, en met de hand | CBS, Kadaster, PDOK, gemeente en OpenStreetMap → woningprijsindex, COROP, bouwkostenindex, misdrijven en vergunningen per buurt, buurtcijfers, begroting, ov-haltes |
| `inhaal-3dbag.yml` | gestart door de voorraadronde als er panden zonder 3D BAG zijn | hoogtes, oppervlakken en bouwlagen → `bag3d.json` |
| `bestemming.yml` | met de hand | bestemmingen per pand (PDOK) → `bestemmingen.json` |
| `gezicht.yml` | maandag, en met de hand | beschermde gezichten, monumenten, stadsbeeld (PDOK, RCE, gemeente) |
| `publicatievelden.yml` | elke dag | velden uit de tekst van bekendmakingen → `publicatie_velden.json` |
| `regelgeving.yml` | zondag 00:05 UTC, en met de hand | verordeningen en wetten volgen → `regelgeving_status.json`, `regelgeving_meldingen.json` |
| `proeven.yml` | bij elke push en PR | `python eisen.py --proef` |

Nodig als repo-secrets: `BAG_API_KEY` (Kadaster) en `EP_API_KEY` (RVO EP-Online).

## Gegevens

| Bestand | Inhoud |
|---|---|
| `bekendmakingen_recent.json` | alle bekendmakingen van de gemeente van de laatste 30 dagen, met tijdstip van ophalen |
| `bekendmakingen_archief.json` | per adres de bekendmakingen over gebruik, verbouwing en handhaving, sinds 2012 |
| `woningprijsindex.json`, `corop_prijzen.json`, `bouwkosten_index.json`, `misdrijven_per_buurt.json` | cijfers van CBS en Kadaster |
| `kamervergunningen.json` | de vergunningenlijst kamerverhuur van de gemeente Nijmegen, per adres (zaaknummer, soort, datum) |
| `vergunningen_per_buurt.json`, `straat_buurt_cache.json` | vergunningen per buurt, en de buurt per straat volgens PDOK |
| `kamerverhuur_objecten.json`, `kamerverhuur_per_buurt.json` | bekende kamerverhuurpanden: vergunningen plus meldingen brandveilig gebruik en besluiten uit het archief; een ondergrens |
| `gezichten.json`, `monumenten_*`, `rijksmonumenten_*`, `omgevingsplan_gio*`, `stadsbeeld_*` | erfgoed en beschermde gezichten per pand |
| `bestemmingen.json` | bestemmingen per pand |
| `publicatie_velden.json` | velden uit bekendmakingen: zaaknummer, uitkomst, aantallen |
| `buurten_cbs.json` | cijfers per ringbuurt uit de CBS Wijk- en Buurtkaart |
| `begroting_nijmegen.json`, `begroting_meldingen.json` | tarieven en nieuwe regels uit de stadsbegroting |
| `ov_haltes.json` | ov-haltes in en rond Nijmegen (OpenStreetMap) |
| `huurtabellen.json` | maximale kale huur per punt, zelfstandig (WWS) en onzelfstandig (WWSO), per jaar; lees met `huurtabel.py` |
| `diagnose/*.txt` | wat er bij het ophalen misging, als dat zo is |
| `bag3d.json` | 3D BAG per pand voor de ring en de adressen met een bekendmaking (TU Delft en 3DGI, CC BY 4.0) |
| `voorraad.json` | woningen en niet-woningen per adres, met oppervlakte, gebruiksdoel, pand en label |
| `voorraad_stand.json` | verslag van de laatste ronde |
| `buurtinventaris.json` | postcodes per ringbuurt |
| `parkeerzones.json` | parkeerzones per pand |
| `eponline_antwoordvorm.json` | vastgelegde echte antwoorden van EP-Online, voor de proef |

Bronnen: officiële bekendmakingen (overheid.nl), CBS, Kadaster BAG, RVO EP-Online, gemeente Nijmegen, PDOK. Zie de docstrings
van de modules voor de voorwaarden per bron.
