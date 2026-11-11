# Gemeentelijke monumenten: twee open bronnen

## Gemeenteblad (SRU)
- NIET OPGEHAALD https://repository.overheid.nl/sru?operation=searchRetrieve&version=2.0&query=dt.creator%3D%22Nijmegen%22+and+cql.textAndIndexes%3D%22gemeentelijk+monument%22&maximumRecords=200: robots.txt van https://repository.overheid.nl niet te lezen: <urlopen error [Errno 101] Network is unreachable>
- `dt.creator="Nijmegen" and cql.textAndIndexes="gemeentelijk monument"`: totaal None, gelezen onleesbaar
- NIET OPGEHAALD https://repository.overheid.nl/sru?operation=searchRetrieve&version=2.0&query=dt.creator%3D%22Nijmegen%22+and+dt.title+any+%22monument%22&maximumRecords=200: robots.txt van https://repository.overheid.nl niet te lezen: <urlopen error [Errno 101] Network is unreachable>
- `dt.creator="Nijmegen" and dt.title any "monument"`: totaal None, gelezen onleesbaar
- NIET OPGEHAALD https://repository.overheid.nl/sru?operation=searchRetrieve&version=2.0&query=cql.textAndIndexes%3D%22Nijmegen%22+and+cql.textAndIndexes%3D%22aanwijzing+gemeentelijk+monument%22&maximumRecords=200: robots.txt van https://repository.overheid.nl niet te lezen: <urlopen error [Errno 101] Network is unreachable>
- `cql.textAndIndexes="Nijmegen" and cql.textAndIndexes="aanwijzing gemeentelijk monument"`: totaal None, gelezen onleesbaar

## Wikidata
- NIET OPGEHAALD https://query.wikidata.org/sparql?query=%0ASELECT+%3Fitem+%3FitemLabel+%3Fadres+%3Fcoord+%3FaanduidingLabel+WHERE+%7B%0A++%3Faanduiding+rdfs%3Alabel+%22gemeentelijk+monument%22%40nl+.%0A++%3Fitem+wdt%3AP1435+%3Faanduiding+%3B%0A++++++++wdt%3AP131+%3Fplaats+.%0A++%3Fplaats+rdfs%3Alabel+%22Nijmegen%22%40nl+.%0A++OPTIONAL+%7B+%3Fitem+wdt%3AP6375+%3Fadres+.+%7D%0A++OPTIONAL+%7B+%3Fitem+wdt%3AP625+%3Fcoord+.+%7D%0A++SERVICE+wikibase%3Alabel+%7B+bd%3AserviceParam+wikibase%3Alanguage+%22nl%22.+%7D%0A%7D%0A&format=json: robots.txt van https://query.wikidata.org staat dit niet toe
- geen leesbaar antwoord
