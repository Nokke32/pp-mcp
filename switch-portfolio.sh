#!/usr/bin/env bash
#
# switch-portfolio.sh — Portfolio-Datei des lokal laufenden pp-mcp-Servers umschalten.
#
# Setzt PP_FILE_PATH in der .env des deployten Servers und startet den
# launchd-Dienst neu (der Server liest PP_FILE_PATH nur beim Start).
#
# Aufruf:
#   ./switch-portfolio.sh "/path/to/portfolios/Example.portfolio"
#   ./switch-portfolio.sh --list      # aktive .portfolio-Dateien ausgeben (für Menü)
#
set -euo pipefail

# PATH ergänzen, damit Tools auch aus der Kurzbefehle-Umgebung gefunden werden
export PATH="/usr/local/bin:/opt/homebrew/bin:/bin:/usr/bin:$PATH"

# --- Konfiguration -----------------------------------------------------------
APP_DIR="/path/to/deployed/pp-mcp"      # deployter Server
ENV_FILE="$APP_DIR/.env"
PORTFOLIO_DIR="/path/to/portfolios"     # Ordner mit den .portfolio-Dateien
SERVICE="de.pp-mcp.server"                          # launchd-Label
# -----------------------------------------------------------------------------

# --list: aktive .portfolio-Dateien auflisten (Backups/Konflikt-Kopien raus)
if [[ "${1:-}" == "--list" ]]; then
  find "$PORTFOLIO_DIR" -maxdepth 1 -name '*.portfolio' \
    ! -name '*.backup*' ! -name '*conflicted*' -print | sort
  exit 0
fi

SELECTED="${1:-}"
if [[ -z "$SELECTED" ]]; then
  echo "Fehler: Kein Pfad übergeben. Aufruf: $0 /pfad/zur/datei.portfolio" >&2
  exit 1
fi
if [[ ! -f "$SELECTED" ]]; then
  echo "Fehler: Datei nicht gefunden: $SELECTED" >&2
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Fehler: .env nicht gefunden: $ENV_FILE" >&2
  exit 1
fi

# PP_FILE_PATH-Zeile in der .env ersetzen (awk ist sicher bei Leerzeichen/&-Zeichen)
tmp="$(mktemp)"
awk -v val="$SELECTED" '
  /^PP_FILE_PATH=/ { print "PP_FILE_PATH=" val; found=1; next }
  { print }
  END { if (!found) print "PP_FILE_PATH=" val }
' "$ENV_FILE" > "$tmp" && mv "$tmp" "$ENV_FILE"

# launchd-Dienst neu starten (-k beendet die laufende Instanz zuerst)
launchctl kickstart -k "gui/$(id -u)/$SERVICE"

# Kurz warten, bis der Port wieder lauscht (max. ~5 s)
for _ in $(seq 1 25); do
  if lsof -nP -iTCP:8080 -sTCP:LISTEN >/dev/null 2>&1; then break; fi
  sleep 0.2
done

echo "✅ pp-mcp läuft jetzt auf: $(basename "$SELECTED")"
