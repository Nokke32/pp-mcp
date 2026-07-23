"""Einstiegspunkt für den Portfolio-Performance MCP Server.

Startet ausschließlich den MCP-Server (kein Web-UI). Der Transport ist über
`MCP_TRANSPORT` wählbar (`streamable-http` | `sse`, Default `streamable-http`).
"""
import logging
import uvicorn

from src.config import settings

_log_level_name = settings.LOG_LEVEL.strip().upper()
_log_level = getattr(logging, _log_level_name, None)
if not isinstance(_log_level, int):
    _log_level = logging.INFO
    _log_level_name = "INFO"

logging.basicConfig(
    level=_log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    from src.mcp_server import build_mcp_asgi_app

    transport = settings.MCP_TRANSPORT.strip().lower()
    if transport not in {"sse", "streamable-http"}:
        logger.warning(
            f"Nicht unterstützter MCP_TRANSPORT '{settings.MCP_TRANSPORT}', "
            f"nutze 'streamable-http'"
        )
        transport = "streamable-http"

    if not settings.PP_FILE_PATH:
        logger.warning("PP_FILE_PATH ist nicht gesetzt – Tools liefern erst nach Konfiguration Daten.")

    if settings.MCP_REQUIRE_AUTH and not settings.MCP_AUTH_TOKEN.strip():
        raise SystemExit(
            "MCP_REQUIRE_AUTH ist aktiv, aber MCP_AUTH_TOKEN ist nicht gesetzt. "
            "Server-Start abgebrochen, um einen ungeschützten öffentlichen Zugriff "
            "zu verhindern. Bitte MCP_AUTH_TOKEN setzen."
        )

    logger.info(
        f"Starte MCP-Server auf {settings.MCP_SERVER_HOST}:{settings.MCP_SERVER_PORT} "
        f"(transport={transport}, datei={settings.PP_FILE_PATH or '<nicht gesetzt>'})"
    )
    uvicorn.run(
        build_mcp_asgi_app(transport),
        host=settings.MCP_SERVER_HOST,
        port=settings.MCP_SERVER_PORT,
        log_level=_log_level_name.lower(),
    )


if __name__ == "__main__":
    main()
