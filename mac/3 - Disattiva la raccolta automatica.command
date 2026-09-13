#!/bin/bash
PLIST="$HOME/Library/LaunchAgents/it.gardawind.poller.plist"
launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "Raccolta automatica disattivata e agente rimosso."
read -n 1 -s -r -p "Premi un tasto per chiudere."
