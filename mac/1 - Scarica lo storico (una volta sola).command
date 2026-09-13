#!/bin/bash
cd "$(dirname "$0")/Garda Wind.app/Contents/Resources" || exit 1
PY=/usr/bin/python3; command -v python3 >/dev/null && PY="$(command -v python3)"
echo "Scarico gli archivi storici delle centraline e i predittori."
echo "La prima volta richiede parecchi minuti: l'archivio di Torbole"
echo "sono oltre 700.000 misure a 10 minuti dal 2012."
echo
"$PY" -m gardawind --backfill
echo
echo "Fatto. Puoi chiudere questa finestra e aprire Garda Wind."
read -n 1 -s -r -p "Premi un tasto per chiudere."
