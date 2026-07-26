#!/bin/sh
# Entrypoint for the Portfolio Performance MCP Server.
# The portfolio file is mounted read-only; we just switch to the non-root
# user and start the application.
set -e

echo "Starting PP MCP Server..."
exec gosu mcpuser python src/main.py
