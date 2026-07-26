"""Configuration for the Portfolio Performance MCP server.

All values are loaded from environment variables or a `.env` file.
"""
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings sourced from environment variables."""

    # Application
    APP_NAME: str = "PP MCP Server"
    APP_VERSION: str = "0.1.0"

    # Path to the Portfolio Performance file (.portfolio). Fallback for single-file
    # operation (internally creates a single source "default") – ignored if
    # PP_PORTFOLIOS_CONFIG is set.
    PP_FILE_PATH: str = Field(default="", env="PP_FILE_PATH")
    # Optional password for AES-encrypted files. Empty = unencrypted.
    PP_PASSWORD: Optional[str] = Field(default=None, env="PP_PASSWORD")
    # Path to a JSON file with multiple portfolio sources:
    # [{"id": "...", "label": "...", "path": "...", "password": "..."}, ...]
    # If set, this takes precedence over PP_FILE_PATH/PP_PASSWORD.
    PP_PORTFOLIOS_CONFIG: str = Field(default="", env="PP_PORTFOLIOS_CONFIG")

    # MCP server – container port is fixed at 8080
    MCP_SERVER_HOST: str = "0.0.0.0"
    MCP_SERVER_PORT: int = 8080
    MCP_TRANSPORT: str = Field(default="streamable-http", env="MCP_TRANSPORT")
    # Optional bearer token to protect the HTTP endpoints. Empty = no
    # authentication (only safe within a trusted local network).
    MCP_AUTH_TOKEN: str = Field(default="", env="MCP_AUTH_TOKEN")
    # If true: the server aborts startup if MCP_AUTH_TOKEN is empty.
    # Defaults to false so existing local/trusted deployments without a
    # token don't break. Set to true for publicly reachable deployments
    # (e.g. docker-compose.yml).
    MCP_REQUIRE_AUTH: bool = Field(default=False, env="MCP_REQUIRE_AUTH")

    # Log level for Python logging and uvicorn (DEBUG/INFO/WARNING/ERROR/CRITICAL).
    LOG_LEVEL: str = Field(default="INFO", env="LOG_LEVEL")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# Global settings instance
settings = Settings()
