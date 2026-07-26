"""Entry point for the Portfolio Performance MCP server.

Starts only the MCP server (no web UI). The transport can be selected via
`MCP_TRANSPORT` (`stdio` | `streamable-http` | `sse`, default
`streamable-http`).
"""
import logging
import uvicorn

from src.config import settings

SUPPORTED_TRANSPORTS = {"stdio", "sse", "streamable-http"}

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
    from src.mcp_server import app, build_mcp_asgi_app

    transport = settings.MCP_TRANSPORT.strip().lower()
    if transport not in SUPPORTED_TRANSPORTS:
        logger.warning(
            f"Unsupported MCP_TRANSPORT '{settings.MCP_TRANSPORT}', "
            f"using 'streamable-http'"
        )
        transport = "streamable-http"

    if not settings.PP_FILE_PATH:
        logger.warning("PP_FILE_PATH is not set – tools will only return data once configured.")

    if (
        transport != "stdio"
        and settings.MCP_REQUIRE_AUTH
        and not settings.MCP_AUTH_TOKEN.strip()
    ):
        raise SystemExit(
            "MCP_REQUIRE_AUTH is enabled, but MCP_AUTH_TOKEN is not set. "
            "Server startup aborted to prevent unprotected public access. "
            "Please set MCP_AUTH_TOKEN."
        )

    if transport == "stdio":
        logger.info(
            f"Starting MCP server (transport=stdio, "
            f"file={settings.PP_FILE_PATH or '<not set>'})"
        )
        app.run(transport="stdio")
        return

    logger.info(
        f"Starting MCP server on {settings.MCP_SERVER_HOST}:{settings.MCP_SERVER_PORT} "
        f"(transport={transport}, file={settings.PP_FILE_PATH or '<not set>'})"
    )
    uvicorn.run(
        build_mcp_asgi_app(transport),
        host=settings.MCP_SERVER_HOST,
        port=settings.MCP_SERVER_PORT,
        log_level=_log_level_name.lower(),
    )


if __name__ == "__main__":
    main()
