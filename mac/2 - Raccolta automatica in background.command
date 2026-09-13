#!/bin/bash
# Installa un agente di sistema che interroga le centraline ogni 15 minuti
# anche ad app chiusa. Serve soprattutto a Malcesine, che pubblica solo
# l'istante corrente: ogni passaggio mancato e' un dato perso per sempre.
set -e
RES="$(cd "$(dirname "$0")/Garda Wind.app/Contents/Resources" && pwd)"
PY=/usr/bin/python3; command -v python3 >/dev/null && PY="$(command -v python3)"
PLIST="$HOME/Library/LaunchAgents/it.gardawind.poller.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
 <key>Label</key><string>it.gardawind.poller</string>
 <key>ProgramArguments</key>
 <array><string>$PY</string><string>-m</string><string>gardawind</string><string>--poll-once</string></array>
 <key>WorkingDirectory</key><string>$RES</string>
 <key>StartInterval</key><integer>900</integer>
 <key>RunAtLoad</key><true/>
 <key>StandardOutPath</key><string>$HOME/Library/Application Support/Garda Wind/poller.log</string>
 <key>StandardErrorPath</key><string>$HOME/Library/Application Support/Garda Wind/poller.log</string>
</dict></plist>
EOF
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Raccolta automatica attiva (ogni 15 minuti)."
echo "Per disattivarla usa il comando 3."
read -n 1 -s -r -p "Premi un tasto per chiudere."
