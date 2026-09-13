#!/bin/bash
# Le due diagnosi che vengono prima di ogni altra ottimizzazione:
#   1. dove cade davvero la distribuzione direzionale osservata;
#   2. le scadenze confrontate sugli STESSI giorni.
# Nessuno scaricamento: legge solo l'archivio che hai gia'. Pochi minuti.
cd "$(dirname "$0")/Garda Wind.app/Contents/Resources" || exit 1
PY=/usr/bin/python3; command -v python3 >/dev/null && PY="$(command -v python3)"

OUT="$HOME/Desktop/Garda Wind - direzioni.txt"
JSON="$HOME/Desktop/Garda Wind - periodo comune.json"

echo "════════════════════════════════════════════════════════════"
echo "  Due diagnosi, nessuno scaricamento"
echo "════════════════════════════════════════════════════════════"
echo
echo "1 di 2 — da dove viene il vento, davvero."
echo "  L'asse del Pelèr è dichiarato a 24 gradi perché è la geometria"
echo "  del lago. Ma la geometria del lago non è la direzione che vede"
echo "  quella centralina. Se l'asse è spostato, è spostata anche la"
echo "  definizione di \"il Pelèr è entrato\", e quindi il bersaglio su"
echo "  cui il modello impara. Questo lo verifica. Pochi secondi."
echo
"$PY" -m gardawind --direzioni 2>&1 | tee "$OUT"

echo | tee -a "$OUT"
echo "2 di 2 — le scadenze sugli stessi giorni." | tee -a "$OUT"
echo "  Nella prima tabella la riga di oggi copriva il 2021-2026 e le"
echo "  altre solo il 2024-2026: non erano confrontabili. Qui tutte"
echo "  guardano lo stesso periodo. Qualche minuto."
echo
"$PY" -m gardawind --validate --periodo-comune --validate-json "$JSON" 2>&1 | tee -a "$OUT"

echo
echo "════════════════════════════════════════════════════════════"
echo "  Fatto. Sulla Scrivania:"
echo "    Garda Wind - direzioni.txt"
echo "    Garda Wind - periodo comune.json"
echo "  Trascinali nella chat."
echo "════════════════════════════════════════════════════════════"
open "$HOME/Desktop" 2>/dev/null
echo
read -n 1 -s -r -p "Premi un tasto per chiudere."
