# Portfolio-Performance MCP Server – Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Build-Abhängigkeiten für native Pakete (pycryptodome)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    python3-dev \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Non-root User – UID/GID passend zum Besitzer der gemounteten Portfolio-Dateien
# wählbar über Build-Args (Default: bisheriges Verhalten mit freier UID/GID).
# Für den Betrieb auf nas-intern (Synology-ACL erlaubt nur bestimmte User/Gruppen)
# werden beim Build UID=1026 (norbert), GID=100 (users) übergeben – siehe
# docker-compose.yml.
ARG MCPUSER_UID=1000
ARG MCPUSER_GID=1000
RUN (getent group ${MCPUSER_GID} || groupadd -g ${MCPUSER_GID} mcpuser) \
    && useradd --create-home --shell /bin/bash --uid ${MCPUSER_UID} --gid ${MCPUSER_GID} mcpuser

# Python-Abhängigkeiten
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Anwendungscode
COPY src/ ./src/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && chown -R mcpuser:${MCPUSER_GID} /app

# Umgebungsvariablen
ENV PYTHONPATH=/app
ENV MCP_SERVER_HOST=0.0.0.0
ENV MCP_SERVER_PORT=8080
ENV MCP_TRANSPORT=streamable-http

EXPOSE 8080

# Healthcheck: prüft, ob der MCP-Port erreichbar ist
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import socket,sys; s=socket.socket(); s.settimeout(2); sys.exit(s.connect_ex(('localhost',8080)))" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "src/main.py"]
