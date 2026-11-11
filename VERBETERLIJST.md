# Verbeterlijst

Wat nog niet klopt sinds de splitsing van 11 november 2026.

- **eisen.py staat twee keer.** Hier en in de brief. Hoort de enige
  implementatie te worden in deze repo, met de brief als gebruiker via
  `marktdata/`. Tot dan lopen de twee kopieën uiteen.
- **De signaaladressen ontbreken.** `voorraad_bag.signaaladressen()` leest
  `pandgeschiedenis.json`, en dat staat in de brief. Daardoor haalt de ronde
  alleen de ring op en niet de adressen met een bekendmaking daarbuiten. Lost
  zich op als het ophalen van de bekendmakingen naar deze repo komt.
- **De inhaalslag van de 3D BAG start niet meer vanzelf.** Die stap stond in
  de voorraadworkflow, maar `bag3d.py` en `bag3d.json` zijn in de brief
  gebleven. Hoort hierheen, samen met `inhaal-3dbag.yml`.
- **Volgende rondes om te verhuizen:** publicatievelden, beschermde gezichten,
  bestemmingen, 3D BAG, en de ophaalstappen van de briefworkflow (CBS,
  criminaliteit, prijsindexen, rente). Zie het structuurplan.
