"""Konfiguration für den Portfolio-Performance MCP Server.

Alle Werte werden aus Umgebungsvariablen bzw. einer `.env`-Datei geladen.
"""
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Anwendungseinstellungen aus Umgebungsvariablen."""

    # Anwendung
    APP_NAME: str = "PP MCP Server"
    APP_VERSION: str = "0.1.0"

    # Pfad zur Portfolio-Performance-Datei (.portfolio). Fallback für Single-File-
    # Betrieb (erzeugt intern eine einzige Quelle "default") – wird ignoriert, wenn
    # PP_PORTFOLIOS_CONFIG gesetzt ist.
    PP_FILE_PATH: str = Field(default="", env="PP_FILE_PATH")
    # Optionales Passwort für AES-verschlüsselte Dateien. Leer = unverschlüsselt.
    PP_PASSWORD: Optional[str] = Field(default=None, env="PP_PASSWORD")
    # Pfad zu einer JSON-Datei mit mehreren Portfolio-Quellen:
    # [{"id": "...", "label": "...", "path": "...", "password": "..."}, ...]
    # Wenn gesetzt, hat dies Vorrang vor PP_FILE_PATH/PP_PASSWORD.
    PP_PORTFOLIOS_CONFIG: str = Field(default="", env="PP_PORTFOLIOS_CONFIG")

    # MCP-Server – Container-Port ist fest 8080
    MCP_SERVER_HOST: str = "0.0.0.0"
    MCP_SERVER_PORT: int = 8080
    MCP_TRANSPORT: str = Field(default="streamable-http", env="MCP_TRANSPORT")
    # Optionaler Bearer-Token zum Schutz der HTTP-Endpunkte. Leer = keine
    # Authentifizierung (nur im vertrauenswürdigen lokalen Netz unbedenklich).
    MCP_AUTH_TOKEN: str = Field(default="", env="MCP_AUTH_TOKEN")
    # Wenn true: Server bricht den Start ab, falls MCP_AUTH_TOKEN leer ist.
    # Default false, um bestehende lokale/vertrauenswürdige Deployments ohne
    # Token nicht zu brechen. Für öffentlich erreichbare Deployments (z.B.
    # docker-compose.yml) auf true setzen.
    MCP_REQUIRE_AUTH: bool = Field(default=False, env="MCP_REQUIRE_AUTH")

    # Log-Level für Python-Logging und uvicorn (DEBUG/INFO/WARNING/ERROR/CRITICAL).
    LOG_LEVEL: str = Field(default="INFO", env="LOG_LEVEL")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# Globale Settings-Instanz
settings = Settings()
