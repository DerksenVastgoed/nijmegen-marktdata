#!/usr/bin/env bash
# Gegevens van een ronde terugcommitten, zonder ooit broncode te raken.
#
# Gebruik: ./terugcommitten.sh "<commitbericht>" bestand1 bestand2 ...
#
# EEN IMPLEMENTATIE. Dit stond als functie in voorraad.yml. Toen er op 11
# november een tweede workflow bij kwam die terugcommit (publicaties.yml), werd
# het een script: twee kopieën van deze lus lopen uiteen, en in deze lus zitten
# drie fouten die elk een ronde hebben gekost.
#
# 1. OPNIEUW BOVENOP DE REMOTE, NIET REBASEN (12 oktober). Een lus met
#    "git pull --rebase --autostash || true" liep vast op een conflict in
#    voorraad.json; de ingeslikte fout liet de repo halverwege een rebase staan
#    en de volgende pushes faalden direct. Deze bestanden worden in hun geheel
#    door de ronde gemaakt, dus er valt niets samen te voegen: HEAD naar de
#    remote, onze bestanden opnieuw toevoegen, opnieuw committen.
# 2. MIXED EN NIET SOFT (13 oktober). "git reset --soft" laat de hele index van
#    de oude checkout staan; de commit van een ronde van 102 minuten draaide
#    daarmee twee PR's terug die tijdens de ronde waren gemerged.
# 3. EEN GEGEVENSCOMMIT RAAKT NOOIT BRONCODE, en nooit een bestand buiten de
#    lijst. Beide worden hieronder nagemeten, los van de resetmodus.
set -uo pipefail
set -x
BERICHT="$1"; shift
BESTANDEN="$*"
TAK="${GITHUB_REF_NAME:-$(git rev-parse --abbrev-ref HEAD)}"
git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

voeg_toe() {
  for f in $BESTANDEN; do
    if [ -f "$f" ]; then
      git add "$f"
      echo "  $f ($(wc -c < "$f") bytes)"
    else
      echo "  $f ONTBREEKT"
    fi
  done
}

geen_broncode() {
  local raakt
  raakt=$(git diff --name-only HEAD~1 HEAD -- '*.py' '*.yml' '*.sh' 2>/dev/null || true)
  if [ -n "$raakt" ]; then
    echo "GESTOPT: deze commit raakt broncode: $raakt"
    return 1
  fi
  return 0
}

alleen_de_lijst() {
  local lijst=" $(echo $BESTANDEN) " vreemd=""
  for f in $(git diff --cached --name-only); do
    case "$lijst" in
      *" $f "*) ;;
      *) vreemd="$vreemd $f" ;;
    esac
  done
  if [ -n "$vreemd" ]; then
    echo "GESTOPT: deze commit zou bestanden buiten de lijst veranderen:$vreemd"
    return 1
  fi
  return 0
}

voeg_toe
alleen_de_lijst || exit 1
if git diff --cached --quiet; then
  echo "Niets gewijzigd, niets te committen"
  exit 0
fi
git commit -m "$BERICHT"
for poging in 1 2 3; do
  geen_broncode || exit 1
  if git push; then
    echo "Teruggecommit gelukt"
    exit 0
  fi
  echo "Push mislukt, poging $poging; opnieuw bovenop de remote"
  git rebase --abort 2>/dev/null || true
  if ! git fetch origin "$TAK"; then
    echo "Kan $TAK niet ophalen van de remote; staat die tak daar wel?"
    exit 1
  fi
  git reset "origin/$TAK"
  voeg_toe
  alleen_de_lijst || exit 1
  if git diff --cached --quiet; then
    echo "Na het bijtrekken is er niets meer te committen"
    exit 0
  fi
  git commit -m "$BERICHT"
done
echo "Terugcommitten mislukt na drie pogingen"
exit 1
