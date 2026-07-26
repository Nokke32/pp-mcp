#!/usr/bin/env bash
# Uploads the local CLAUDE.md to Gitea directly via `tea api` (Contents API),
# without creating a commit. CLAUDE.md is deliberately not tracked in git
# (see .gitignore) and must therefore never end up on GitHub via the normal
# main -> github-main cherry-pick workflow (it contains internal paths/domains).
#
# Usage: ./sync-claude-md.sh
set -euo pipefail

cd "$(dirname "$0")"

FILE="CLAUDE.md"
[ -f "$FILE" ] || { echo "$FILE not found." >&2; exit 1; }

LOCAL_B64=$(base64 < "$FILE" | tr -d '\n')

# Fetch the current state from Gitea (if the file already exists -> need the sha for update)
REMOTE_JSON=$(tea api "/repos/{owner}/{repo}/contents/$FILE" 2>/dev/null || true)
REMOTE_SHA=$(echo "$REMOTE_JSON" | grep -o '"sha":"[^"]*"' | head -1 | cut -d'"' -f4 || true)
REMOTE_CONTENT_B64=$(echo "$REMOTE_JSON" | grep -o '"content":"[^"]*"' | head -1 | cut -d'"' -f4 | tr -d '\n' || true)

if [ -n "$REMOTE_CONTENT_B64" ] && [ "$REMOTE_CONTENT_B64" = "$LOCAL_B64" ]; then
    echo "CLAUDE.md is already up to date on Gitea, no upload needed."
    exit 0
fi

TMP_PAYLOAD=$(mktemp)
trap 'rm -f "$TMP_PAYLOAD"' EXIT

if [ -n "$REMOTE_SHA" ]; then
    printf '{"content":"%s","sha":"%s","message":"CLAUDE.md updated (via sync-claude-md.sh)"}' \
        "$LOCAL_B64" "$REMOTE_SHA" > "$TMP_PAYLOAD"
    tea api -X PUT "/repos/{owner}/{repo}/contents/$FILE" -d "@$TMP_PAYLOAD"
    echo "CLAUDE.md updated on Gitea."
else
    printf '{"content":"%s","message":"CLAUDE.md added (via sync-claude-md.sh)"}' \
        "$LOCAL_B64" > "$TMP_PAYLOAD"
    tea api -X POST "/repos/{owner}/{repo}/contents/$FILE" -d "@$TMP_PAYLOAD"
    echo "CLAUDE.md created on Gitea."
fi
