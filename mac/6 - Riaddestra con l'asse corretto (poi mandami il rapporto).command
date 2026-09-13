#!/bin/bash
# L'asse del regime e' cambiato: da 24 gradi (geometria del lago) a 54 gradi
# (cio' che la centralina di Torbole misura davvero). Questo cambia la
# definizione di "il Pelèr è entrato", quindi cambia il bersaglio, quindi
# TUTTO va riaddestrato e rivalidato da capo.
# Nessuno scaricamento: usa l'archivio che hai gia'. Qualche minuto.
cd "$(dirname "$0")/Garda Wind.app/Contents/Resources" || exit 1
PY=/usr/bin/python3; command -v python3 >/dev/null && PY="$(command -v python3)"

OUT="$HOME/Desktop/Garda Wind - asse corretto.txt"
JSON="$HOME/Desktop/Garda Wind - asse corretto.json"

echo "════════════════════════════════════════════════════════════"
echo "  Riaddestramento con l'asse osservato"
echo "════════════════════════════════════════════════════════════"
echo
echo "Cosa cambia: fino a ieri una giornata era \"Pelèr entrato\" se la"
echo "direzione stava entro 70 gradi da 24. Ora il confronto e' con 54,"
echo "che e' dove il vento arriva davvero a quella centralina. Cambiano"
echo "i positivi e i negativi, quindi cambia tutto cio' che ci sta sopra."
echo
echo "1 di 3 — riaddestro sui bersagli ridefiniti."
"$PY" -m gardawind --train 2>&1 | tee "$OUT"

echo | tee -a "$OUT"
echo "2 di 3 — rivalido, scadenza per scadenza, sul periodo comune." | tee -a "$OUT"
"$PY" -m gardawind --validate --periodo-comune --validate-json "$JSON" 2>&1 | tee -a "$OUT"

echo | tee -a "$OUT"
echo "3 di 3 — ricontrollo le direzioni con il nuovo riferimento." | tee -a "$OUT"
echo "  Qui la tabella dei settori e' ora centrata su 54: e' quella che" | tee -a "$OUT"
echo "  dice quanto stretto conviene tenere il settore." | tee -a "$OUT"
"$PY" -m gardawind --direzioni 2>&1 | tee -a "$OUT"

echo
echo "════════════════════════════════════════════════════════════"
echo "  Fatto. Sulla Scrivania:"
echo "    Garda Wind - asse corretto.txt"
echo "    Garda Wind - asse corretto.json"
echo "  Trascinali nella chat: confrontiamo con i numeri di prima."
echo "════════════════════════════════════════════════════════════"
open "$HOME/Desktop" 2>/dev/null
echo
read -n 1 -s -r -p "Premi un tasto per chiudere."
