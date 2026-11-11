# Lees dit voordat je iets bouwt

Deze repo is openbaar. Hij is op 11 november 2026 afgesplitst van de privé repo
van de vastgoedbrief, zodat de ophaalrondes gratis Actions-minuten gebruiken.
De brief haalt deze repo op in `marktdata/` en leest de modules en gegevens
hieruit.

## De regel voor wat hier mag

Een bestand mag hier alleen staan als het volledig uit een openbare bron komt
(overheid, PDOK, CBS, Kadaster open data) en niets zegt over Derksen Vastgoed,
de familie of de eigen panden. Twijfel = privé. Niet hier: gegevens uit de
mailbox, eigen bouwkosten en inkoopprijzen, de brieven, en gegevens die met de
hand van een platform zijn geplakt.

## Eerst lezen

1. `eisen.txt`: elke eis met waarom en met de proef die hem afdwingt.
2. `VERBETERLIJST.md`: wat nog niet klopt sinds de splitsing.
3. `python3 eisen.py --proef`: draai dit voor je begint en voor je committeert.

## Wat deze repo niet mag

- Nooit iets uit de brief-repo lezen of ernaar verwijzen in code. Een openbare
  repo die naar een privé repo kijkt, maakt die privé repo openbaar. Controles
  die nameten dat de brief zich aan een afspraak van hier houdt, staan in de
  brief (`marktdata_toets.py`).
- `jeleefomgeving.nl` geeft ROBOTS_DISALLOWED. Daar wordt niet geautomatiseerd
  opgehaald.
- Zichtbaarheid van de repo en de secrets zijn van Mark. Claude zet die niet om
  en maakt geen tokens aan.

## De werkwijze

Dezelfde als in de brief: meet voordat je iets beweert, breek elke controle om
te zien of hij vuurt, "niet gekeken" en "niets gevonden" krijgen nooit hetzelfde
woord, en één implementatie per afspraak. Mark accepteert pull requests een voor
een en leest de uitleg in de PR.
