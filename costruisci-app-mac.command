#!/bin/bash
# Costruisce la cartella "Garda Wind" pronta all'uso, a partire da UNA sola
# copia del codice.
#
# Perche' esiste questo script. Fino alla 3.6 il pacchetto gardawind viveva in
# tre posti: dentro il bundle .app, dentro cloud/, e nella copia di lavoro. Tre
# copie della stessa cosa divergono sempre, e in un repository git la divergenza
# diventa invisibile finche' non fa danni. Qui il codice sta in un posto solo
# (gardawind/) e il bundle viene assemblato quando serve.
set -e
cd "$(dirname "$0")"
DEST="${1:-Garda Wind}"

echo "Costruisco \"$DEST\"…"
rm -rf "$DEST"
mkdir -p "$DEST/Garda Wind.app/Contents/MacOS"
mkdir -p "$DEST/Garda Wind.app/Contents/Resources"

cp -R gardawind "$DEST/Garda Wind.app/Contents/Resources/"
find "$DEST" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
cp mac/Info.plist "$DEST/Garda Wind.app/Contents/Info.plist"
cp mac/GardaWind "$DEST/Garda Wind.app/Contents/MacOS/GardaWind"
chmod +x "$DEST/Garda Wind.app/Contents/MacOS/GardaWind"

cp mac/*.command "$DEST/"
cp mac/LEGGIMI.txt "$DEST/"
chmod +x "$DEST/"*.command

mkdir -p "$DEST/test"
cp test/*.py "$DEST/test/" 2>/dev/null || true

echo
echo "Fatto: \"$DEST\""
echo "  L'app e i comandi numerati sono dentro. Il codice resta in gardawind/,"
echo "  che e' l'unica copia: se lo modifichi, rilancia questo script."
echo
read -n 1 -s -r -p "Premi un tasto per chiudere." 2>/dev/null || true
