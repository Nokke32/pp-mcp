#!/bin/sh
# Entrypoint für den Portfolio-Performance MCP Server.
# Die Portfolio-Datei wird read-only gemountet; wir wechseln nur auf den
# non-root User und starten die Anwendung.
set -e

echo "Starte PP MCP Server..."
exec gosu mcpuser python src/main.py
