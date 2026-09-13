#!/bin/bash
# Scarica i predittori "come erano" a ogni scadenza e misura, scadenza per
# scadenza, quanto vale davvero la previsione. Alla fine scrive due file sulla
# Scrivania da trascinare nella chat.
cd "$(dirname "$0")/Garda Wind.app/Contents/Resources" || exit 1
PY=/usr/bin/python3; command -v python3 >/dev/null && PY="$(command -v python3)"

OUT="$HOME/Desktop/Garda Wind - rapporto.txt"
JSON="$HOME/Desktop/Garda Wind - rapporto.json"

echo "════════════════════════════════════════════════════════════"
echo "  Misura di affidabilità — Garda Wind"
echo "════════════════════════════════════════════════════════════"
echo
echo "Due fasi. La prima scarica; la seconda misura."
echo
echo "FASE 1 di 2 — scarico i predittori per ogni scadenza."
echo "  Serve a sapere cosa i modelli dicevano 1, 2, 3... 7 giorni prima,"
echo "  invece di indovinarlo. È la parte lunga: anche 20-40 minuti la"
echo "  prima volta. Puoi lasciarla andare e fare altro, ma non chiudere"
echo "  questa finestra."
echo
"$PY" -m gardawind --backfill 2>&1 | tee "$OUT"

echo
echo "FASE 2 di 2 — misuro." | tee -a "$OUT"
echo "  Nessuno scaricamento, solo calcolo. Qualche minuto."
echo
"$PY" -m gardawind --validate --validate-json "$JSON" 2>&1 | tee -a "$OUT"

echo
echo "════════════════════════════════════════════════════════════"
echo "  Fatto."
echo
echo "  Sulla Scrivania trovi due file:"
echo "    Garda Wind - rapporto.txt"
echo "    Garda Wind - rapporto.json"
echo
echo "  Trascinali nella chat e li leggiamo insieme."
echo "════════════════════════════════════════════════════════════"
open "$HOME/Desktop" 2>/dev/null
echo
read -n 1 -s -r -p "Premi un tasto per chiudere."
