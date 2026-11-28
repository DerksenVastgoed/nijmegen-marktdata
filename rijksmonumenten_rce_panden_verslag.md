# RCE-rijksmonumenten gekoppeld aan BAG-panden

- FOUT https://service.pdok.nl/lv/bag/wfs/v2_0?service=WFS&version=2.0.0&request=GetFeature&typeName=bag%3Apand&outputFormat=application%2Fjson&bbox=186126.2641635364%2C431911.3652384771%2C186127.2641635364%2C431912.3652384771%2Curn%3Aogc%3Adef%3Acrs%3AEPSG%3A%3A28992: ConnectionResetError [Errno 104] Connection reset by peer
- FOUT https://service.pdok.nl/lv/bag/wfs/v2_0?service=WFS&version=2.0.0&request=GetFeature&typeName=bag%3Apand&outputFormat=application%2Fjson&bbox=186118.66926508743%2C431869.7146620613%2C186119.66926508743%2C431870.7146620613%2Curn%3Aogc%3Adef%3Acrs%3AEPSG%3A%3A28992: ConnectionResetError [Errno 104] Connection reset by peer
- FOUT https://service.pdok.nl/lv/bag/wfs/v2_0?service=WFS&version=2.0.0&request=GetFeature&typeName=bag%3Apand&outputFormat=application%2Fjson&bbox=186183.86417270853%2C431737.6152980671%2C186184.86417270853%2C431738.6152980671%2Curn%3Aogc%3Adef%3Acrs%3AEPSG%3A%3A28992: ConnectionResetError [Errno 104] Connection reset by peer
- 252 nummers gevraagd, 9 zonder antwoord, 47 met een punt buiten elk pand
- toets tegen het register (pand in de ring, nummer in beide): 90, waarvan 86 hetzelfde pand en 4 een ander
  - ('523032', None, ['0268100000030637'], ['0268100000030170', '0268100000030172', '0268100000030173', '0268100000030174'])
  - ('31169', None, ['0268100000045386', '0268100000047325'], ['0268100000045384'])
  - ('31176', None, ['0268100000009784'], ['0268100000011000'])
  - ('31180', None, ['0268100000009786'], ['0268100000011004'])
- nummers met een pand in de ring: 109, waarvan niet in het register: 20
