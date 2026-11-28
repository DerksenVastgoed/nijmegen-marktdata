# Verbeterlijst

Wat nog niet klopt sinds de splitsing van 11 november 2026.


- **De geplande tijden van GitHub vuren hier uren te laat.** Nagemeten op 18
  november om 16:20 UTC, runs met event "schedule" vanaf 12 november:
  cijfers (01:07) tussen 07:30 en 09:00 UTC; publicatievelden (05:25) tussen
  12:21 en 14:44; voorraad (04:40) tussen 11:42 en 13:47; publicaties (vier
  keer per dag) 16 keer in plaats van 27; regelgeving (zondag 00:05) om
  06:16; gezicht (maandag 03:17) om 11:30. Geen dagelijkse workflow sloeg een
  dag over.
  Publicaties, cijfers en velden worden daarom door de brief zelf gestart
  voor hij ze leest. De voorraad draait alleen op zijn eigen cron; een dag
  oud is daar genoeg (zie voorraad.yml). Regelgeving en gezicht ook; met één
  run elk is nog niet te zeggen of hun vertraging vast is.
- **bestemming.yml draait sinds 28 november wekelijks** (woensdag, cron 02:23
  UTC; vertraging zoals hierboven verwacht). De veldnamen zijn op 28 november
  gemeten (zie verwijzingen_uit). Elk pand zonder verwijzingen wordt een keer
  helemaal opnieuw gevraagd: de hele ring, zes lagen per pand. Dat kost
  meerdere runs van 120 minuten. Sinds de vervolgronde (zelfde patroon als
  inhaal-3dbag.yml) start een ronde met alles zichzelf opnieuw tot de
  wachtrij leeg is, met maximaal 15 schakels. De maten van de maatvoering
  (zevende laag) staan in het veld 'maatvoering', gemeten op 28 november.

- **planregels.py (28 november)** haalt de tekst op van elk artikel waar een
  bestemming naar wijst, en koppelt elke functieaanduiding aan zijn bepaling
  (232 van 240 na de eerste ronde; de rest staat niet in het artikel van de
  bestemming, mogelijk in een algemeen hoofdstuk, dat nog niet wordt gelezen).
  Het dossier toont de bepaling. Nog niet gebouwd: het gebruik op de
  shortlist van de brief (ruimte en wrijving).
