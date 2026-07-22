#!/usr/bin/env bash
# Lädt die lokale CLAUDE.md per `tea api` direkt auf Gitea hoch (Contents API),
# ohne einen Commit zu erzeugen. CLAUDE.md ist bewusst nicht in git getrackt
# (siehe .gitignore) und darf daher nie über den normalen main -> github-main
# Cherry-Pick-Workflow auf GitHub landen (enthält interne Pfade/Domains).
#
# Nutzung: ./sync-claude-md.sh
set -euo pipefail

cd "$(dirname "$0")"

FILE="CLAUDE.md"
[ -f "$FILE" ] || { echo "$FILE nicht gefunden." >&2; exit 1; }

LOCAL_B64=$(base64 < "$FILE" | tr -d '\n')

# Aktuellen Stand auf Gitea holen (falls Datei schon existiert -> sha fuer Update noetig)
REMOTE_JSON=$(tea api "/repos/{owner}/{repo}/contents/$FILE" 2>/dev/null || true)
REMOTE_SHA=$(echo "$REMOTE_JSON" | grep -o '"sha":"[^"]*"' | head -1 | cut -d'"' -f4 || true)
REMOTE_CONTENT_B64=$(echo "$REMOTE_JSON" | grep -o '"content":"[^"]*"' | head -1 | cut -d'"' -f4 | tr -d '\n' || true)

if [ -n "$REMOTE_CONTENT_B64" ] && [ "$REMOTE_CONTENT_B64" = "$LOCAL_B64" ]; then
    echo "CLAUDE.md ist auf Gitea bereits aktuell, kein Upload noetig."
    exit 0
fi

TMP_PAYLOAD=$(mktemp)
trap 'rm -f "$TMP_PAYLOAD"' EXIT

if [ -n "$REMOTE_SHA" ]; then
    printf '{"content":"%s","sha":"%s","message":"CLAUDE.md aktualisiert (via sync-claude-md.sh)"}' \
        "$LOCAL_B64" "$REMOTE_SHA" > "$TMP_PAYLOAD"
    tea api -X PUT "/repos/{owner}/{repo}/contents/$FILE" -d "@$TMP_PAYLOAD"
    echo "CLAUDE.md auf Gitea aktualisiert."
else
    printf '{"content":"%s","message":"CLAUDE.md hinzugefuegt (via sync-claude-md.sh)"}' \
        "$LOCAL_B64" > "$TMP_PAYLOAD"
    tea api -X POST "/repos/{owner}/{repo}/contents/$FILE" -d "@$TMP_PAYLOAD"
    echo "CLAUDE.md auf Gitea angelegt."
fi
