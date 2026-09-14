#!/bin/bash
# Con il wing non si plana sul vento medio. Questo comando NON decide niente:
# guarda come si distribuiscono davvero, sull'archivio di Torbole dal 2012, le
# tre grandezze separate - vento medio, raffica ricorrente, raffica massima -
# e per ogni soglia candidata quante giornate la superano e PER QUANTO TEMPO.
# Le soglie operative si scelgono dopo, guardando questi numeri.
# Nessuno scaricamento: usa l'archivio che hai gia'. Qualche minuto.
cd "$(dirname "$0")/Garda Wind.app/Contents/Resources" || exit 1
PY=/usr/bin/python3; command -v python3 >/dev/null && PY="$(command -v python3)"

OUT="$HOME/Desktop/Garda Wind - raffiche.txt"

echo "════════════════════════════════════════════════════════════"
echo "  Analisi descrittiva delle raffiche"
echo "════════════════════════════════════════════════════════════"
echo
echo "Tre grandezze, tenute separate:"
echo "  vento medio          la media del vento"
echo "  raffica ricorrente   il livello di raffica che TORNA: mediana"
echo "                       mobile su mezz'ora, quindi un colpo isolato"
echo "                       non la alza"
echo "  raffica massima      il picco, che da solo non fa una sessione"
echo
echo "Piu' la durata: una soglia superata per venti minuti e' un colpo"
echo "di vento, una superata per tre ore e' una giornata."
echo

"$PY" -m gardawind --raffiche 2>&1 | tee "$OUT"

echo
echo "════════════════════════════════════════════════════════════"
echo "  Fatto. Sulla Scrivania:"
echo "    Garda Wind - raffiche.txt"
echo "  Trascinalo nella chat: le soglie le scegliamo su questi numeri,"
echo "  non su una tabella teorica."
echo "════════════════════════════════════════════════════════════"
open "$HOME/Desktop" 2>/dev/null
echo
read -n 1 -s -r -p "Premi un tasto per chiudere."
