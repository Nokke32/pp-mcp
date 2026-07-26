#!/usr/bin/env bash
#
# switch-portfolio.sh — switch the portfolio file of the locally running
# pp-mcp server.
#
# Sets PP_FILE_PATH in the deployed server's .env and restarts the launchd
# service (the server only reads PP_FILE_PATH at startup).
#
# Usage:
#   ./switch-portfolio.sh "/path/to/portfolios/Example.portfolio"
#   ./switch-portfolio.sh --list      # print active .portfolio files (for a menu)
#
set -euo pipefail

# Extend PATH so tools are also found from the Shortcuts environment
export PATH="/usr/local/bin:/opt/homebrew/bin:/bin:/usr/bin:$PATH"

# --- Configuration -----------------------------------------------------------
APP_DIR="/path/to/deployed/pp-mcp"      # deployed server
ENV_FILE="$APP_DIR/.env"
PORTFOLIO_DIR="/path/to/portfolios"     # folder with the .portfolio files
SERVICE="de.pp-mcp.server"                          # launchd label
# -----------------------------------------------------------------------------

# --list: list active .portfolio files (excluding backups/conflict copies)
if [[ "${1:-}" == "--list" ]]; then
  find "$PORTFOLIO_DIR" -maxdepth 1 -name '*.portfolio' \
    ! -name '*.backup*' ! -name '*conflicted*' -print | sort
  exit 0
fi

SELECTED="${1:-}"
if [[ -z "$SELECTED" ]]; then
  echo "Error: no path given. Usage: $0 /path/to/file.portfolio" >&2
  exit 1
fi
if [[ ! -f "$SELECTED" ]]; then
  echo "Error: file not found: $SELECTED" >&2
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: .env not found: $ENV_FILE" >&2
  exit 1
fi

# Replace the PP_FILE_PATH line in .env (awk is safe with spaces/& characters)
tmp="$(mktemp)"
awk -v val="$SELECTED" '
  /^PP_FILE_PATH=/ { print "PP_FILE_PATH=" val; found=1; next }
  { print }
  END { if (!found) print "PP_FILE_PATH=" val }
' "$ENV_FILE" > "$tmp" && mv "$tmp" "$ENV_FILE"

# Restart the launchd service (-k stops the running instance first)
launchctl kickstart -k "gui/$(id -u)/$SERVICE"

# Wait briefly until the port is listening again (max. ~5 s)
for _ in $(seq 1 25); do
  if lsof -nP -iTCP:8080 -sTCP:LISTEN >/dev/null 2>&1; then break; fi
  sleep 0.2
done

echo "✅ pp-mcp is now running: $(basename "$SELECTED")"
